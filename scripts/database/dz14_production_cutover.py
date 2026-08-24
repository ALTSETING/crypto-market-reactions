"""Fail-closed backup and production cutover for DZ14 migration 009.

Only the reviewed migration and metadata backfill are applied. Existing event
identity, Reaction V2 fields, legacy record_type/source_type, and every other
pre-existing column are hashed before the transaction and verified again before
and after commit. The exact event-level V2 classification manifest is a gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

from scripts.database.import_events import ROOT, normalize_database_url
from scripts.database.release_backfill import preflight_cursor
from scripts.database.release_contract import (
    DEFAULT_RELEASE_MANIFEST,
    PROTECTED_REACTION_COLUMNS,
    REACTION_COLUMNS,
    validate_manifest,
)
from scripts.quality.build_source_classification_v2 import mapping_sha256


EXPECTED_PROJECT_REF = "ickflwksigaotygtdyko"
EXPECTED_ROWS = 9_073
MIGRATION = ROOT / "database/migrations/009_source_classification_reaction_v2.sql"
BACKFILL = ROOT / "database/migrations/009_source_classification_backfill.sql"
ROLLBACK = ROOT / "database/migrations/009_source_classification_rollback.sql"
CLASSIFICATION = ROOT / "reports/SOURCE_CLASSIFICATION_V2_MANIFEST.csv"
CLASSIFICATION_SUMMARY = ROOT / "reports/SOURCE_CLASSIFICATION_V2_MANIFEST.json"
REPORT = ROOT / "reports/DZ14_PRODUCTION_CUTOVER.json"
EXPECTED_SOURCE_COUNTS = {
    "news_media": 8_046,
    "primary_document": 736,
    "official_announcement": 291,
    "unknown": 0,
}
EXPECTED_DOCUMENT_COUNTS = {
    "news_article": 8_046,
    "regulatory_filing": 496,
    "protocol_announcement": 291,
    "other": 240,
}
EXPECTED_CONFIDENCE_COUNTS = {"high": 8_966, "medium": 107}
NEW_COLUMNS = {
    "source_class_v2",
    "document_class_v2",
    "source_class_confidence_v2",
    "source_classification_version",
}
NEW_INDEX = "ix_events_source_class_v2_published_at"
NEW_CONSTRAINTS = {
    "events_source_class_v2_check",
    "events_document_class_v2_check",
    "events_source_class_confidence_v2_check",
    "events_source_classification_version_check",
}
CONFIRMATION = f"APPLY-MIGRATION-009-METADATA-ONLY-{EXPECTED_PROJECT_REF}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (float, np.floating)) and math.isnan(float(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return [canonical(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, np.generic):
        return canonical(value.item())
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, memoryview):
        return value.tobytes().hex()
    if isinstance(value, bytes):
        return value.hex()
    return value


def frame_hash(frame: pd.DataFrame, columns: list[str]) -> str:
    digest = hashlib.sha256()
    ordered = frame[columns].sort_values("event_id").reset_index(drop=True)
    for record in ordered.to_dict("records"):
        payload = {column: canonical(record[column]) for column in columns}
        digest.update(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
            + b"\n"
        )
    return digest.hexdigest()


def fetch_dicts(cursor: Any, query: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    cursor.execute(query, params)
    names = [item.name for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def table_columns(cursor: Any) -> list[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='events'
        ORDER BY ordinal_position
        """
    )
    return [row[0] for row in cursor.fetchall()]


def fetch_frame(cursor: Any, columns: list[str]) -> pd.DataFrame:
    selected = sql.SQL(",").join(sql.Identifier(column) for column in columns)
    cursor.execute(
        sql.SQL("SELECT {} FROM public.events ORDER BY event_id").format(selected)
    )
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def schema_snapshot(cursor: Any) -> dict[str, Any]:
    columns = fetch_dicts(
        cursor,
        """
        SELECT ordinal_position, column_name, data_type, udt_name, is_nullable,
               column_default, is_generated, generation_expression
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='events'
        ORDER BY ordinal_position
        """,
    )
    table_state = fetch_dicts(
        cursor,
        """
        SELECT c.relrowsecurity AS rls_enabled,
               c.relforcerowsecurity AS rls_forced,
               c.relacl::text AS raw_acl,
               pg_get_userbyid(c.relowner) AS owner,
               obj_description(c.oid, 'pg_class') AS comment
        FROM pg_class c WHERE c.oid='public.events'::regclass
        """,
    )[0]
    constraints = fetch_dicts(
        cursor,
        """
        SELECT conname AS name, contype AS type, convalidated AS validated,
               pg_get_constraintdef(oid, true) AS definition
        FROM pg_constraint
        WHERE conrelid='public.events'::regclass
        ORDER BY conname
        """,
    )
    indexes = fetch_dicts(
        cursor,
        """
        SELECT x.indexname AS name, x.indexdef AS definition,
               i.indisvalid AS valid, i.indisready AS ready, i.indislive AS live
        FROM pg_indexes x
        JOIN pg_class ic ON ic.relname=x.indexname
        JOIN pg_namespace n ON n.oid=ic.relnamespace AND n.nspname=x.schemaname
        JOIN pg_index i ON i.indexrelid=ic.oid
        WHERE x.schemaname='public' AND x.tablename='events'
        ORDER BY x.indexname
        """,
    )
    policies = fetch_dicts(
        cursor,
        """
        SELECT policyname, permissive, roles, cmd, qual, with_check
        FROM pg_policies
        WHERE schemaname='public' AND tablename='events'
        ORDER BY policyname
        """,
    )
    grants = fetch_dicts(
        cursor,
        """
        SELECT grantee, privilege_type, is_grantable
        FROM information_schema.role_table_grants
        WHERE table_schema='public' AND table_name='events'
        ORDER BY grantee, privilege_type
        """,
    )
    comments = fetch_dicts(
        cursor,
        """
        SELECT a.attname AS column_name,
               col_description(a.attrelid, a.attnum) AS comment
        FROM pg_attribute a
        WHERE a.attrelid='public.events'::regclass
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
    )
    return {
        "columns": columns,
        "table_state": table_state,
        "constraints": constraints,
        "indexes": indexes,
        "policies": policies,
        "grants": grants,
        "column_comments": comments,
    }


def security_snapshot(schema: dict[str, Any]) -> dict[str, Any]:
    client = {"anon", "authenticated", "PUBLIC"}
    client_grants = [row for row in schema["grants"] if row["grantee"] in client]
    return {
        "table_state": schema["table_state"],
        "policies": schema["policies"],
        "grants": schema["grants"],
        "client_grants": client_grants,
    }


def migration_state(schema: dict[str, Any]) -> dict[str, Any]:
    names = {row["column_name"] for row in schema["columns"]}
    indexes = {row["name"] for row in schema["indexes"]}
    constraints = {row["name"] for row in schema["constraints"]}
    return {
        "new_columns_present": sorted(NEW_COLUMNS & names),
        "source_filter_index_present": NEW_INDEX in indexes,
        "dz14_constraints_present": sorted(NEW_CONSTRAINTS & constraints),
    }


def load_target() -> str:
    load_dotenv(ROOT / ".env")
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    parsed = urlparse(database_url)
    identity = f"{parsed.hostname or ''} {parsed.username or ''}"
    if EXPECTED_PROJECT_REF not in identity:
        raise RuntimeError("Configured database does not identify the confirmed production project")
    return database_url


def check_ignored(path: Path) -> None:
    path = path.resolve()
    git_root = ROOT.resolve()
    try:
        relative = path.relative_to(git_root)
    except ValueError:
        probe = path if path.is_dir() else path.parent
        target = "." if path.is_dir() else path.name
        result = subprocess.run(
            ["git", "-C", str(probe), "check-ignore", "--quiet", "--", target],
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Backup/report target is not ignored by Git: {path}")
        return
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", str(relative)],
        cwd=git_root,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Backup/report target is not ignored by Git: {path}")


def exact_counts(cursor: Any) -> tuple[int, int, int, int]:
    cursor.execute(
        """
        SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug),
               count(*) FILTER (
                   WHERE reaction_methodology='reaction_v2_next_full_minute_open_to_open'
               )
        FROM public.events
        """
    )
    return tuple(map(int, cursor.fetchone()))


def grouped_counts(cursor: Any, column: str) -> dict[str, int]:
    cursor.execute(
        sql.SQL("SELECT {}, count(*) FROM public.events GROUP BY {} ORDER BY {}").format(
            sql.Identifier(column), sql.Identifier(column), sql.Identifier(column)
        )
    )
    return {str(value): int(count) for value, count in cursor.fetchall() if value is not None}


def protected_column_sets(columns: list[str]) -> tuple[list[str], list[str]]:
    reaction = ["event_id", "reaction_methodology", "reaction_value_unit"]
    reaction.extend(column for column in REACTION_COLUMNS if column in columns)
    reaction.extend(
        column
        for column in columns
        if column.endswith("_average_reaction") and column not in reaction
    )
    missing = sorted(
        {"reaction_methodology", "reaction_value_unit", *PROTECTED_REACTION_COLUMNS}
        - set(reaction)
    )
    if missing:
        raise RuntimeError(f"Protected Reaction V2 columns are missing: {missing}")
    return reaction, list(columns)


def sql_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    begin = [index for index, line in enumerate(lines) if line.strip().upper() == "BEGIN;"]
    commit = [index for index, line in enumerate(lines) if line.strip().upper() == "COMMIT;"]
    if len(begin) != 1 or len(commit) != 1 or begin[0] >= commit[0]:
        raise RuntimeError(f"Unexpected transaction envelope in {path.name}")
    return "\n".join(
        line for index, line in enumerate(lines) if index not in {begin[0], commit[0]}
    )


def verify_live_baseline(backup: Path) -> dict[str, Any]:
    """Read-only exact comparison with the preserved pre-009 production backup."""
    backup = backup.resolve()
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("project_ref") != EXPECTED_PROJECT_REF:
        raise RuntimeError("Preserved backup project ref mismatch")
    for name, expected in manifest["files"].items():
        path = backup / name
        if not path.is_file() or file_sha256(path) != expected["sha256"]:
            raise RuntimeError(f"Preserved backup file hash mismatch: {name}")
    aggregate = hashlib.sha256(
        "\n".join(
            f"{name}|{item['sha256']}"
            for name, item in sorted(manifest["files"].items())
        ).encode()
    ).hexdigest()
    if aggregate != manifest["backup_sha256"]:
        raise RuntimeError("Preserved backup aggregate SHA-256 mismatch")
    check_ignored(backup)

    database_url = load_target()
    connection = psycopg2.connect(database_url, application_name="dz14_readonly_live_baseline")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_read_only')")
            if cursor.fetchone()[0] != "on":
                raise RuntimeError("Live baseline transaction is not read-only")
            counts = exact_counts(cursor)
            schema = schema_snapshot(cursor)
            columns = table_columns(cursor)
            if columns != manifest["columns"]:
                raise RuntimeError("Live 81-column baseline schema differs from backup")
            live = fetch_frame(cursor, columns)
            security = security_snapshot(schema)
            state = migration_state(schema)
            cursor.execute(
                "SELECT record_type,source_type,count(*) FROM public.events "
                "GROUP BY record_type,source_type ORDER BY record_type,source_type NULLS FIRST"
            )
            legacy_counts = [list(row) for row in cursor.fetchall()]
        connection.rollback()
    finally:
        connection.close()

    if counts != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS):
        raise RuntimeError(f"Live identity/Reaction V2 count mismatch: {counts}")
    if state != manifest["migration_state"]:
        raise RuntimeError("Live migration state differs from preserved backup")
    if security != manifest["schema_security"]:
        raise RuntimeError("Live RLS, policies, grants, or ACL differ from preserved backup")
    checks = {
        "identity_sha256": frame_hash(live, ["event_id", "slug", "source_url"])
        == manifest["hashes"]["identity_sha256"],
        "protected_reaction_v2_sha256": frame_hash(live, manifest["reaction_columns"])
        == manifest["hashes"]["protected_reaction_v2_sha256"],
        "legacy_source_type_sha256": frame_hash(live, ["event_id", "source_type"])
        == manifest["hashes"]["source_type_snapshot_sha256"],
        "all_81_columns_sha256": frame_hash(live, columns)
        == manifest["hashes"]["full_table_content_sha256"],
    }
    if not all(checks.values()):
        raise RuntimeError(f"Live content differs from preserved backup: {checks}")
    expected_legacy = [["news_article", "publisher", 1_195], ["other", None, 7_878]]
    if legacy_counts != expected_legacy:
        raise RuntimeError(f"Legacy metadata baseline mismatch: {legacy_counts}")
    result = {
        "status": "LIVE_BASELINE_EXACT",
        "project_ref": EXPECTED_PROJECT_REF,
        "backup_path": str(backup),
        "backup_sha256": aggregate,
        "rows_unique_ids_unique_slugs": list(counts[:3]),
        "reaction_v2_rows": counts[3],
        "column_count": len(columns),
        "legacy_counts": legacy_counts,
        "checks": checks,
        "rls_enabled": security["table_state"]["rls_enabled"],
        "policies": len(security["policies"]),
        "client_grants": len(security["client_grants"]),
        "transaction_read_only": True,
    }
    print(json.dumps(result, indent=2))
    return result


def create_backup(output: Path) -> dict[str, Any]:
    output = output.resolve()
    check_ignored(output)
    if output.exists():
        raise RuntimeError(f"Refusing to reuse backup directory: {output}")
    release, release_manifest, _ = validate_manifest(DEFAULT_RELEASE_MANIFEST)
    release_manifest["_manifest_path"] = str(DEFAULT_RELEASE_MANIFEST.resolve())
    if release_manifest["expected_project_ref"] != EXPECTED_PROJECT_REF:
        raise RuntimeError("Release manifest project mismatch")

    database_url = load_target()
    connection = psycopg2.connect(database_url, application_name="dz14_readonly_backup")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_read_only')")
            if cursor.fetchone()[0] != "on":
                raise RuntimeError("Backup transaction is not read-only")
            preflight = preflight_cursor(cursor, release, release_manifest)
            counts = exact_counts(cursor)
            schema = schema_snapshot(cursor)
            state = migration_state(schema)
            security = security_snapshot(schema)
            columns = [row["column_name"] for row in schema["columns"]]
            live = fetch_frame(cursor, columns)
            cursor.execute("SELECT min(published_at), max(published_at) FROM public.events")
            min_date, max_date = cursor.fetchone()
        connection.rollback()
    finally:
        connection.close()

    if counts != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS):
        raise RuntimeError(f"Production identity/Reaction V2 count mismatch: {counts}")
    if preflight["mode"] != "already_applied":
        raise RuntimeError(f"Release identity gate failed: {preflight}")
    if len(columns) != 81:
        raise RuntimeError(f"Expected exact 81-column production baseline, found {len(columns)}")
    if state != {
        "new_columns_present": [],
        "source_filter_index_present": False,
        "dz14_constraints_present": [],
    }:
        raise RuntimeError(f"Migration 009 is already or partially applied: {state}")
    if (
        not security["table_state"]["rls_enabled"]
        or security["policies"]
        or security["client_grants"]
    ):
        raise RuntimeError("Production RLS/policy/client-grant baseline mismatch")

    reaction_columns, protected_existing = protected_column_sets(columns)
    hashes = {
        "identity_sha256": frame_hash(live, ["event_id", "slug", "source_url"]),
        "protected_reaction_v2_sha256": frame_hash(live, reaction_columns),
        "all_preexisting_columns_sha256": frame_hash(live, protected_existing),
        "legacy_record_source_sha256": frame_hash(
            live, ["event_id", "record_type", "source_type"]
        ),
        "full_table_content_sha256": frame_hash(live, columns),
    }
    reaction_coverage = {
        column: {
            "non_null": int(live[column].notna().sum()),
            "null": int(live[column].isna().sum()),
        }
        for column in reaction_columns
        if column != "event_id"
    }

    output.mkdir(parents=True)
    paths = {
        "events.parquet": output / "events.parquet",
        "events.csv": output / "events.csv",
        "schema_snapshot.json": output / "schema_snapshot.json",
        "migration_state.json": output / "migration_state.json",
        "RESTORE_INSTRUCTIONS.md": output / "RESTORE_INSTRUCTIONS.md",
    }
    live.to_parquet(paths["events.parquet"], index=False)
    live.to_csv(paths["events.csv"], index=False, encoding="utf-8", na_rep="")
    paths["schema_snapshot.json"].write_text(
        json.dumps(schema, indent=2, default=str) + "\n", encoding="utf-8"
    )
    paths["migration_state.json"].write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )
    paths["RESTORE_INSTRUCTIONS.md"].write_text(
        """# DZ14 production restore instructions

Restore only during an approved incident. Verify the exact project ref and all
file hashes first. In one transaction, lock public.events, verify identity and
protected Reaction V2 hashes, run the reviewed schema-only migration 009
rollback, then validate all 81 pre-existing columns plus identity, reactions,
legacy record_type/source_type, RLS, policies, and grants before commit. The
full Parquet/CSV copies are last-resort table restore inputs.
""",
        encoding="utf-8",
    )
    files = {
        name: {"bytes": path.stat().st_size, "sha256": file_sha256(path)}
        for name, path in paths.items()
    }
    aggregate = hashlib.sha256(
        "\n".join(f"{name}|{item['sha256']}" for name, item in sorted(files.items())).encode()
    ).hexdigest()
    manifest = {
        "version": "DZ14_PRODUCTION_BACKUP_V2",
        "project_ref": EXPECTED_PROJECT_REF,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "rows": counts[0],
        "unique_event_ids": counts[1],
        "unique_slugs": counts[2],
        "reaction_v2_rows": counts[3],
        "columns": columns,
        "column_count": len(columns),
        "reaction_columns": reaction_columns,
        "protected_existing_columns": protected_existing,
        "min_published_at": str(min_date),
        "max_published_at": str(max_date),
        "reaction_v2_coverage": reaction_coverage,
        "hashes": hashes,
        "migration_sql_sha256": {
            MIGRATION.name: file_sha256(MIGRATION),
            BACKFILL.name: file_sha256(BACKFILL),
            ROLLBACK.name: file_sha256(ROLLBACK),
        },
        "classification_manifest": {
            "csv_sha256": file_sha256(CLASSIFICATION),
            "summary_sha256": file_sha256(CLASSIFICATION_SUMMARY),
            "event_level_mapping_sha256": json.loads(
                CLASSIFICATION_SUMMARY.read_text(encoding="utf-8")
            )["event_level_mapping_sha256"],
        },
        "schema_security": security,
        "migration_state": state,
        "release_preflight": preflight,
        "files": files,
        "backup_sha256": aggregate,
        "git_ignored": True,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )

    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in stored["files"].items():
        path = output / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"Backup file is missing or empty: {name}")
        if file_sha256(path) != expected["sha256"]:
            raise RuntimeError(f"Backup restore-read hash mismatch: {name}")
    restored = pd.read_parquet(paths["events.parquet"])
    restored_csv = pd.read_csv(paths["events.csv"], low_memory=False)
    if (
        len(restored),
        restored["event_id"].nunique(),
        restored["slug"].nunique(),
    ) != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS):
        raise RuntimeError("Parquet restore-read identity verification failed")
    if len(restored_csv) != EXPECTED_ROWS or list(restored.columns) != columns:
        raise RuntimeError("CSV/schema restore-read verification failed")
    check_ignored(output)

    result = {
        "status": "BACKUP_VERIFIED",
        "project_ref": EXPECTED_PROJECT_REF,
        "backup_path": str(output),
        "rows_unique_ids_unique_slugs": list(counts[:3]),
        "reaction_v2_rows": counts[3],
        "column_count": len(columns),
        "backup_sha256": aggregate,
        "identity_sha256": hashes["identity_sha256"],
        "protected_reaction_v2_sha256": hashes["protected_reaction_v2_sha256"],
        "all_preexisting_columns_sha256": hashes["all_preexisting_columns_sha256"],
        "event_level_mapping_sha256": manifest["classification_manifest"][
            "event_level_mapping_sha256"
        ],
        "migration_sql_sha256": manifest["migration_sql_sha256"],
        "rls_enabled": security["table_state"]["rls_enabled"],
        "policies": len(security["policies"]),
        "client_grants": len(security["client_grants"]),
        "restore_read_verified": True,
        "git_ignored": True,
    }
    print(json.dumps(result, indent=2))
    return result


def verify_backup(
    backup: Path,
    classification_csv: Path = CLASSIFICATION,
    classification_summary: Path = CLASSIFICATION_SUMMARY,
) -> dict[str, Any]:
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "DZ14_PRODUCTION_BACKUP_V2":
        raise RuntimeError("Backup predates the corrected independent-column migration 009")
    if manifest["project_ref"] != EXPECTED_PROJECT_REF:
        raise RuntimeError("Backup project ref mismatch")
    if (manifest["rows"], manifest["unique_event_ids"], manifest["unique_slugs"]) != (
        EXPECTED_ROWS,
        EXPECTED_ROWS,
        EXPECTED_ROWS,
    ):
        raise RuntimeError("Backup identity mismatch")
    for name, expected in manifest["files"].items():
        path = backup / name
        if not path.is_file() or file_sha256(path) != expected["sha256"]:
            raise RuntimeError(f"Backup file hash mismatch: {name}")
    if manifest["migration_sql_sha256"] != {
        MIGRATION.name: file_sha256(MIGRATION),
        BACKFILL.name: file_sha256(BACKFILL),
        ROLLBACK.name: file_sha256(ROLLBACK),
    }:
        raise RuntimeError("Reviewed SQL hashes changed after backup")
    classification = manifest.get("classification_manifest", {})
    if classification != {
        "csv_sha256": file_sha256(classification_csv),
        "summary_sha256": file_sha256(classification_summary),
        "event_level_mapping_sha256": json.loads(
            classification_summary.read_text(encoding="utf-8")
        )["event_level_mapping_sha256"],
    }:
        raise RuntimeError("Reviewed event-level classification manifest changed after backup")
    check_ignored(backup)
    return manifest


def validate_cutover_state(
    cursor: Any,
    manifest: dict[str, Any],
    *,
    require_idempotency_hash: str | None = None,
) -> dict[str, Any]:
    counts = exact_counts(cursor)
    if counts != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS):
        raise RuntimeError(f"Post-migration identity/Reaction V2 counts mismatch: {counts}")
    columns = table_columns(cursor)
    if not NEW_COLUMNS <= set(columns):
        raise RuntimeError(f"Migration 009 columns are incomplete: {sorted(NEW_COLUMNS-set(columns))}")

    reaction_columns = manifest["reaction_columns"]
    protected_existing = manifest["protected_existing_columns"]
    protected_frame = fetch_frame(cursor, sorted(set(reaction_columns + protected_existing)))
    identity_hash = frame_hash(protected_frame, ["event_id", "slug", "source_url"])
    reaction_hash = frame_hash(protected_frame, reaction_columns)
    old_field_hash = frame_hash(protected_frame, protected_existing)
    legacy_hash = frame_hash(
        protected_frame, ["event_id", "record_type", "source_type"]
    )
    if identity_hash != manifest["hashes"]["identity_sha256"]:
        raise RuntimeError("Identity hash changed")
    if reaction_hash != manifest["hashes"]["protected_reaction_v2_sha256"]:
        raise RuntimeError("Protected Reaction V2 hash changed")
    if old_field_hash != manifest["hashes"]["all_preexisting_columns_sha256"]:
        raise RuntimeError("A protected pre-existing field changed")
    if legacy_hash != manifest["hashes"]["legacy_record_source_sha256"]:
        raise RuntimeError("Legacy record_type/source_type changed")

    source_counts = grouped_counts(cursor, "source_class_v2")
    document_counts = grouped_counts(cursor, "document_class_v2")
    confidence_counts = grouped_counts(cursor, "source_class_confidence_v2")
    if source_counts != {key: value for key, value in EXPECTED_SOURCE_COUNTS.items() if value}:
        raise RuntimeError(f"Source counts mismatch: {source_counts}")
    if document_counts != EXPECTED_DOCUMENT_COUNTS:
        raise RuntimeError(f"Document counts mismatch: {document_counts}")
    if confidence_counts != EXPECTED_CONFIDENCE_COUNTS:
        raise RuntimeError(f"Confidence counts mismatch: {confidence_counts}")
    cursor.execute(
        "SELECT count(*) FROM public.events "
        "WHERE source_classification_version='dz13-source-class-v2'"
    )
    version_rows = int(cursor.fetchone()[0])
    if version_rows != EXPECTED_ROWS:
        raise RuntimeError(f"Source classification version count mismatch: {version_rows}")

    schema = schema_snapshot(cursor)
    security = security_snapshot(schema)
    if security != manifest["schema_security"]:
        raise RuntimeError("RLS, policies, grants, or table ACL changed")
    constraint_map = {row["name"]: row for row in schema["constraints"]}
    if not NEW_CONSTRAINTS <= set(constraint_map):
        raise RuntimeError("Migration 009 constraints are incomplete")
    if not all(constraint_map[name]["validated"] for name in NEW_CONSTRAINTS):
        raise RuntimeError("A migration 009 constraint is not validated")
    index_map = {row["name"]: row for row in schema["indexes"]}
    expected_indexes = {row["name"] for row in json.loads(
        (Path(manifest["backup_path"]) / "schema_snapshot.json").read_text(encoding="utf-8")
    )["indexes"]} if "backup_path" in manifest else set()
    if NEW_INDEX not in index_map or not all(
        index_map[NEW_INDEX][flag] for flag in ("valid", "ready", "live")
    ):
        raise RuntimeError("Source filter index is not valid/ready/live")
    if expected_indexes and set(index_map) != expected_indexes | {NEW_INDEX}:
        raise RuntimeError("Unexpected production index set change")
    cursor.execute("SET LOCAL enable_seqscan=off")
    cursor.execute(
        "EXPLAIN SELECT event_id FROM public.events "
        "WHERE source_class_v2='primary_document' ORDER BY published_at DESC LIMIT 25"
    )
    plan = "\n".join(row[0] for row in cursor.fetchall())
    if NEW_INDEX not in plan:
        raise RuntimeError("Source filter query does not use the new index")

    metadata_frame = fetch_frame(
        cursor,
        [
            "event_id",
            "source_class_v2",
            "document_class_v2",
            "source_class_confidence_v2",
            "source_classification_version",
        ],
    )
    metadata_hash = frame_hash(metadata_frame, list(metadata_frame.columns))
    mapping_hash = mapping_sha256(metadata_frame)
    expected_mapping = pd.read_csv(
        Path(manifest.get("_classification_csv", str(CLASSIFICATION)))
    )
    expected_mapping = expected_mapping[list(metadata_frame.columns)].sort_values("event_id")
    live_mapping = metadata_frame.sort_values("event_id")
    if not expected_mapping.reset_index(drop=True).equals(live_mapping.reset_index(drop=True)):
        raise RuntimeError("Exact event-ID to classification mapping mismatch")
    if mapping_hash != manifest["classification_manifest"]["event_level_mapping_sha256"]:
        raise RuntimeError("Event-level classification mapping hash mismatch")
    if require_idempotency_hash is not None and metadata_hash != require_idempotency_hash:
        raise RuntimeError("Repeated metadata backfill is not idempotent")
    return {
        "rows_unique_ids_unique_slugs": list(counts[:3]),
        "reaction_v2_methodology_rows": counts[3],
        "source_classification_version_rows": version_rows,
        "source_counts": {**EXPECTED_SOURCE_COUNTS},
        "document_counts": document_counts,
        "confidence_counts": confidence_counts,
        "identity_sha256": identity_hash,
        "protected_reaction_v2_sha256": reaction_hash,
        "identity_mismatches": 0,
        "protected_reaction_mismatches": 0,
        "protected_old_field_mismatches": 0,
        "legacy_record_source_mismatches": 0,
        "event_level_mapping_mismatches": 0,
        "event_level_mapping_sha256": mapping_hash,
        "metadata_hash": metadata_hash,
        "rls_enabled": security["table_state"]["rls_enabled"],
        "rls_forced": security["table_state"]["rls_forced"],
        "policies": len(security["policies"]),
        "client_grants": len(security["client_grants"]),
        "constraints_valid": True,
        "source_filter_index_valid_ready_live_and_used": True,
    }


def restore_metadata_from_backup(
    backup: Path, manifest: dict[str, Any], database_url: str
) -> dict[str, Any]:
    """Drop only the four additive V2 fields after a failed post-commit gate."""
    connection = psycopg2.connect(
        database_url, application_name="dz14_exact_metadata_emergency_restore"
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='15s'")
            cursor.execute("SET LOCAL statement_timeout='10min'")
            cursor.execute("LOCK TABLE public.events IN SHARE ROW EXCLUSIVE MODE")
            current_columns = table_columns(cursor)
            current = fetch_frame(cursor, current_columns)
            if frame_hash(current, ["event_id", "slug", "source_url"]) != manifest["hashes"]["identity_sha256"]:
                raise RuntimeError("Emergency metadata restore refused: identity changed")
            if frame_hash(current, manifest["reaction_columns"]) != manifest["hashes"]["protected_reaction_v2_sha256"]:
                raise RuntimeError("Emergency metadata restore refused: reactions changed")
            if frame_hash(current, manifest["columns"]) != manifest["hashes"]["all_preexisting_columns_sha256"]:
                raise RuntimeError("Emergency metadata restore refused: an old field changed")
            cursor.execute(sql_body(ROLLBACK))

            restored_columns = table_columns(cursor)
            restored = fetch_frame(cursor, restored_columns)
            if restored_columns != manifest["columns"]:
                raise RuntimeError("Emergency metadata restore schema mismatch")
            if frame_hash(restored, manifest["columns"]) != manifest["hashes"]["full_table_content_sha256"]:
                raise RuntimeError("Emergency metadata restore content mismatch")
            restored_schema = schema_snapshot(cursor)
            if migration_state(restored_schema) != manifest["migration_state"]:
                raise RuntimeError("Emergency metadata restore migration-state mismatch")
            if security_snapshot(restored_schema) != manifest["schema_security"]:
                raise RuntimeError("Emergency metadata restore security mismatch")
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "status": "METADATA_ROLLED_BACK_TO_EXACT_BACKUP",
        "legacy_rows_restored": 0,
        "identity_mismatches": 0,
        "protected_reaction_mismatches": 0,
        "all_preexisting_column_mismatches": 0,
    }


def apply_cutover(backup: Path, confirmation: str) -> dict[str, Any]:
    if confirmation != CONFIRMATION:
        raise RuntimeError(f"Production write requires --confirm {CONFIRMATION}")
    backup = backup.resolve()
    manifest = verify_backup(backup)
    manifest["backup_path"] = str(backup)
    database_url = load_target()
    migration_body = sql_body(MIGRATION)
    backfill_body = sql_body(BACKFILL)

    connection = psycopg2.connect(database_url, application_name="dz14_migration_009_cutover")
    committed = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='15s'")
            cursor.execute("SET LOCAL statement_timeout='10min'")
            cursor.execute("LOCK TABLE public.events IN SHARE ROW EXCLUSIVE MODE")
            if exact_counts(cursor) != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS):
                raise RuntimeError("Final pre-write production count gate failed")
            before_schema = schema_snapshot(cursor)
            if migration_state(before_schema) != manifest["migration_state"]:
                raise RuntimeError("Migration state changed since the verified backup")
            if security_snapshot(before_schema) != manifest["schema_security"]:
                raise RuntimeError("Security state changed since the verified backup")
            before_columns = table_columns(cursor)
            before = fetch_frame(cursor, before_columns)
            reaction_columns = manifest["reaction_columns"]
            protected_existing = manifest["protected_existing_columns"]
            if frame_hash(before, ["event_id", "slug", "source_url"]) != manifest["hashes"]["identity_sha256"]:
                raise RuntimeError("Identity changed since the verified backup")
            if frame_hash(before, reaction_columns) != manifest["hashes"]["protected_reaction_v2_sha256"]:
                raise RuntimeError("Reaction V2 changed since the verified backup")
            if frame_hash(before, protected_existing) != manifest["hashes"]["all_preexisting_columns_sha256"]:
                raise RuntimeError("Protected old fields changed since the verified backup")

            cursor.execute(migration_body)
            cursor.execute(backfill_body)
            first = validate_cutover_state(cursor, manifest)
            cursor.execute(backfill_body)
            second = validate_cutover_state(
                cursor, manifest, require_idempotency_hash=first["metadata_hash"]
            )
            connection.commit()
            committed = True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    try:
        verify_connection = psycopg2.connect(
            database_url, application_name="dz14_postcommit_readonly_verification"
        )
        try:
            verify_connection.set_session(readonly=True, autocommit=False)
            with verify_connection.cursor() as cursor:
                postcommit = validate_cutover_state(
                    cursor, manifest, require_idempotency_hash=second["metadata_hash"]
                )
            verify_connection.rollback()
        finally:
            verify_connection.close()
    except Exception as exc:
        rollback = restore_metadata_from_backup(backup, manifest, database_url)
        failure = {
            "status": "MIGRATION_009_POSTCOMMIT_FAILED_AND_ROLLED_BACK",
            "project_ref": EXPECTED_PROJECT_REF,
            "backup_path": str(backup),
            "rollback": rollback,
            "error_type": type(exc).__name__,
            "github_updated": False,
            "vercel_updated": False,
        }
        check_ignored(REPORT)
        REPORT.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure, indent=2))
        raise RuntimeError("Post-commit verification failed; exact metadata backup restored") from exc

    result = {
        "status": "MIGRATION_009_SUCCESS",
        "project_ref": EXPECTED_PROJECT_REF,
        "backup_path": str(backup),
        "backup_sha256": manifest["backup_sha256"],
        "migration_sql_sha256": manifest["migration_sql_sha256"],
        "transaction_committed": committed,
        "first_backfill": first,
        "second_backfill_idempotent": first["metadata_hash"] == second["metadata_hash"],
        "postcommit_readonly_verification": postcommit,
        "candidate_methodology_applied": False,
        "reaction_values_overwritten": False,
        "github_updated": False,
        "vercel_updated": False,
    }
    check_ignored(REPORT)
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def verify_applied(
    backup: Path,
    classification_csv: Path = CLASSIFICATION,
    classification_summary: Path = CLASSIFICATION_SUMMARY,
) -> dict[str, Any]:
    """Run the full post-migration production gate through a read-only session."""
    backup = backup.resolve()
    manifest = verify_backup(backup, classification_csv, classification_summary)
    manifest["backup_path"] = str(backup)
    manifest["_classification_csv"] = str(classification_csv.resolve())
    database_url = load_target()
    connection = psycopg2.connect(
        database_url, application_name="dz14_applied_state_readonly_verification"
    )
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_read_only')")
            if cursor.fetchone()[0] != "on":
                raise RuntimeError("Applied-state verification is not read-only")
            verification = validate_cutover_state(cursor, manifest)
        connection.rollback()
    finally:
        connection.close()
    result = {
        "status": "MIGRATION_009_READBACK_PASS",
        "project_ref": EXPECTED_PROJECT_REF,
        "backup_path": str(backup),
        "backup_sha256": manifest["backup_sha256"],
        "transaction_read_only": True,
        "verification": verification,
        "production_updated": False,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify-live")
    verify_parser.add_argument("--backup", type=Path, required=True)
    applied_parser = subparsers.add_parser("verify-applied")
    applied_parser.add_argument("--backup", type=Path, required=True)
    applied_parser.add_argument("--classification-csv", type=Path, default=CLASSIFICATION)
    applied_parser.add_argument(
        "--classification-summary", type=Path, default=CLASSIFICATION_SUMMARY
    )
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--output-dir", type=Path, required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--backup", type=Path, required=True)
    apply_parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.command == "verify-live":
        verify_live_baseline(args.backup)
    elif args.command == "verify-applied":
        verify_applied(
            args.backup,
            args.classification_csv.resolve(),
            args.classification_summary.resolve(),
        )
    elif args.command == "backup":
        create_backup(args.output_dir)
    else:
        apply_cutover(args.backup, args.confirm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
