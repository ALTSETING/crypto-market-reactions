"""Backup live Supabase event classification and print the database contract."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import psycopg2
from dotenv import load_dotenv

from scripts.database.import_events import ROOT, normalize_database_url


EXPECTED_PROJECT_REF = "ickflwksigaotygtdyko"
EXPECTED_ROWS = 7_878
BACKUP_DIR = ROOT / "data" / "website" / "backups"
PARQUET_BACKUP = BACKUP_DIR / "supabase_events_classification_pre_20260823.parquet"
CSV_BACKUP = BACKUP_DIR / "supabase_events_classification_pre_20260823.csv"
CLASSIFICATION_COLUMNS = (
    "event_id",
    "slug",
    "primary_asset",
    "related_assets",
    "category",
    "sentiment",
    "sentiment_score",
    "importance",
    "updated_at",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    load_dotenv(ROOT / ".env")
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    parsed = urlparse(database_url)
    target_identity = f"{parsed.hostname or ''} {parsed.username or ''}"
    if EXPECTED_PROJECT_REF not in target_identity:
        raise RuntimeError("DATABASE_URL does not identify the expected Supabase project")
    if PARQUET_BACKUP.exists() or CSV_BACKUP.exists():
        raise RuntimeError("Refusing to overwrite an existing Supabase classification backup")

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug) FROM public.events"
            )
            total, unique_event_ids, unique_slugs = map(int, cursor.fetchone())
            if (total, unique_event_ids, unique_slugs) != (
                EXPECTED_ROWS,
                EXPECTED_ROWS,
                EXPECTED_ROWS,
            ):
                raise RuntimeError("Live event count or uniqueness does not match the expected dataset")

            cursor.execute(
                "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.events'::regclass"
            )
            rls_enabled = bool(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT policyname, roles, cmd
                FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'events'
                ORDER BY policyname
                """
            )
            policies = cursor.fetchall()
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'events'
                ORDER BY indexname
                """
            )
            indexes = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT grantee, privilege_type
                FROM information_schema.role_table_grants
                WHERE table_schema = 'public' AND table_name = 'events'
                  AND grantee IN ('anon', 'authenticated', 'PUBLIC')
                ORDER BY grantee, privilege_type
                """
            )
            grants = cursor.fetchall()
            cursor.execute(
                f"SELECT {', '.join(CLASSIFICATION_COLUMNS)} FROM public.events ORDER BY event_id"
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    backup = pd.DataFrame(rows, columns=CLASSIFICATION_COLUMNS)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup.to_parquet(PARQUET_BACKUP, index=False)
    backup.to_csv(CSV_BACKUP, index=False, encoding="utf-8", na_rep="")
    print(
        json.dumps(
            {
                "target_host": parsed.hostname,
                "target_user": parsed.username,
                "rows": total,
                "unique_event_ids": unique_event_ids,
                "unique_slugs": unique_slugs,
                "rls_enabled": rls_enabled,
                "policies": policies,
                "grants": grants,
                "indexes": indexes,
                "parquet_backup": str(PARQUET_BACKUP.relative_to(ROOT)),
                "parquet_sha256": sha256(PARQUET_BACKUP),
                "csv_backup": str(CSV_BACKUP.relative_to(ROOT)),
                "csv_sha256": sha256(CSV_BACKUP),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
