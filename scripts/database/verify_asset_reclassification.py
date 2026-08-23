"""Verify live classification, security, indexes and FTS after the controlled update."""

from __future__ import annotations

import json
import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv

from scripts.database.import_events import DEFAULT_DATASET, ROOT, normalize_database_url, prepare_dataset


OUTPUT = ROOT / "reports" / "supabase_asset_reclassification_verification.json"
EXPECTED_INDEXES = {
    "events_pkey",
    "events_slug_key",
    "ix_events_category",
    "ix_events_primary_asset",
    "ix_events_published_at",
    "ix_events_related_assets_gin",
    "ix_events_search_vector_gin",
    "ix_events_source",
}


def main() -> int:
    local = prepare_dataset(DEFAULT_DATASET).sort_values("event_id").reset_index(drop=True)
    load_dotenv(ROOT / ".env")
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug) FROM public.events")
            total, unique_event_ids, unique_slugs = map(int, cursor.fetchone())
            asset_counts = {}
            for asset in ("BTC", "ETH", "SOL"):
                cursor.execute(
                    "SELECT count(*) FROM public.events WHERE related_assets @> ARRAY[%s]::text[]",
                    (asset,),
                )
                asset_counts[asset] = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM public.events WHERE cardinality(related_assets) = 0")
            empty_assets = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT count(*) FROM public.events WHERE related_assets @> ARRAY['BTC','ETH','SOL']::text[]"
            )
            three_assets = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT count(*) FROM public.events WHERE source = 'sec' AND related_assets @> ARRAY['SOL']::text[]"
            )
            sol_sec = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT count(*) FROM public.events
                WHERE source = 'sec'
                  AND title ~ '^Coinbase Global .+ filing [0-9-]+$'
                  AND related_assets @> ARRAY['SOL']::text[]
                """
            )
            sol_generic_coinbase = int(cursor.fetchone()[0])
            cursor.execute("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.events'::regclass")
            rls_enabled = bool(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT policyname, roles, cmd FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'events'
                ORDER BY policyname
                """
            )
            policies = cursor.fetchall()
            cursor.execute(
                """
                SELECT grantee, privilege_type FROM information_schema.role_table_grants
                WHERE table_schema = 'public' AND table_name = 'events'
                  AND grantee IN ('anon', 'authenticated', 'PUBLIC')
                ORDER BY grantee, privilege_type
                """
            )
            grants = cursor.fetchall()
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'events'"
            )
            indexes = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT is_generated, generation_expression
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'events'
                  AND column_name = 'search_vector'
                """
            )
            fts_column = cursor.fetchone()
            cursor.execute(
                """
                SELECT count(*) FROM public.events
                WHERE search_vector @@ websearch_to_tsquery('english', 'ethereum ETF')
                """
            )
            fts_matches = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT event_id, primary_asset, related_assets FROM public.events ORDER BY event_id"
            )
            live_rows = cursor.fetchall()
    finally:
        connection.close()

    live = pd.DataFrame(live_rows, columns=["event_id", "primary_asset", "related_assets"])
    expected = local[["event_id", "primary_asset", "related_assets"]]
    primary_equal = (
        (live.primary_asset.isna() & expected.primary_asset.isna())
        | live.primary_asset.eq(expected.primary_asset).fillna(False)
    )
    related_equal = live.apply(
        lambda row: list(row.related_assets) == list(expected.iloc[row.name].related_assets), axis=1
    )
    classification_mismatches = int((~(primary_equal & related_equal)).sum())

    checks = {
        "total_is_7878": total == 7_878,
        "event_ids_unique": unique_event_ids == total,
        "slugs_unique": unique_slugs == total,
        "local_classification_matches": classification_mismatches == 0,
        "generic_coinbase_absent_from_sol": sol_generic_coinbase == 0,
        "rls_enabled": rls_enabled,
        "client_roles_have_no_table_grants": grants == [],
        "no_public_policies": policies == [],
        "expected_indexes_present": EXPECTED_INDEXES.issubset(indexes),
        "fts_generated": bool(fts_column and fts_column[0] == "ALWAYS"),
        "fts_query_returns_rows": fts_matches > 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"Supabase verification failed: {checks}")

    result = {
        "checks": checks,
        "total": total,
        "unique_event_ids": unique_event_ids,
        "unique_slugs": unique_slugs,
        "asset_counts": asset_counts,
        "empty_related_assets": empty_assets,
        "three_assets": three_assets,
        "sol_sec": sol_sec,
        "sol_generic_coinbase": sol_generic_coinbase,
        "classification_mismatches": classification_mismatches,
        "fts_matches_ethereum_etf": fts_matches,
        "indexes": sorted(indexes),
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
