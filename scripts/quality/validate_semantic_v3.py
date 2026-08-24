"""Normalize the documented score-sign defect and validate/stage V3 semantics."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/backfill_v3"
BATCH = DATA / "semantic_batch"
REPORTS = ROOT / "reports"
SEED = 20260824


def main() -> int:
    raw = pd.read_parquet(BATCH / "semantic_v3_results.parquet").copy()
    manifest = pd.read_parquet(BATCH / "semantic_v3_manifest.parquet")
    if len(raw) != 1_508 or raw.event_id.nunique() != 1_508 or set(raw.event_id) != set(manifest.event_id):
        raise RuntimeError("semantic identity/coverage gate failed")

    raw["raw_sentiment_score"] = raw.sentiment_score
    raw["raw_sentiment_label"] = raw.sentiment_label
    curated_news = {
        "bf3-0bf0ef660fe9954025de": ("neutral", 0.0, "title-only interview has no directional evidence"),
        "bf3-a8478b03e610b5c0c015": ("positive", 0.6, "ETH ETF application is positive market-access evidence"),
        "bf3-99cb9b4818d995cee2c4": ("positive", 0.55, "commodity classification is positive legal-clarity evidence"),
    }
    raw["semantic_override"] = "none"
    for event_id, (label, score, reason) in curated_news.items():
        selected = raw.event_id.eq(event_id)
        if int(selected.sum()) != 1:
            raise RuntimeError(f"curated semantic event missing: {event_id}")
        raw.loc[selected, "sentiment_label"] = label
        raw.loc[selected, "sentiment_score"] = score
        raw.loc[selected, "semantic_override"] = reason
    negative_sign_defect = raw.sentiment_label.eq("negative") & raw.sentiment_score.ge(0)
    positive_sign_defect = raw.sentiment_label.eq("positive") & raw.sentiment_score.le(0)
    raw.loc[negative_sign_defect, "sentiment_score"] = -raw.loc[negative_sign_defect, "sentiment_score"].abs()
    raw.loc[positive_sign_defect, "sentiment_score"] = raw.loc[positive_sign_defect, "sentiment_score"].abs()
    raw.loc[raw.sentiment_label.eq("neutral"), "sentiment_score"] = 0.0
    raw.loc[raw.sentiment_label.eq("mixed"), "sentiment_score"] = 0.0
    raw.loc[raw.sentiment_label.eq("not_applicable"), "sentiment_score"] = np.nan
    raw["score_normalization"] = np.select(
        [negative_sign_defect | positive_sign_defect, raw.sentiment_label.eq("mixed")],
        ["label_sign_normalized_from_raw_magnitude", "mixed_valence_normalized_to_zero"], default="none",
    )
    raw["semantic_status"] = np.where(raw.sentiment_label.eq("not_applicable"), "sentiment_not_applicable_importance_classified", "classified")
    raw["model"] = "gpt-5-mini"
    raw["prompt_version"] = "news_quality_v3_semantic_batch_v1"
    raw["validated_at"] = datetime.now(timezone.utc)

    failures: list[str] = []
    if not raw.importance.between(0, 1).all(): failures.append("importance_range")
    if not raw.confidence.between(0, 1).all(): failures.append("confidence_range")
    if not raw.loc[raw.sentiment_label.eq("positive"), "sentiment_score"].gt(0).all(): failures.append("positive_score_sign")
    if not raw.loc[raw.sentiment_label.eq("negative"), "sentiment_score"].lt(0).all(): failures.append("negative_score_sign")
    if not raw.loc[raw.sentiment_label.eq("neutral"), "sentiment_score"].eq(0).all(): failures.append("neutral_score_zero")
    if not raw.loc[raw.sentiment_label.eq("mixed"), "sentiment_score"].eq(0).all(): failures.append("mixed_score_zero")
    if not raw.loc[raw.sentiment_label.eq("not_applicable"), "sentiment_score"].isna().all(): failures.append("not_applicable_null")
    if ((raw.record_type.eq("news_article")) & raw.sentiment_label.eq("not_applicable")).any(): failures.append("news_sentiment_not_applicable")
    if raw.rationale.fillna("").str.split().map(len).gt(20).any(): failures.append("rationale_length")
    if raw[["importance", "confidence", "rationale", "sentiment_label"]].isna().any().any(): failures.append("required_null")
    if failures:
        raise RuntimeError("semantic validation failed: " + ",".join(failures))

    raw.to_parquet(BATCH / "semantic_v3_results_validated.parquet", index=False)
    old = raw[raw.dataset_scope.eq("existing_gap")].copy()
    old["sentiment"] = old.sentiment_label.mask(old.sentiment_label.eq("not_applicable"))
    old[["event_id", "sentiment", "sentiment_score", "importance", "confidence", "rationale", "semantic_status", "model", "prompt_version", "raw_sentiment_label", "raw_sentiment_score", "score_normalization", "semantic_override"]].to_parquet(
        DATA / "existing_semantic_staging.parquet", index=False
    )

    new = raw[raw.dataset_scope.eq("new_candidate")].set_index("event_id")
    production = pd.read_parquet(DATA / "production_rows_staging.parquet").copy()
    if set(production.event_id) != set(new.index):
        raise RuntimeError("candidate semantic staging identity mismatch")
    production["sentiment"] = production.event_id.map(new.sentiment_label).mask(lambda values: values.eq("not_applicable"))
    production["sentiment_score"] = production.event_id.map(new.sentiment_score)
    production["importance"] = production.event_id.map(new.importance)
    production["ai_schema_version"] = "news_quality_v3_semantic_v1"
    production["ai_prompt_version"] = "news_quality_v3_semantic_batch_v1"
    production["ai_original_scale"] = "sentiment -1..1; importance 0..1"
    production.to_parquet(DATA / "production_rows_staging.parquet", index=False)

    # Deterministic 200-row audit sample: both scopes, every label, extremes, and low confidence.
    selected = []
    for _, part in raw.groupby(["dataset_scope", "sentiment_label"]):
        selected.append(part.sample(min(12, len(part)), random_state=SEED))
    selected.extend([raw[raw.semantic_override.ne("none")], raw.nsmallest(30, "confidence"), raw.nlargest(20, "importance"), raw.nsmallest(20, "importance")])
    sample = pd.concat(selected).drop_duplicates("event_id")
    if len(sample) < 200:
        remaining = raw[~raw.event_id.isin(sample.event_id)].sample(200 - len(sample), random_state=SEED)
        sample = pd.concat([sample, remaining])
    sample = sample.head(200).copy()
    sample["automated_validation"] = "PASS"
    sample["recommended_action"] = np.where(sample.confidence.lt(0.5), "REVIEW_LOW_CONFIDENCE", "ACCEPT")
    sample["user_decision"] = ""
    sample[["event_id", "dataset_scope", "title", "source", "record_type", "raw_sentiment_label", "raw_sentiment_score", "sentiment_label", "sentiment_score", "importance", "confidence", "rationale", "score_normalization", "semantic_override", "automated_validation", "recommended_action", "user_decision"]].to_csv(
        REPORTS / "SEMANTIC_V3_QA_SAMPLE_200.csv", index=False
    )

    by_scope = raw.groupby("dataset_scope").agg(
        rows=("event_id", "size"), importance_mean=("importance", "mean"), confidence_mean=("confidence", "mean")
    ).reset_index().to_dict("records")
    summary = {
        "status": "PASS",
        "rows": len(raw),
        "existing_gaps_recovered": len(old),
        "new_candidates_classified": len(new),
        "raw_negative_sign_defects": int(negative_sign_defect.sum()),
        "raw_positive_sign_defects": int(positive_sign_defect.sum()),
        "deterministic_score_normalizations": int((negative_sign_defect | positive_sign_defect | raw.sentiment_label.eq("mixed")).sum()),
        "curated_news_label_overrides": len(curated_news),
        "remaining_validation_failures": 0,
        "not_applicable": int(raw.sentiment_label.eq("not_applicable").sum()),
        "low_confidence_below_0_5": int(raw.confidence.lt(0.5).sum()),
        "qa_sample_rows": len(sample),
        "sentiment_distribution": raw.sentiment_label.value_counts().to_dict(),
        "by_scope": by_scope,
        "production_updated": False,
    }
    (REPORTS / "SEMANTIC_V3_VALIDATION.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
