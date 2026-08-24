import re
from pathlib import Path

from scripts.quality.build_source_classification_v2 import (
    MEDIUM_CONFIDENCE_EVENT_IDS,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "database/migrations/009_source_classification_reaction_v2.sql").read_text(
    encoding="utf-8"
)
BACKFILL = (ROOT / "database/migrations/009_source_classification_backfill.sql").read_text(
    encoding="utf-8"
)
ROLLBACK = (ROOT / "database/migrations/009_source_classification_rollback.sql").read_text(
    encoding="utf-8"
)
CUTOVER = (ROOT / "scripts/database/dz14_production_cutover.py").read_text(
    encoding="utf-8"
)


def test_migration_009_is_atomic_idempotent_and_uses_independent_columns():
    assert MIGRATION.count("BEGIN;") == 1
    assert MIGRATION.count("COMMIT;") == 1
    for column in (
        "source_class_v2",
        "document_class_v2",
        "source_class_confidence_v2",
        "source_classification_version",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in MIGRATION
    assert "CREATE INDEX IF NOT EXISTS ix_events_source_class_v2_published_at" in MIGRATION
    assert "UPDATE public.events" not in MIGRATION


def test_backfill_has_exact_release_guards_and_never_reads_legacy_classification():
    assert "LOCK TABLE public.events" in BACKFILL
    for expected in ("8046::bigint", "736::bigint", "291::bigint", "8966::bigint", "107::bigint"):
        assert expected in BACKFILL
    assert "dz13-source-class-v2" in BACKFILL
    assert "event.record_type" not in BACKFILL
    assert "event.source_type" not in BACKFILL
    assert re.search(r"\bSET\s+source_type\b", BACKFILL, re.IGNORECASE) is None
    assert re.search(r"\bSET\s+record_type\b", BACKFILL, re.IGNORECASE) is None


def test_sql_medium_identity_set_exactly_matches_frozen_manifest_builder():
    sql_ids = set(
        re.findall(r"\('((?:evt18|bf3)-[a-z0-9-]+)'\)", BACKFILL)
    )
    assert sql_ids == MEDIUM_CONFIDENCE_EVENT_IDS
    assert len(sql_ids) == 107


def test_dz14_sql_never_references_protected_reaction_values():
    protected = [
        f"{asset}_{horizon}"
        for asset in ("btc", "eth", "sol")
        for horizon in ("1m", "5m", "15m", "1h", "4h", "24h")
    ]
    for statement in (MIGRATION, BACKFILL, ROLLBACK):
        assert all(column not in statement for column in protected)


def test_migration_009_does_not_widen_database_access():
    upper = MIGRATION.upper()
    assert "GRANT " not in upper
    assert "CREATE POLICY" not in upper
    assert "DISABLE ROW LEVEL SECURITY" not in upper


def test_rollback_is_schema_only_atomic_and_idempotent():
    assert ROLLBACK.count("BEGIN;") == 1
    assert ROLLBACK.count("COMMIT;") == 1
    assert "UPDATE public.events" not in ROLLBACK
    for column in (
        "source_class_v2",
        "document_class_v2",
        "source_class_confidence_v2",
        "source_classification_version",
    ):
        assert f"DROP COLUMN IF EXISTS {column}" in ROLLBACK
    assert "DROP INDEX IF EXISTS public.ix_events_source_class_v2_published_at" in ROLLBACK


def test_production_cutover_protects_all_old_columns_and_exact_mapping():
    assert '"all_preexisting_columns_sha256"' in CUTOVER
    assert '"legacy_record_source_sha256"' in CUTOVER
    assert "mapping_sha256(metadata_frame)" in CUTOVER
    assert 'grouped_counts(cursor, "source_class_v2")' in CUTOVER
    assert 'WHERE source_class_v2=\'primary_document\'' in CUTOVER
    assert "protected_existing_except_source_type_sha256" not in CUTOVER
    assert 'grouped_counts(cursor, "source_type")' not in CUTOVER
    assert "UPDATE public.events live SET source_type" not in CUTOVER
    assert 'set_session(readonly=True, autocommit=False)' in CUTOVER
    assert '"all_81_columns_sha256"' in CUTOVER
