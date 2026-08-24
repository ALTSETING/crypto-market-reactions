"""Read-only post-006 production validation against the verified DZ9A backup."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import psycopg2
from dotenv import load_dotenv

from scripts.database.release_backfill import values_equal
from scripts.database.release_contract import METADATA_COLUMNS, PROTECTED_REACTION_COLUMNS

ROOT = Path(__file__).resolve().parents[2]
PROJECT_REF = "ickflwksigaotygtdyko"
INDEXES_006 = {
    "ix_events_story_id",
    "ix_events_record_type",
    "ix_events_quality_public",
    "ix_events_search_document_v2_gin",
}


def normalize_parquet_json(value):
    """Undo Arrow struct union padding for sparse JSONB objects."""
    if isinstance(value, dict):
        return {
            key: normalize_parquet_json(item)
            for key, item in value.items()
            if item is not None
        }
    return value


def fetch_dicts(cursor, sql: str):
    cursor.execute(sql)
    names = [item.name for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--expected-total", type=int, default=7_878)
    args = parser.parse_args()
    backup = args.backup.resolve()
    before = pd.read_parquet(backup / "events.parquet").sort_values("event_id").reset_index(drop=True)
    before_schema = json.loads((backup / "schema_snapshot.json").read_text(encoding="utf-8"))

    load_dotenv(ROOT / ".env")
    database_url = os.environ["DATABASE_URL"]
    parsed = urlparse(database_url.replace("postgresql+psycopg2://", "postgresql://", 1))
    if PROJECT_REF not in f"{parsed.hostname or ''} {parsed.username or ''}":
        raise RuntimeError("Production project ref mismatch")

    connection = psycopg2.connect(database_url, application_name="dz9a_post006_validation")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_read_only')")
            if cursor.fetchone()[0] != "on":
                raise RuntimeError("Validation transaction is not read-only")
            cursor.execute(
                "SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug) FROM public.events"
            )
            counts = tuple(map(int, cursor.fetchone()))

            cursor.execute("""
                SELECT column_name, is_generated, generation_expression
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='events'
                ORDER BY ordinal_position
            """)
            column_rows = cursor.fetchall()
            columns = {row[0]: {"is_generated": row[1], "expression": row[2]} for row in column_rows}
            reaction_types = fetch_dicts(cursor, """
                SELECT column_name, data_type, udt_name, numeric_precision
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='events'
                  AND column_name IN ('btc_1m', 'eth_1m', 'sol_1m')
                ORDER BY column_name
            """)
            missing_metadata = sorted(set(METADATA_COLUMNS) - set(columns))
            search = columns.get("search_document_v2")

            indexes = fetch_dicts(cursor, """
                SELECT i.relname AS name, x.indisvalid AS valid, x.indisready AS ready,
                       pg_get_indexdef(i.oid) AS definition
                FROM pg_index x
                JOIN pg_class i ON i.oid=x.indexrelid
                WHERE x.indrelid='public.events'::regclass
                ORDER BY i.relname
            """)
            index_map = {item["name"]: item for item in indexes}
            bad_indexes = sorted(
                name for name in INDEXES_006
                if name not in index_map or not index_map[name]["valid"] or not index_map[name]["ready"]
            )

            cursor.execute(
                "SELECT count(*) FROM public.events "
                "WHERE search_document_v2 @@ websearch_to_tsquery('english', 'ethereum ETF')"
            )
            search_matches = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM public.events WHERE search_document_v2 IS NULL")
            null_search = int(cursor.fetchone()[0])

            cursor.execute("SELECT relrowsecurity FROM pg_class WHERE oid='public.events'::regclass")
            rls_enabled = bool(cursor.fetchone()[0])
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
                item for item in grants if item["grantee"] in {"anon", "authenticated", "PUBLIC"}
            ]

            quoted = ",".join(f'"{name}"' for name in before.columns)
            cursor.execute(
                f"SELECT {quoted} FROM public.events "
                "WHERE event_id = ANY(%s) ORDER BY event_id",
                (before.event_id.tolist(),),
            )
            after = pd.DataFrame(cursor.fetchall(), columns=before.columns)
            cursor.execute(
                "SELECT to_regclass('public.api_rate_limit_buckets'), "
                "to_regprocedure('public.consume_events_rate_limit(text,integer,integer)')"
            )
            migration_objects = cursor.fetchone()
            migration_008_present = any(item is not None for item in migration_objects)
        connection.rollback()
    finally:
        connection.close()

    mismatches = {}
    for column in before.columns:
        count = sum(
            not values_equal(
                normalize_parquet_json(left)
                if column.endswith("_reaction_missing_reason")
                else left,
                right,
            )
            for left, right in zip(before[column], after[column])
        )
        if count:
            mismatches[column] = count
    reaction_mismatches = sum(mismatches.get(column, 0) for column in PROTECTED_REACTION_COLUMNS)

    before_grants = before_schema["grants"]
    checks = {
        "counts_expected": counts == (
            args.expected_total, args.expected_total, args.expected_total
        ),
        "metadata_22_present": not missing_metadata and len(METADATA_COLUMNS) == 22,
        "generated_search_present": bool(search and search["is_generated"] == "ALWAYS"),
        "indexes_4_valid": not bad_indexes,
        "search_operational": null_search == 0 and search_matches > 0,
        "old_58_columns_unchanged": not mismatches,
        "reaction_v2_mismatches_zero": reaction_mismatches == 0,
        "rls_enabled": rls_enabled,
        "policies_not_wider": policies == before_schema["policies"],
        "grants_not_wider": grants == before_grants and not client_grants,
        "migration_008_absent": not migration_008_present,
    }
    result = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "project_ref": PROJECT_REF,
        "checks": checks,
        "rows": counts[0],
        "unique_event_ids": counts[1],
        "unique_slugs": counts[2],
        "metadata_columns_present": [name for name in METADATA_COLUMNS if name in columns],
        "metadata_columns_missing": missing_metadata,
        "generated_search_column": "search_document_v2",
        "new_indexes": sorted(INDEXES_006),
        "bad_indexes": bad_indexes,
        "search_matches_ethereum_etf": search_matches,
        "old_column_mismatches": mismatches,
        "reaction_v2_mismatches": reaction_mismatches,
        "reaction_column_types": reaction_types,
        "rls_enabled": rls_enabled,
        "policies_before_after": [len(before_schema["policies"]), len(policies)],
        "grants_before_after": [len(before_grants), len(grants)],
        "client_grants": client_grants,
        "migration_008_present": migration_008_present,
        "production_updated_by_validation": False,
    }
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
