"""Fail-closed production audit and restorable pre-cutover events backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import psycopg2
from dotenv import load_dotenv

from scripts.database.release_backfill import preflight_cursor
from scripts.database.release_contract import (
    DEFAULT_RELEASE_MANIFEST,
    METADATA_COLUMNS,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PROJECT_REF = "ickflwksigaotygtdyko"
EXPECTED_ROWS = 7_878
MIGRATION = ROOT / "database/migrations/006_data_quality_v2_staging.sql"
REACTION_QUALITY_COLUMNS = [f"{asset}_reaction_quality" for asset in ("btc", "eth", "sol")]
REACTION_COLUMNS = [
    f"{asset}_{horizon}"
    for asset in ("btc", "eth", "sol")
    for horizon in ("1m", "5m", "15m", "1h", "4h", "24h")
]
EXPECTED_PRE_006_INDEXES = {
    "events_pkey", "events_slug_key", "ix_events_btc_average_reaction",
    "ix_events_category", "ix_events_eth_average_reaction", "ix_events_primary_asset",
    "ix_events_published_at", "ix_events_related_assets_gin",
    "ix_events_search_vector_gin", "ix_events_sol_average_reaction", "ix_events_source",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("postgresql+psycopg2://"):
        return "postgresql://" + value.removeprefix("postgresql+psycopg2://")
    if value.startswith("postgres://"):
        return "postgresql://" + value.removeprefix("postgres://")
    return value


def fetch_dicts(cursor: Any, sql: str) -> list[dict[str, Any]]:
    cursor.execute(sql)
    names = [item.name for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def check_ignored(path: Path) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", str(path)], cwd=ROOT, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"Backup target is not ignored by Git: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    check_ignored(output)
    if output.exists():
        raise RuntimeError(f"Refusing to reuse backup directory: {output}")

    release, release_manifest, release_stats = validate_manifest(args.manifest.resolve())
    release_manifest["_manifest_path"] = str(args.manifest.resolve())
    if release_manifest["expected_project_ref"] != EXPECTED_PROJECT_REF:
        raise RuntimeError("Release manifest project ref mismatch")
    if (release_stats["old_rows"], release_stats["new_rows"]) != (EXPECTED_ROWS, 1_195):
        raise RuntimeError("Release identity split mismatch")

    load_dotenv(ROOT / ".env")
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    parsed = urlparse(database_url)
    identity = f"{parsed.hostname or ''} {parsed.username or ''}"
    if EXPECTED_PROJECT_REF not in identity:
        raise RuntimeError("DATABASE_URL does not identify the expected production project")

    connection = psycopg2.connect(database_url, application_name="dz9a_readonly_backup")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_read_only')")
            if cursor.fetchone()[0] != "on":
                raise RuntimeError("Production audit transaction is not read-only")

            preflight = preflight_cursor(
                cursor, release, release_manifest, require_insert_schema=False
            )
            if preflight["mode"] != "ready_to_insert" or preflight["present_new_rows"] != 0:
                raise RuntimeError(f"Production identity/protected snapshot gate failed: {preflight}")

            cursor.execute(
                "SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug), "
                "min(published_at), max(published_at) FROM public.events"
            )
            total, unique_ids, unique_slugs, min_date, max_date = cursor.fetchone()
            counts = (int(total), int(unique_ids), int(unique_slugs))
            if counts != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS):
                raise RuntimeError(f"Production identity counts mismatch: {counts}")

            columns = fetch_dicts(cursor, """
                SELECT ordinal_position, column_name, data_type, udt_name, is_nullable,
                       column_default, is_generated, generation_expression
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='events'
                ORDER BY ordinal_position
            """)
            column_names = [item["column_name"] for item in columns]
            if not set(REACTION_COLUMNS + REACTION_QUALITY_COLUMNS) <= set(column_names):
                raise RuntimeError("Reaction V2 columns are incomplete")
            present_006 = sorted(set(METADATA_COLUMNS) & set(column_names))
            if present_006 or "search_document_v2" in column_names:
                raise RuntimeError(f"Migration 006 is already or partially applied: {present_006}")

            table_state = fetch_dicts(cursor, """
                SELECT c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced,
                       pg_get_userbyid(c.relowner) AS owner,
                       obj_description(c.oid, 'pg_class') AS comment
                FROM pg_class c WHERE c.oid='public.events'::regclass
            """)[0]
            policies = fetch_dicts(cursor, """
                SELECT policyname, permissive, roles, cmd, qual, with_check
                FROM pg_policies WHERE schemaname='public' AND tablename='events'
                ORDER BY policyname
            """)
            grants = fetch_dicts(cursor, """
                SELECT grantee, privilege_type, is_grantable
                FROM information_schema.role_table_grants
                WHERE table_schema='public' AND table_name='events'
                ORDER BY grantee, privilege_type
            """)
            client_grants = [
                grant for grant in grants
                if grant["grantee"] in {"anon", "authenticated", "PUBLIC"}
            ]
            if not table_state["rls_enabled"] or policies or client_grants:
                raise RuntimeError(
                    "RLS/policy/grant state mismatch: expected RLS on, no policies, no client grants"
                )

            constraints = fetch_dicts(cursor, """
                SELECT conname AS name, contype AS type, pg_get_constraintdef(oid, true) AS definition
                FROM pg_constraint WHERE conrelid='public.events'::regclass ORDER BY conname
            """)
            indexes = fetch_dicts(cursor, """
                SELECT indexname AS name, indexdef AS definition
                FROM pg_indexes WHERE schemaname='public' AND tablename='events'
                ORDER BY indexname
            """)
            index_names = {item["name"] for item in indexes}
            if not EXPECTED_PRE_006_INDEXES <= index_names:
                raise RuntimeError(
                    f"Expected production indexes missing: {sorted(EXPECTED_PRE_006_INDEXES-index_names)}"
                )
            comments = fetch_dicts(cursor, """
                SELECT a.attname AS column_name, col_description(a.attrelid, a.attnum) AS comment
                FROM pg_attribute a
                WHERE a.attrelid='public.events'::regclass AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY a.attnum
            """)
            migration_state = {
                "metadata_006_columns_present": present_006,
                "search_document_v2_present": "search_document_v2" in column_names,
                "migration_006_applied": False,
                "migration_008_table_present": None,
                "alembic_versions": [],
            }
            cursor.execute("SELECT to_regclass('public.distributed_rate_limits')")
            migration_state["migration_008_table_present"] = cursor.fetchone()[0] is not None
            cursor.execute("SELECT to_regclass('public.alembic_version')")
            if cursor.fetchone()[0] is not None:
                cursor.execute("SELECT version_num FROM public.alembic_version ORDER BY version_num")
                migration_state["alembic_versions"] = [row[0] for row in cursor.fetchall()]

            cursor.execute("SELECT * FROM public.events ORDER BY event_id")
            rows = cursor.fetchall()
            live_columns = [item.name for item in cursor.description]
        connection.rollback()
    finally:
        connection.close()

    live = pd.DataFrame(rows, columns=live_columns)
    reaction_coverage = {
        column: {"non_null": int(live[column].notna().sum()), "null": int(live[column].isna().sum())}
        for column in REACTION_COLUMNS + REACTION_QUALITY_COLUMNS
    }
    schema = {
        "schema": "public", "table": "events", "table_state": table_state,
        "columns": columns, "constraints": constraints, "indexes": indexes,
        "policies": policies, "grants": grants, "column_comments": comments,
    }
    restore_text = """# Restore instructions

This backup is a pre-migration snapshot of public.events. Restore only during an approved incident.

1. Verify the target Supabase project and take a fresh backup.
2. Recreate public.events from schema_snapshot.json in a transaction, including constraints and indexes.
3. Load events.parquet with a reviewed restore program that maps the manifest exact column order. events.csv is the portable fallback.
4. Restore RLS, policies, and grants exactly as recorded in schema_snapshot.json.
5. Validate the manifest hashes, row/ID/slug counts, min/max dates, and Reaction V2 coverage before commit.
6. Roll back the transaction on any mismatch.
"""

    output.mkdir(parents=True)
    data_parquet = output / "events.parquet"
    data_csv = output / "events.csv"
    schema_path = output / "schema_snapshot.json"
    migration_path = output / "migration_state.json"
    restore_path = output / "RESTORE_INSTRUCTIONS.md"
    live.to_parquet(data_parquet, index=False)
    live.to_csv(data_csv, index=False, encoding="utf-8", na_rep="")
    schema_path.write_text(json.dumps(schema, indent=2, default=str) + "\n", encoding="utf-8")
    migration_path.write_text(json.dumps(migration_state, indent=2, default=str) + "\n", encoding="utf-8")
    restore_path.write_text(restore_text, encoding="utf-8")

    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in (data_parquet, data_csv, schema_path, migration_path, restore_path)
    }
    backup_sha = hashlib.sha256(
        "\n".join(f"{name}|{item['sha256']}" for name, item in sorted(files.items())).encode()
    ).hexdigest()
    manifest = {
        "project_ref": EXPECTED_PROJECT_REF,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(live), "unique_event_ids": int(live.event_id.nunique()),
        "unique_slugs": int(live.slug.nunique()), "columns": live_columns,
        "column_count": len(live_columns), "min_published_at": min_date,
        "max_published_at": max_date, "reaction_v2_coverage": reaction_coverage,
        "backup_sha256": backup_sha, "files": files,
        "restore_instructions": restore_text.splitlines()[2:],
        "stage1": {"release_preflight": preflight, "rls": table_state["rls_enabled"],
                   "policies": len(policies), "client_grants": len(client_grants),
                   "migration_006_applied": False},
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")

    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in stored["files"].items():
        path = output / name
        if not path.is_file() or path.stat().st_size <= 0 or sha256(path) != expected["sha256"]:
            raise RuntimeError(f"Backup restore-read hash verification failed: {name}")
    restored = pd.read_parquet(data_parquet)
    restored_csv = pd.read_csv(data_csv, low_memory=False)
    if (len(restored), restored.event_id.nunique(), restored.slug.nunique()) != (
        EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS
    ):
        raise RuntimeError("Parquet restore-read identity verification failed")
    if len(restored_csv) != EXPECTED_ROWS or list(restored.columns) != live_columns:
        raise RuntimeError("CSV/schema restore-read verification failed")
    if stored["backup_sha256"] != backup_sha or len(stored["columns"]) != len(columns):
        raise RuntimeError("Manifest/schema restore-read verification failed")

    print(json.dumps({
        "status": "BACKUP_VERIFIED", "project_ref": EXPECTED_PROJECT_REF,
        "backup_path": str(output), "rows": len(restored),
        "unique_event_ids": int(restored.event_id.nunique()),
        "unique_slugs": int(restored.slug.nunique()), "columns": len(live_columns),
        "backup_sha256": backup_sha, "migration_006_sha256": sha256(MIGRATION),
        "min_published_at": str(min_date), "max_published_at": str(max_date),
        "new_ids_already_present": preflight["present_new_rows"],
        "protected_mismatches": preflight["protected_old_mismatches"],
        "rls_enabled": table_state["rls_enabled"], "policies": len(policies),
        "client_grants": len(client_grants), "migration_006_applied": False,
        "git_ignored": True, "restore_read_verified": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
