import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "data/website/backups/pre_news_quality_v3/supabase_events_post_reaction_v2.parquet"
CANDIDATES = ROOT / "data/backfill_v3/historical_candidates_qa.parquet"
REACTIONS = ROOT / "data/backfill_v3/historical_candidate_reactions_v2.parquet"
STAGING = ROOT / "data/backfill_v3/production_rows_staging.parquet"
HORIZONS = ("1m", "5m", "15m", "1h", "4h", "24h")
PRIVATE_ARTIFACTS_AVAILABLE = all(
    path.is_file() for path in (BACKUP, CANDIDATES, REACTIONS, STAGING)
)
requires_private_artifacts = pytest.mark.skipif(
    not PRIVATE_ARTIFACTS_AVAILABLE,
    reason="private news-quality artifacts are intentionally not stored in Git",
)


@requires_private_artifacts
def test_production_baseline_identity_is_complete_and_unique():
    baseline = pd.read_parquet(BACKUP)
    assert len(baseline) == 7_878
    assert baseline.event_id.nunique() == len(baseline)
    assert baseline.slug.nunique() == len(baseline)


@requires_private_artifacts
def test_candidates_have_credible_identity_provenance_and_classification():
    rows = pd.read_parquet(CANDIDATES)
    timestamps = pd.to_datetime(rows.published_at, utc=True)
    assert len(rows) == 1_195
    assert rows.candidate_id.nunique() == len(rows)
    assert rows.source_url.nunique() == len(rows)
    assert rows.title.str.casefold().nunique() == len(rows)
    assert timestamps.dt.year.between(2017, 2022).all()
    assert rows.quality_status.eq("accepted").all()
    assert rows.record_type.eq("news_article").all()
    assert rows.provenance.str.len().gt(0).all()
    assert rows.capture_method.str.len().gt(0).all()
    allowed = {"BTC", "ETH", "SOL"}
    for row in rows.itertuples(index=False):
        assets = set(row.related_assets)
        assert assets <= allowed
        assert (pd.isna(row.primary_asset) and len(assets) != 1) or row.primary_asset in assets


@requires_private_artifacts
def test_candidate_reaction_v2_values_are_open_to_open_and_explicitly_missing():
    rows = pd.read_parquet(REACTIONS)
    assert len(rows) == 1_195 * 3
    assert rows.methodology_version.eq("reaction_v2_next_full_minute_open_to_open").all()
    assert set(rows.reaction_quality) <= {"verified_raw", "partial_verified_raw", "missing"}
    for horizon in HORIZONS:
        valid = rows.reference_price.notna() & rows[f"{horizon}_endpoint_open"].notna()
        expected = (rows.loc[valid, f"{horizon}_endpoint_open"] / rows.loc[valid, "reference_price"] - 1) * 100
        assert np.allclose(rows.loc[valid, horizon], expected, rtol=0, atol=1e-12)
    assert rows.loc[rows.reaction_quality.eq("missing"), "missing_reason"].notna().all()


@requires_private_artifacts
def test_staged_rows_do_not_collide_with_existing_ids_or_slugs():
    old = pd.read_parquet(BACKUP)
    new = pd.read_parquet(STAGING)
    assert len(new) == 1_195
    assert not (set(old.event_id) & set(new.event_id))
    assert not (set(old.slug) & set(new.slug))
    assert new.event_id.nunique() == len(new)
    assert new.slug.nunique() == len(new)
    assert new.reaction_methodology.eq("reaction_v2_next_full_minute_open_to_open").all()


@requires_private_artifacts
def test_independent_reaction_sample_and_metadata_gates_pass():
    reaction = json.loads((ROOT / "reports/HISTORICAL_CANDIDATE_REACTION_V2.json").read_text())
    metadata = json.loads((ROOT / "reports/METADATA_QA_V3_SUMMARY.json").read_text())
    assert reaction["independent_qa_cells"] >= 500
    assert reaction["independent_qa_failures"] == 0
    assert reaction["selected_candle_problems"] == 0
    assert metadata["asset_changes"] == 0
    assert metadata["record_type_failures"] == 0
    assert metadata["candidate_story_pairs"] == 0


@requires_private_artifacts
def test_semantic_batch_is_bounded_below_approved_budget_and_not_production():
    status = json.loads((ROOT / "reports/SEMANTIC_BATCH_V3_STATUS.json").read_text())
    requests = (ROOT / "data/backfill_v3/semantic_batch/semantic_v3_requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(requests) == 1_508
    assert status["hard_max_total_cost_usd"] <= status["approved_cap_usd"] == 0.58
    assert status["production_updated"] is False
    custom_ids = []
    for line in requests:
        item = json.loads(line)
        custom_ids.append(item["custom_id"])
        assert item["url"] == "/v1/responses"
        assert item["body"]["model"] == "gpt-5-mini"
        assert item["body"]["max_output_tokens"] == 180
        assert item["body"]["text"]["format"]["strict"] is True
    assert len(set(custom_ids)) == len(custom_ids)


@requires_private_artifacts
def test_semantic_batch_completed_and_validated_without_production_cutover():
    batch = json.loads((ROOT / "reports/SEMANTIC_BATCH_V3_STATUS.json").read_text())
    validation = json.loads((ROOT / "reports/SEMANTIC_V3_VALIDATION.json").read_text())
    result = pd.read_parquet(ROOT / "data/backfill_v3/semantic_batch/semantic_v3_results_validated.parquet")
    existing = pd.read_parquet(ROOT / "data/backfill_v3/existing_semantic_staging.parquet")
    candidates = pd.read_parquet(STAGING)
    assert batch["status"] == "completed"
    assert batch["request_counts"] == {"completed": 1_508, "failed": 0, "total": 1_508}
    assert batch["actual_estimated_cost_usd"] <= batch["approved_cap_usd"] == 0.58
    assert batch["validation_status"] == validation["status"] == "PASS"
    assert len(result) == 1_508 and len(existing) == 313 and len(candidates) == 1_195
    assert candidates[["importance", "ai_prompt_version"]].notna().all().all()
    assert result.loc[result.sentiment_label.eq("negative"), "sentiment_score"].lt(0).all()
    assert result.loc[result.sentiment_label.eq("not_applicable"), "sentiment_score"].isna().all()
    assert batch["production_updated"] is False and validation["production_updated"] is False
