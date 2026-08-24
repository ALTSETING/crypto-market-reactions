"""Exercise import, idempotency, failure rollback, and exact rollback on a disposable DB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.database.release_backfill import (  # noqa: E402
    ReleasePreflightError,
    copy_buffer,
    insert_new_events,
    normalize_database_url,
    preflight_database,
)
from scripts.database.release_backfill_rollback import rollback_database  # noqa: E402
from scripts.database.release_contract import (  # noqa: E402
    DEFAULT_RELEASE_MANIFEST,
    RELEASE_COLUMNS,
    validate_manifest,
)


REPORT = ROOT / "reports" / "DISPOSABLE_RELEASE_REHEARSAL.json"


def seed_rows(connection, frame) -> int:
    columns_sql = ",".join(f'"{column}"' for column in RELEASE_COLUMNS)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMP TABLE events_seed (LIKE public.events INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            cursor.copy_expert(
                f"COPY pg_temp.events_seed ({columns_sql}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
                copy_buffer(frame[RELEASE_COLUMNS]),
            )
            cursor.execute(
                f"INSERT INTO public.events ({columns_sql}) SELECT {columns_sql} FROM pg_temp.events_seed"
            )
            return int(cursor.rowcount)


def count_rows(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM public.events")
        return int(cursor.fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    url = normalize_database_url(args.database_url)
    release, manifest, stats = validate_manifest(args.manifest)
    new_ids_path = args.manifest.parent / manifest["new_ids"]["path"]
    new_ids = new_ids_path.read_text(encoding="utf-8").splitlines()
    old = release[~release.event_id.isin(new_ids)]
    new = release[release.event_id.isin(new_ids)]
    insert_confirmation = f"INSERT-{stats['new_rows']}-NEW-EVENTS"
    rollback_confirmation = f"DELETE-{stats['new_rows']}-BACKFILL-EVENTS"

    connection = psycopg2.connect(url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("TRUNCATE public.events")
        seeded = seed_rows(connection, old)
        initial_preflight = preflight_database(url, args.manifest)

        # A partial conflicting new-ID state must fail before the importer writes.
        seed_rows(connection, new.head(1))
        conflict_rejected = False
        try:
            preflight_database(url, args.manifest)
        except ReleasePreflightError as exc:
            conflict_rejected = "Partial backfill" in str(exc)
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM public.events WHERE event_id=%s", (new.iloc[0].event_id,))
        if not conflict_rejected:
            raise RuntimeError("Partial existing new-ID conflict was not rejected")

        # A database error during COPY/INSERT must roll the whole transaction back.
        blocked_id = new.iloc[len(new) // 2].event_id
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION public.reject_disposable_release_row()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                      IF NEW.event_id = %s THEN RAISE EXCEPTION 'disposable forced failure'; END IF;
                      RETURN NEW;
                    END $$
                    """,
                    (blocked_id,),
                )
                cursor.execute(
                    "CREATE TRIGGER reject_disposable_release_row "
                    "BEFORE INSERT ON public.events FOR EACH ROW "
                    "EXECUTE FUNCTION public.reject_disposable_release_row()"
                )
        transaction_rollback_pass = False
        try:
            insert_new_events(url, args.manifest, insert_confirmation)
        except psycopg2.Error:
            connection.rollback()
            transaction_rollback_pass = count_rows(connection) == stats["old_rows"]
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("DROP TRIGGER reject_disposable_release_row ON public.events")
                cursor.execute("DROP FUNCTION public.reject_disposable_release_row()")
        if not transaction_rollback_pass:
            raise RuntimeError("Forced insert failure did not roll back atomically")

        first_import = insert_new_events(url, args.manifest, insert_confirmation)
        repeat_preflight = preflight_database(url, args.manifest)
        repeat_import = insert_new_events(url, args.manifest, insert_confirmation)
        rollback_preflight = rollback_database(url, args.manifest)
        rollback = rollback_database(url, args.manifest, rollback_confirmation)
        repeat_rollback = rollback_database(url, args.manifest, rollback_confirmation)
        reimport = insert_new_events(url, args.manifest, insert_confirmation)

        result = {
            "status": "PASS",
            "seeded_old_rows": seeded,
            "initial_preflight": initial_preflight,
            "partial_conflict_rejected": conflict_rejected,
            "transaction_rollback_on_error": transaction_rollback_pass,
            "first_import": first_import,
            "repeat_preflight": repeat_preflight,
            "repeat_import": repeat_import,
            "rollback_preflight": rollback_preflight,
            "rollback": rollback,
            "repeat_rollback": repeat_rollback,
            "reimport": reimport,
            "final_rows": count_rows(connection),
            "production_updated": False,
            "target": "disposable_test_database",
        }
        if result["final_rows"] != stats["rows"]:
            raise RuntimeError("Disposable rehearsal ended with an incorrect identity count")
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
