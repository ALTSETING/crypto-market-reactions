"""Exercise migration 008 against an explicitly disposable PostgreSQL database."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg2
from psycopg2 import errors

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "database/migrations/008_distributed_rate_limit.sql"
FUNCTION_SIGNATURE = "public.consume_events_rate_limit(text,integer,integer)"


def connect(url: str):
    return psycopg2.connect(url, application_name="migration_008_disposable_test")


def denied_as(url: str, role: str, statement: str) -> bool:
    connection = connect(url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL ROLE {role}")
            try:
                cursor.execute(statement)
            except errors.InsufficientPrivilege:
                connection.rollback()
                return True
        connection.rollback()
        return False
    finally:
        connection.close()


def consume(url: str, key_hash: str, limit: int = 20) -> dict:
    connection = connect(url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL ROLE service_role")
                cursor.execute(
                    "SELECT public.consume_events_rate_limit(%s, %s, 60)",
                    (key_hash, limit),
                )
                return cursor.fetchone()[0]
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    sql = MIGRATION.read_text(encoding="utf-8")

    admin = connect(args.database_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
                        CREATE ROLE anon NOLOGIN;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
                        CREATE ROLE authenticated NOLOGIN;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
                        CREATE ROLE service_role NOLOGIN;
                    END IF;
                END
                $$;
                DROP FUNCTION IF EXISTS public.consume_events_rate_limit(text, integer, integer);
                DROP TABLE IF EXISTS public.api_rate_limit_buckets;
                DROP TABLE IF EXISTS public.migration_008_sentinel;
                CREATE TABLE public.migration_008_sentinel(value integer NOT NULL);
                INSERT INTO public.migration_008_sentinel VALUES (1);
                REVOKE ALL ON public.migration_008_sentinel FROM PUBLIC, anon, authenticated, service_role;
            """)

            failed_sql = sql.replace("COMMIT;", "SELECT 1 / 0;\nCOMMIT;")
            failed_rolled_back = False
            try:
                cursor.execute(failed_sql)
            except errors.DivisionByZero:
                failed_rolled_back = True
                cursor.execute("ROLLBACK")
            cursor.execute(
                "SELECT to_regclass('public.api_rate_limit_buckets'), "
                "to_regprocedure('public.consume_events_rate_limit(text,integer,integer)')"
            )
            rollback_objects = cursor.fetchone()
            failed_rolled_back = failed_rolled_back and rollback_objects == (None, None)

            cursor.execute(sql)
            cursor.execute(sql)
            cursor.execute("""
                SELECT c.relrowsecurity
                FROM pg_class c
                WHERE c.oid='public.api_rate_limit_buckets'::regclass
            """)
            rls_enabled = bool(cursor.fetchone()[0])
            cursor.execute("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname='public' AND tablename='api_rate_limit_buckets'
                ORDER BY indexname
            """)
            indexes = [row[0] for row in cursor.fetchall()]
            cursor.execute("""
                SELECT p.prosecdef, p.proconfig
                FROM pg_proc p
                WHERE p.oid='public.consume_events_rate_limit(text,integer,integer)'::regprocedure
            """)
            security_definer, function_config = cursor.fetchone()
            cursor.execute("""
                SELECT
                    has_function_privilege('anon', %s, 'EXECUTE'),
                    has_function_privilege('authenticated', %s, 'EXECUTE'),
                    has_function_privilege('service_role', %s, 'EXECUTE'),
                    has_table_privilege('anon', 'public.api_rate_limit_buckets', 'SELECT'),
                    has_table_privilege('authenticated', 'public.api_rate_limit_buckets', 'SELECT')
            """, (FUNCTION_SIGNATURE, FUNCTION_SIGNATURE, FUNCTION_SIGNATURE))
            anon_exec, auth_exec, service_exec, anon_table, auth_table = cursor.fetchone()
    finally:
        admin.close()

    key_hash = "a" * 64
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _: consume(args.database_url, key_hash), range(40)))
    allowed = sum(bool(result["allowed"]) for result in results)
    remaining = sorted(int(result["remaining"]) for result in results)

    admin = connect(args.database_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT request_count FROM public.api_rate_limit_buckets WHERE key_hash=%s",
                (key_hash,),
            )
            concurrent_count = int(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO public.api_rate_limit_buckets VALUES (%s, now()-interval '3 days', 1)",
                ("b" * 64,),
            )
        consume(args.database_url, "c" * 64)
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM public.api_rate_limit_buckets "
                "WHERE window_started_at < now()-interval '2 days'"
            )
            expired_after_cleanup = int(cursor.fetchone()[0])

        anon_rpc_denied = denied_as(
            args.database_url,
            "anon",
            "SELECT public.consume_events_rate_limit('dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd', 1, 60)",
        )
        auth_rpc_denied = denied_as(
            args.database_url,
            "authenticated",
            "SELECT public.consume_events_rate_limit('eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee', 1, 60)",
        )
        service_other_table_denied = denied_as(
            args.database_url,
            "service_role",
            "UPDATE public.migration_008_sentinel SET value=2",
        )

        with admin.cursor() as cursor:
            cursor.execute(
                "DROP FUNCTION public.consume_events_rate_limit(text, integer, integer); "
                "DROP TABLE public.api_rate_limit_buckets"
            )
            cursor.execute(
                "SELECT to_regclass('public.api_rate_limit_buckets'), "
                "to_regprocedure('public.consume_events_rate_limit(text,integer,integer)'), "
                "(SELECT value FROM public.migration_008_sentinel)"
            )
            table_after, function_after, sentinel_after = cursor.fetchone()
    finally:
        admin.close()

    checks = {
        "failure_transaction_rolled_back": failed_rolled_back,
        "idempotent_reapply": True,
        "rls_enabled": rls_enabled,
        "ttl_index_present": "ix_api_rate_limit_buckets_window_started_at" in indexes,
        "primary_key_index_present": "api_rate_limit_buckets_pkey" in indexes,
        "security_definer": bool(security_definer),
        "fixed_safe_search_path": function_config == ["search_path=pg_catalog, public, pg_temp"],
        "anon_execute_denied": not anon_exec and anon_rpc_denied,
        "authenticated_execute_denied": not auth_exec and auth_rpc_denied,
        "service_role_execute_allowed": bool(service_exec),
        "client_table_access_denied": not anon_table and not auth_table,
        "concurrency_exact_count": concurrent_count == 40,
        "concurrency_exact_limit": allowed == 20 and remaining[0] == 0 and remaining[-1] == 19,
        "ttl_cleanup": expired_after_cleanup == 0,
        "cannot_modify_other_tables": service_other_table_denied,
        "explicit_rollback_clean": table_after is None and function_after is None and sentinel_after == 1,
    }
    print(json.dumps({"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
