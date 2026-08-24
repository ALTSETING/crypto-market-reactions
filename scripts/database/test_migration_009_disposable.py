"""Production-shaped DZ14 rehearsal on a disposable PostgreSQL 16 database."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg2
from psycopg2 import sql

from scripts.database.dz14_production_cutover import canonical, file_sha256, frame_hash
from scripts.quality.build_source_classification_v2 import mapping_sha256


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "database/migrations/009_source_classification_reaction_v2.sql"
BACKFILL = ROOT / "database/migrations/009_source_classification_backfill.sql"
ROLLBACK = ROOT / "database/migrations/009_source_classification_rollback.sql"
BACKUP = ROOT / "data/website/backups/pre_source_classification_v2_20260824T081101Z"
CLASSIFICATION = ROOT / "reports/SOURCE_CLASSIFICATION_V2_MANIFEST.csv"
CLASSIFICATION_SUMMARY = ROOT / "reports/SOURCE_CLASSIFICATION_V2_MANIFEST.json"
OUTPUT = ROOT / "reports/DZ14_PRODUCTION_SHAPED_REHEARSAL.json"
EXPECTED_ROWS = 9_073
NEW_COLUMNS = [
    "source_class_v2",
    "document_class_v2",
    "source_class_confidence_v2",
    "source_classification_version",
]
TYPE_SQL = {
    "text": "text",
    "timestamptz": "timestamptz",
    "_text": "text[]",
    "float8": "double precision",
    "int4": "integer",
    "bool": "boolean",
    "jsonb": "jsonb",
    "tsvector": "tsvector",
}


def connect(url: str):
    return psycopg2.connect(url, application_name="dz14_production_shaped_rehearsal")


def execute_sql(connection: Any, path: Path) -> None:
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute(path.read_text(encoding="utf-8"))


def copy_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return r"\N"
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return r"\N"
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, list):
        return "{" + ",".join(str(item) for item in value) + "}"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, np.generic):
        return value.item()
    return value


def copy_buffer(frame: pd.DataFrame) -> io.StringIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in frame.itertuples(index=False, name=None):
        writer.writerow([copy_value(value) for value in row])
    buffer.seek(0)
    return buffer


def fetch_frame(cursor: Any, columns: list[str]) -> pd.DataFrame:
    selected = sql.SQL(",").join(sql.Identifier(column) for column in columns)
    cursor.execute(
        sql.SQL("SELECT {} FROM public.events ORDER BY event_id").format(selected)
    )
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def mismatch_count(before: pd.DataFrame, after: pd.DataFrame, columns: list[str]) -> int:
    left = before.sort_values("event_id").reset_index(drop=True)
    right = after.sort_values("event_id").reset_index(drop=True)
    if list(left.event_id) != list(right.event_id):
        return max(len(left), len(right))
    def equal(first: Any, second: Any) -> bool:
        first = canonical(first)
        second = canonical(second)
        if isinstance(first, (int, float)) and not isinstance(first, bool) and isinstance(
            second, (int, float)
        ) and not isinstance(second, bool):
            return math.isclose(float(first), float(second), rel_tol=1e-12, abs_tol=1e-12)
        return first == second

    mismatches = 0
    for column in columns:
        left_values = left[column].tolist()
        right_values = right[column].tolist()
        mismatches += sum(
            not equal(first, second)
            for first, second in zip(left_values, right_values, strict=True)
        )
    return mismatches


def fetch_security(cursor: Any) -> dict[str, Any]:
    cursor.execute(
        "SELECT relrowsecurity, relforcerowsecurity, relacl::text "
        "FROM pg_class WHERE oid='public.events'::regclass"
    )
    rls, forced, acl = cursor.fetchone()
    cursor.execute(
        "SELECT policyname, permissive, roles, cmd, qual, with_check "
        "FROM pg_policies WHERE schemaname='public' AND tablename='events' "
        "ORDER BY policyname"
    )
    policies = cursor.fetchall()
    cursor.execute(
        "SELECT grantee, privilege_type, is_grantable "
        "FROM information_schema.role_table_grants "
        "WHERE table_schema='public' AND table_name='events' "
        "ORDER BY grantee, privilege_type"
    )
    grants = cursor.fetchall()
    client_grants = [row for row in grants if row[0] in {"PUBLIC", "anon", "authenticated"}]
    return {
        "rls_enabled": bool(rls),
        "rls_forced": bool(forced),
        "raw_acl": acl,
        "policies": policies,
        "grants": grants,
        "client_grants": client_grants,
    }


def create_roles(cursor: Any) -> None:
    for role in ("anon", "authenticated", "service_role"):
        cursor.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=%s) "
            "THEN EXECUTE format('CREATE ROLE %%I NOLOGIN', %s); END IF; END $$",
            (role, role),
        )


def seed_exact_backup(connection: Any, backup: pd.DataFrame, schema: dict[str, Any]) -> None:
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        create_roles(cursor)
        definitions: list[sql.Composable] = []
        generated: set[str] = set()
        for column in schema["columns"]:
            column_type = TYPE_SQL[column["udt_name"]]
            definition = sql.SQL("{} {}").format(
                sql.Identifier(column["column_name"]), sql.SQL(column_type)
            )
            if column["is_generated"] == "ALWAYS":
                generated.add(column["column_name"])
                definition += sql.SQL(" GENERATED ALWAYS AS ({}) STORED").format(
                    sql.SQL(column["generation_expression"])
                )
            else:
                if column["column_default"] is not None:
                    definition += sql.SQL(" DEFAULT {}").format(
                        sql.SQL(column["column_default"])
                    )
                if column["is_nullable"] == "NO":
                    definition += sql.SQL(" NOT NULL")
            definitions.append(definition)
        cursor.execute(
            sql.SQL("CREATE TABLE public.events ({})").format(sql.SQL(",").join(definitions))
        )
        writable = [column for column in backup.columns if column not in generated]
        selected = sql.SQL(",").join(sql.Identifier(column) for column in writable)
        cursor.copy_expert(
            sql.SQL("COPY public.events ({}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')").format(
                selected
            ).as_string(cursor),
            copy_buffer(backup[writable]),
        )
        for constraint in schema["constraints"]:
            cursor.execute(
                sql.SQL("ALTER TABLE public.events ADD CONSTRAINT {} {}").format(
                    sql.Identifier(constraint["name"]),
                    sql.SQL(constraint["definition"]),
                )
            )
        cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename='events'"
        )
        existing_indexes = {row[0] for row in cursor.fetchall()}
        for index in schema["indexes"]:
            if index["name"] not in existing_indexes:
                cursor.execute(index["definition"])
        cursor.execute("ALTER TABLE public.events ENABLE ROW LEVEL SECURITY")
        cursor.execute("REVOKE ALL ON TABLE public.events FROM PUBLIC, anon, authenticated")
        cursor.execute("GRANT ALL PRIVILEGES ON TABLE public.events TO service_role")
        cursor.execute("COMMENT ON TABLE public.events IS %s", (schema["table_state"]["comment"],))
        for comment in schema["column_comments"]:
            if comment["comment"] is not None:
                cursor.execute(
                    sql.SQL("COMMENT ON COLUMN public.events.{} IS %s").format(
                        sql.Identifier(comment["column_name"])
                    ),
                    (comment["comment"],),
                )


def verify_mapping(cursor: Any, expected: pd.DataFrame, expected_hash: str) -> dict[str, Any]:
    live = fetch_frame(cursor, ["event_id", *NEW_COLUMNS])
    expected_columns = ["event_id", *NEW_COLUMNS]
    expected = expected[expected_columns].sort_values("event_id").reset_index(drop=True)
    mapping_mismatches = mismatch_count(expected, live, expected_columns)
    live_hash = mapping_sha256(live)
    cursor.execute(
        "SELECT source_class_v2,count(*) FROM public.events "
        "GROUP BY source_class_v2 ORDER BY source_class_v2"
    )
    source_counts = {row[0]: int(row[1]) for row in cursor.fetchall()}
    cursor.execute(
        "SELECT source_class_confidence_v2,count(*) FROM public.events "
        "GROUP BY source_class_confidence_v2 ORDER BY source_class_confidence_v2"
    )
    confidence_counts = {row[0]: int(row[1]) for row in cursor.fetchall()}
    if mapping_mismatches or live_hash != expected_hash:
        raise RuntimeError(
            f"Event-level mapping mismatch: cells={mapping_mismatches}, hash={live_hash}"
        )
    return {
        "mapping_mismatches": mapping_mismatches,
        "event_level_mapping_sha256": live_hash,
        "source_counts": source_counts,
        "confidence_counts": confidence_counts,
        "metadata_hash": frame_hash(live, expected_columns),
    }


def schema_state(cursor: Any) -> dict[str, Any]:
    cursor.execute(
        "SELECT column_name,is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='events' "
        "AND column_name=ANY(%s) ORDER BY column_name",
        (NEW_COLUMNS,),
    )
    columns = cursor.fetchall()
    cursor.execute(
        "SELECT conname,convalidated FROM pg_constraint "
        "WHERE conrelid='public.events'::regclass AND ("
        "pg_get_constraintdef(oid) LIKE '%source_class_v2%' OR "
        "pg_get_constraintdef(oid) LIKE '%document_class_v2%' OR "
        "pg_get_constraintdef(oid) LIKE '%source_class_confidence_v2%' OR "
        "pg_get_constraintdef(oid) LIKE '%source_classification_version%') "
        "ORDER BY conname"
    )
    constraints = cursor.fetchall()
    cursor.execute(
        "SELECT i.indisvalid,i.indisready,i.indislive FROM pg_index i "
        "WHERE i.indexrelid=to_regclass('public.ix_events_source_class_v2_published_at')"
    )
    index_state = cursor.fetchone()
    cursor.execute("SET enable_seqscan=off")
    cursor.execute(
        "EXPLAIN SELECT event_id FROM public.events "
        "WHERE source_class_v2='primary_document' ORDER BY published_at DESC LIMIT 25"
    )
    plan = "\n".join(row[0] for row in cursor.fetchall())
    cursor.execute("RESET enable_seqscan")
    return {
        "columns": columns,
        "constraints": constraints,
        "index_state": index_state,
        "index_used": "ix_events_source_class_v2_published_at" in plan,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--backup-dir", type=Path, default=BACKUP)
    parser.add_argument("--classification-csv", type=Path, default=CLASSIFICATION)
    parser.add_argument(
        "--classification-summary", type=Path, default=CLASSIFICATION_SUMMARY
    )
    args = parser.parse_args()
    backup_dir = args.backup_dir.resolve()
    classification_csv = args.classification_csv.resolve()
    classification_summary = args.classification_summary.resolve()
    backup_manifest = json.loads(
        (backup_dir / "manifest.json").read_text(encoding="utf-8")
    )
    for name, expected_file in backup_manifest["files"].items():
        if file_sha256(backup_dir / name) != expected_file["sha256"]:
            raise RuntimeError(f"Production backup file hash mismatch: {name}")
    backup = pd.read_parquet(backup_dir / "events.parquet")
    schema = json.loads(
        (backup_dir / "schema_snapshot.json").read_text(encoding="utf-8")
    )
    expected_mapping = pd.read_csv(classification_csv)
    mapping_summary = json.loads(classification_summary.read_text(encoding="utf-8"))
    if len(backup) != EXPECTED_ROWS or list(backup.columns) != backup_manifest["columns"]:
        raise RuntimeError("Production backup identity/schema mismatch")

    connection = connect(args.database_url)
    try:
        seed_exact_backup(connection, backup, schema)
        old_columns = list(backup.columns)
        with connection.cursor() as cursor:
            baseline = fetch_frame(cursor, old_columns)
            baseline_security = fetch_security(cursor)
            cursor.execute(
                "SELECT count(*),count(DISTINCT event_id),count(DISTINCT slug) FROM public.events"
            )
            baseline_counts = tuple(map(int, cursor.fetchone()))
        if baseline_counts != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS):
            raise RuntimeError("Production-shaped seed identity mismatch")
        seed_backup_mismatches = mismatch_count(backup, baseline, old_columns)
        if seed_backup_mismatches:
            raise RuntimeError(f"Production-shaped seed differs from backup: {seed_backup_mismatches}")

        execute_sql(connection, MIGRATION)
        with connection.cursor() as cursor:
            state_after_migration = schema_state(cursor)
            after_migration = fetch_frame(cursor, old_columns)
            security_after_migration = fetch_security(cursor)
        execute_sql(connection, MIGRATION)
        with connection.cursor() as cursor:
            state_after_migration_reapply = schema_state(cursor)
            after_migration_reapply = fetch_frame(cursor, old_columns)

        execute_sql(connection, BACKFILL)
        with connection.cursor() as cursor:
            first_mapping = verify_mapping(
                cursor,
                expected_mapping,
                mapping_summary["event_level_mapping_sha256"],
            )
            after_first = fetch_frame(cursor, old_columns)
            security_after_first = fetch_security(cursor)
            final_schema_state = schema_state(cursor)
        execute_sql(connection, BACKFILL)
        with connection.cursor() as cursor:
            second_mapping = verify_mapping(
                cursor,
                expected_mapping,
                mapping_summary["event_level_mapping_sha256"],
            )
            after_second = fetch_frame(cursor, old_columns)
            security_after_second = fetch_security(cursor)

        execute_sql(connection, ROLLBACK)
        with connection.cursor() as cursor:
            after_rollback = fetch_frame(cursor, old_columns)
            security_after_rollback = fetch_security(cursor)
            cursor.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='events' AND column_name=ANY(%s)",
                (NEW_COLUMNS,),
            )
            rollback_columns = int(cursor.fetchone()[0])
        execute_sql(connection, ROLLBACK)
        with connection.cursor() as cursor:
            after_rollback_reapply = fetch_frame(cursor, old_columns)
            security_after_rollback_reapply = fetch_security(cursor)
            cursor.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='events' AND column_name=ANY(%s)",
                (NEW_COLUMNS,),
            )
            rollback_reapply_columns = int(cursor.fetchone()[0])

        execute_sql(connection, MIGRATION)
        execute_sql(connection, BACKFILL)
        with connection.cursor() as cursor:
            reapplied_mapping = verify_mapping(
                cursor,
                expected_mapping,
                mapping_summary["event_level_mapping_sha256"],
            )
            after_reapply = fetch_frame(cursor, old_columns)
            security_after_reapply = fetch_security(cursor)
            cursor.execute(
                "SELECT count(*),count(DISTINCT event_id),count(DISTINCT slug) FROM public.events"
            )
            final_counts = tuple(map(int, cursor.fetchone()))

        stages = {
            "migration": after_migration,
            "migration_reapply": after_migration_reapply,
            "first_backfill": after_first,
            "repeated_backfill": after_second,
            "rollback": after_rollback,
            "repeated_rollback": after_rollback_reapply,
            "reapply_after_rollback": after_reapply,
        }
        old_mismatches = {
            name: mismatch_count(baseline, frame, old_columns)
            for name, frame in stages.items()
        }
        reaction_columns = backup_manifest["reaction_columns"]
        reaction_mismatches = {
            name: mismatch_count(baseline, frame, reaction_columns)
            for name, frame in stages.items()
        }
        legacy_mismatches = {
            name: mismatch_count(baseline, frame, ["event_id", "record_type", "source_type"])
            for name, frame in stages.items()
        }
        securities = [
            security_after_migration,
            security_after_first,
            security_after_second,
            security_after_rollback,
            security_after_rollback_reapply,
            security_after_reapply,
        ]
        checks = {
            "exact_backup_restored": seed_backup_mismatches == 0,
            "migration_apply_reapply_idempotent": state_after_migration
            == state_after_migration_reapply,
            "backfill_repeated_idempotent": first_mapping["metadata_hash"]
            == second_mapping["metadata_hash"],
            "rollback_repeated_idempotent": rollback_columns == 0
            and rollback_reapply_columns == 0,
            "reapply_after_rollback_exact": reapplied_mapping["event_level_mapping_sha256"]
            == mapping_summary["event_level_mapping_sha256"],
            "final_identity_exact": final_counts
            == (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS),
            "all_81_old_columns_mismatch_zero": all(value == 0 for value in old_mismatches.values()),
            "protected_reaction_mismatch_zero": all(
                value == 0 for value in reaction_mismatches.values()
            ),
            "legacy_record_source_mismatch_zero": all(
                value == 0 for value in legacy_mismatches.values()
            ),
            "security_unchanged": all(value == baseline_security for value in securities),
            "rls_enabled_no_client_access": baseline_security["rls_enabled"]
            and not baseline_security["policies"]
            and not baseline_security["client_grants"],
            "classification_counts_exact": reapplied_mapping["source_counts"]
            == {
                "news_media": 8_046,
                "official_announcement": 291,
                "primary_document": 736,
            },
            "confidence_counts_exact": reapplied_mapping["confidence_counts"]
            == {"high": 8_966, "medium": 107},
            "event_level_mapping_exact": reapplied_mapping["mapping_mismatches"] == 0,
            "mapping_hash_exact": reapplied_mapping["event_level_mapping_sha256"]
            == mapping_summary["event_level_mapping_sha256"],
            "new_columns_not_null": all(row[1] == "NO" for row in final_schema_state["columns"]),
            "new_constraints_valid": len(final_schema_state["constraints"]) == 4
            and all(row[1] for row in final_schema_state["constraints"]),
            "source_index_valid_ready_live_used": tuple(final_schema_state["index_state"])
            == (True, True, True)
            and final_schema_state["index_used"],
        }
        result = {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "postgresql_version": 16,
            "production_backup_path": str(backup_dir),
            "production_backup_sha256": backup_manifest["backup_sha256"],
            "old_column_count": len(old_columns),
            "rows_unique_ids_unique_slugs": list(final_counts),
            "source_counts": reapplied_mapping["source_counts"],
            "confidence_counts": reapplied_mapping["confidence_counts"],
            "event_level_mapping_sha256": reapplied_mapping["event_level_mapping_sha256"],
            "old_column_mismatches_by_stage": old_mismatches,
            "protected_reaction_mismatches_by_stage": reaction_mismatches,
            "legacy_record_source_mismatches_by_stage": legacy_mismatches,
            "checks": checks,
            "production_updated": False,
        }
        OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0 if all(checks.values()) else 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
