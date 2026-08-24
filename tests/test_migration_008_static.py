from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "database/migrations/008_distributed_rate_limit.sql").read_text(
    encoding="utf-8"
)
VALIDATOR = (ROOT / "scripts/database/validate_dz9a_cutover.py").read_text(
    encoding="utf-8"
)


def test_rate_limit_migration_has_fixed_safe_security_boundary():
    assert "SECURITY DEFINER" in SQL
    assert "SET search_path = pg_catalog, public, pg_temp" in SQL
    assert (
        "REVOKE ALL ON FUNCTION public.consume_events_rate_limit"
        "(text, integer, integer) FROM PUBLIC, anon, authenticated"
    ) in SQL
    assert (
        "GRANT EXECUTE ON FUNCTION public.consume_events_rate_limit"
        "(text, integer, integer) TO service_role"
    ) in SQL


def test_rate_limit_migration_is_atomic_idempotent_and_ttl_indexed():
    assert SQL.count("BEGIN;") == 1
    assert SQL.count("COMMIT;") == 1
    assert "CREATE TABLE IF NOT EXISTS public.api_rate_limit_buckets" in SQL
    assert "CREATE INDEX IF NOT EXISTS ix_api_rate_limit_buckets_window_started_at" in SQL
    assert "CREATE OR REPLACE FUNCTION public.consume_events_rate_limit" in SQL
    assert "LIMIT 1000" in SQL
    assert "interval '2 days'" in SQL


def test_rate_limit_function_has_no_dynamic_sql_or_cross_table_mutation():
    assert "EXECUTE format" not in SQL
    assert "format(" not in SQL.lower()
    assert SQL.count("INSERT INTO public.") == 1
    assert SQL.count("DELETE FROM public.") == 1
    assert "UPDATE public." not in SQL


def test_cutover_validator_detects_the_actual_migration_008_objects():
    assert "public.api_rate_limit_buckets" in VALIDATOR
    assert (
        "public.consume_events_rate_limit(text,integer,integer)" in VALIDATOR
    )
    assert "public.distributed_rate_limits" not in VALIDATOR
