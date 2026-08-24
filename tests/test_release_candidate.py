import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.database.release_backfill import (
    ReleasePreflightError,
    validate_identity_sets,
    verify_target_project,
)
from scripts.database.release_contract import (
    DEFAULT_RELEASE_DATASET,
    DEFAULT_RELEASE_MANIFEST,
    METADATA_COLUMNS,
    PROTECTED_OLD_COLUMNS,
    RELEASE_COLUMNS,
    ReleaseValidationError,
    validate_manifest,
)
from scripts.database.release_backfill_rollback import validate_rollback_identity_sets


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "data/website/backups/pre_news_quality_v3/supabase_events_post_reaction_v2.parquet"
NEW = ROOT / "data/backfill_v3/production_rows_staging.parquet"
RELEASE_ARTIFACTS_AVAILABLE = (
    DEFAULT_RELEASE_DATASET.is_file()
    and DEFAULT_RELEASE_MANIFEST.is_file()
    and OLD.is_file()
    and NEW.is_file()
)
requires_private_release = pytest.mark.skipif(
    not RELEASE_ARTIFACTS_AVAILABLE,
    reason="private release/backfill artifacts are intentionally not stored in Git",
)


@requires_private_release
def test_release_manifest_derives_complete_identity_and_schema():
    frame, manifest, stats = validate_manifest(DEFAULT_RELEASE_MANIFEST)
    assert stats["rows"] == manifest["identity"]["total_rows"] == 9_073
    assert stats["old_rows"] == manifest["identity"]["old_rows"] == 7_878
    assert stats["new_rows"] == manifest["identity"]["new_rows"] == 1_195
    assert list(frame.columns) == RELEASE_COLUMNS
    assert len(RELEASE_COLUMNS) == 74
    assert set(METADATA_COLUMNS) <= set(frame.columns)


@requires_private_release
def test_staging_79_columns_are_explicitly_reduced_to_release_contract():
    staging = pd.read_parquet(NEW)
    release, _, _ = validate_manifest(DEFAULT_RELEASE_MANIFEST)
    assert len(staging.columns) == 79
    assert len(release.columns) == 74
    assert {"created_at", "updated_at", "btc_average_reaction", "eth_average_reaction", "sol_average_reaction"}.isdisjoint(release.columns)


@requires_private_release
def test_old_protected_reaction_and_identity_fields_are_unchanged():
    release, _, _ = validate_manifest(DEFAULT_RELEASE_MANIFEST)
    old = pd.read_parquet(OLD).sort_values("event_id").reset_index(drop=True)
    candidate = release[release.event_id.isin(old.event_id)].sort_values("event_id").reset_index(drop=True)
    from scripts.database.release_contract import canonical_value

    assert len(PROTECTED_OLD_COLUMNS) == 49
    for column in PROTECTED_OLD_COLUMNS:
        assert all(
            canonical_value(left) == canonical_value(right)
            for left, right in zip(candidate[column], old[column])
        ), column


@requires_private_release
def test_manifest_hash_tampering_is_rejected(tmp_path):
    manifest = json.loads(DEFAULT_RELEASE_MANIFEST.read_text(encoding="utf-8"))
    dataset = tmp_path / DEFAULT_RELEASE_DATASET.name
    dataset.write_bytes(DEFAULT_RELEASE_DATASET.read_bytes())
    ids_source = DEFAULT_RELEASE_MANIFEST.parent / manifest["new_ids"]["path"]
    (tmp_path / ids_source.name).write_bytes(ids_source.read_bytes())
    manifest["dataset"]["sha256"] = "0" * 64
    path = tmp_path / DEFAULT_RELEASE_MANIFEST.name
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReleaseValidationError, match="SHA-256"):
        validate_manifest(path)


def test_target_project_must_match_manifest_identity():
    verify_target_project(
        "postgresql://postgres.ickflwksigaotygtdyko:p@pooler.supabase.com/postgres",
        "ickflwksigaotygtdyko",
    )
    with pytest.raises(ReleasePreflightError, match="manifest target"):
        verify_target_project("postgresql://postgres.wrongproject:p@localhost/postgres", "expected")


def test_identity_preflight_is_idempotent_and_rejects_conflicts():
    old = {"old-1", "old-2"}
    new = {"new-1", "new-2"}
    assert validate_identity_sets(old, old, new) == "ready_to_insert"
    assert validate_identity_sets(old | new, old, new) == "already_applied"
    with pytest.raises(ReleasePreflightError, match="Partial backfill"):
        validate_identity_sets(old | {"new-1"}, old, new)
    with pytest.raises(ReleasePreflightError, match="missing_old"):
        validate_identity_sets({"old-1"}, old, new)
    with pytest.raises(ReleasePreflightError, match="unexpected"):
        validate_identity_sets(old | {"alien"}, old, new)


def test_rollback_identity_can_only_remove_the_new_set():
    old = {"old-1", "old-2"}
    new = {"new-1", "new-2"}
    assert validate_rollback_identity_sets(old | new, old, new) == "ready_to_delete"
    assert validate_rollback_identity_sets(old, old, new) == "already_rolled_back"
    with pytest.raises(ReleasePreflightError, match="intersects"):
        validate_rollback_identity_sets(old | new, old, {"old-1", "new-1"})
    with pytest.raises(ReleasePreflightError, match="Partial"):
        validate_rollback_identity_sets(old | {"new-1"}, old, new)


@requires_private_release
def test_incomplete_new_id_manifest_is_rejected(tmp_path):
    manifest = json.loads(DEFAULT_RELEASE_MANIFEST.read_text(encoding="utf-8"))
    dataset = tmp_path / DEFAULT_RELEASE_DATASET.name
    dataset.write_bytes(DEFAULT_RELEASE_DATASET.read_bytes())
    ids_source = DEFAULT_RELEASE_MANIFEST.parent / manifest["new_ids"]["path"]
    ids = ids_source.read_text(encoding="utf-8").splitlines()[:-1]
    ids_path = tmp_path / ids_source.name
    ids_path.write_text("\n".join(ids) + "\n", encoding="utf-8")
    from scripts.database.release_contract import sha256_file, sha256_lines

    manifest["new_ids"]["sha256"] = sha256_file(ids_path)
    manifest["identity"]["new_ids_sha256"] = sha256_lines(ids)
    path = tmp_path / DEFAULT_RELEASE_MANIFEST.name
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReleaseValidationError, match="incomplete or extra"):
        validate_manifest(path)


@requires_private_release
def test_null_reactions_remain_null_not_zero():
    release, _, _ = validate_manifest(DEFAULT_RELEASE_MANIFEST)
    reaction_columns = [
        f"{asset}_{horizon}"
        for asset in ("btc", "eth", "sol")
        for horizon in ("1m", "5m", "15m", "1h", "4h", "24h")
    ]
    assert release[reaction_columns].isna().sum().sum() == 6_945
    assert release[reaction_columns].isna().all(axis=1).sum() == 133


def test_data_quality_migration_uses_generated_column_safe_asset_expression():
    sql = (ROOT / "database/migrations/006_data_quality_v2_staging.sql").read_text(encoding="utf-8")
    assert "array_to_string(related_assets" not in sql
    assert "related_assets @> ARRAY['BTC']::text[]" in sql
