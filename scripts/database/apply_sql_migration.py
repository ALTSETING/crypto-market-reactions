"""Apply one repository SQL migration to the configured PostgreSQL target."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv

from scripts.database.import_events import ROOT, normalize_database_url


MIGRATIONS = (ROOT / "database" / "migrations").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration", type=Path)
    parser.add_argument("--expected-project-ref")
    args = parser.parse_args()
    migration = args.migration.resolve()
    if migration.parent != MIGRATIONS or migration.suffix.lower() != ".sql":
        raise RuntimeError("Migration must be a direct SQL child of database/migrations")

    load_dotenv(ROOT / ".env")
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    parsed = urlparse(database_url)
    target_identity = f"{parsed.hostname or ''} {parsed.username or ''}"
    if args.expected_project_ref and args.expected_project_ref not in target_identity:
        raise RuntimeError("DATABASE_URL does not identify the explicitly confirmed project")
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(migration.read_text(encoding="utf-8"))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT conname, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'public.events'::regclass
                  AND conname = 'events_related_assets_check'
                """
            )
            constraint = cursor.fetchone()
    finally:
        connection.close()
    print(
        json.dumps(
            {
                "migration": str(migration.relative_to(ROOT)),
                "project_ref": args.expected_project_ref,
                "related_assets_constraint": constraint,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
