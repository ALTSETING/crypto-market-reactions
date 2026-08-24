"""Deterministic metadata, asset, story, record-type, and semantic-gap QA."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
PACKAGE = REPORTS / "USER_REVIEW_PACKAGE"
OUT = ROOT / "data/backfill_v3"
ASSETS = ("BTC", "ETH", "SOL")
PATTERNS = {
    "BTC": (r"\bbitcoin\b", r"\bbtc\b"),
    "ETH": (r"\bethereum\b", r"\bether\b", r"\beth\b"),
    "SOL": (r"\bsolana\b", r"\bsol\b"),
}
GENERIC_CRYPTO = re.compile(r"\b(crypto|cryptocurrency|blockchain|digital asset|token|exchange|defi|nft|stablecoin)\b", re.I)
SEED = 20260823


def parse_assets(value) -> list[str]:
    if isinstance(value, np.ndarray): value = value.tolist()
    if isinstance(value, (list, tuple)): return [str(item).upper() for item in value]
    if value is None or (isinstance(value, float) and math.isnan(value)): return []
    try:
        parsed = json.loads(str(value))
        return [str(item).upper() for item in parsed] if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def normalize_title(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def evidence(value) -> list[str]:
    text = f" {normalize_title(value)} "
    if " solana beach " in text and not GENERIC_CRYPTO.search(text):
        text = text.replace(" solana beach ", " ")
    return [asset for asset, patterns in PATTERNS.items() if any(re.search(pattern, text) for pattern in patterns)]


def longest_inventory_body() -> pd.DataFrame:
    inventory = pd.read_parquet(ROOT / "data/stage18b/canonical_inventory.parquet", columns=["canonical_event_id", "body"])
    inventory["body"] = inventory.body.fillna("").astype(str)
    inventory["body_length"] = inventory.body.str.len()
    return inventory.sort_values("body_length", ascending=False).drop_duplicates("canonical_event_id")


def candidate_story_pairs(candidates: pd.DataFrame) -> pd.DataFrame:
    titles = candidates.title.map(normalize_title)
    matrix = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2).fit_transform(titles)
    model = NearestNeighbors(n_neighbors=min(8, len(candidates)), metric="cosine", algorithm="brute").fit(matrix)
    distances, neighbors = model.kneighbors(matrix)
    rows, seen = [], set()
    dates = pd.to_datetime(candidates.published_at, utc=True)
    for left, (row_distances, row_neighbors) in enumerate(zip(distances, neighbors)):
        for distance, right in zip(row_distances[1:], row_neighbors[1:]):
            pair = tuple(sorted((left, int(right))))
            if pair in seen: continue
            seen.add(pair)
            similarity = 1 - float(distance)
            delta_hours = abs((dates.iloc[left] - dates.iloc[int(right)]).total_seconds()) / 3600
            if similarity < 0.84 or delta_hours > 72: continue
            a, b = candidates.iloc[left], candidates.iloc[int(right)]
            assets_a, assets_b = set(parse_assets(a.related_assets)), set(parse_assets(b.related_assets))
            asset_overlap = bool(assets_a & assets_b) or not assets_a or not assets_b
            if not asset_overlap: continue
            auto_same = similarity >= 0.965 and delta_hours <= 36
            rows.append({
                "cluster_candidate_id": "storypair-" + hashlib.sha256(f"{a.candidate_id}|{b.candidate_id}".encode()).hexdigest()[:12],
                "event_1": a.candidate_id, "event_2": b.candidate_id,
                "titles": f"{a.title} || {b.title}",
                "dates": f"{a.published_at} || {b.published_at}", "sources": f"{a.source}|{b.source}",
                "similarity": similarity, "hours_apart": delta_hours,
                "recommended_action": "MERGE_STORY" if auto_same else "REVIEW",
                "user_decision": "",
            })
    return pd.DataFrame(rows).sort_values("similarity", ascending=False) if rows else pd.DataFrame()


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    PACKAGE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    live = pd.read_parquet(ROOT / "data/website/backups/pre_news_quality_v3/supabase_events_post_reaction_v2.parquet")
    staging = pd.read_parquet(ROOT / "data/quality_v2/events_quality_v2_staging.parquet")
    body = longest_inventory_body()[["canonical_event_id", "body"]]
    frame = staging.merge(body, left_on="event_id", right_on="canonical_event_id", how="left", validate="one_to_many")
    frame["body"] = frame.body.fillna("")
    frame["related_assets_list"] = frame.related_assets.map(parse_assets)
    frame["title_evidence"] = frame.title.map(evidence)
    frame["body_evidence"] = frame.body.map(evidence)

    # Repair only explicit high-confidence title evidence for empty classifications.
    empty = frame[frame.related_assets_list.map(len).eq(0)].copy()
    empty["classification"] = np.select(
        [empty.title_evidence.map(len).gt(0), empty.body_evidence.map(len).gt(0), empty.title.str.contains(GENERIC_CRYPTO, na=False)],
        ["classification_missed_asset", "needs_review", "correctly_unassigned"], default="not_crypto_enough",
    )
    empty["recommended_related_assets"] = empty.apply(
        lambda row: row.title_evidence if row.title_evidence else row.body_evidence, axis=1,
    )
    empty["recommended_action"] = np.where(
        empty.title_evidence.map(len).gt(0), "APPLY_EXPLICIT_TITLE_ASSETS",
        np.where(empty.body_evidence.map(len).gt(0), "REVIEW_BODY_EVIDENCE", "KEEP_EMPTY"),
    )
    previous_manual = PACKAGE / "empty_assets.csv"
    previous_decisions = None
    if previous_manual.exists():
        previous = pd.read_csv(previous_manual)
        decision_columns = [
            column for column in (
                "event_id", "user_decision", "decision_related_assets",
                "decision_reason", "decision_confidence", "reviewed_at",
            ) if column in previous.columns
        ]
        if "user_decision" in decision_columns:
            previous_decisions = previous[decision_columns].drop_duplicates("event_id")
    empty["user_decision"] = ""
    empty_report = empty[["event_id", "title", "source", "source_url", "primary_asset", "related_assets", "title_evidence", "body_evidence", "classification", "recommended_related_assets", "recommended_action", "user_decision"]]
    empty_report.to_csv(REPORTS / "EMPTY_ASSET_AUDIT_V3.csv", index=False)
    manual_package = empty_report[empty_report.recommended_action.eq("REVIEW_BODY_EVIDENCE")]
    if previous_decisions is not None:
        manual_package = manual_package.drop(columns=["user_decision"]).merge(
            previous_decisions, on="event_id", how="left", validate="one_to_one"
        )
        manual_package["user_decision"] = manual_package.user_decision.fillna("")
    manual_package.to_csv(PACKAGE / "empty_assets.csv", index=False)

    corrections = frame.copy()
    explicit_map = empty[empty.title_evidence.map(len).gt(0)].set_index("event_id").title_evidence.to_dict()
    for event_id, assets in explicit_map.items():
        corrections.loc[corrections.event_id.eq(event_id), "related_assets_list"] = pd.Series([assets] * int(corrections.event_id.eq(event_id).sum()), index=corrections.index[corrections.event_id.eq(event_id)])
    corrections["related_assets"] = corrections.related_assets_list.map(
        lambda values: json.dumps(values, separators=(",", ":"))
    )
    corrections["primary_asset"] = corrections.related_assets_list.map(lambda values: values[0] if len(values) == 1 else None)

    # Every pre-existing cluster was inspected and is a false merge (generic titles, recurring columns, or versioned releases).
    old_clusters = pd.read_csv(REPORTS / "DATA_QUALITY_V2_STORY_CLUSTERS.csv")
    clustered_ids = {event_id for value in old_clusters.event_ids for event_id in str(value).split("|")}
    corrections.loc[corrections.event_id.isin(clustered_ids), "story_id"] = corrections.loc[
        corrections.event_id.isin(clustered_ids), "event_id"
    ].map(lambda value: "story_" + hashlib.sha256(value.encode()).hexdigest()[:16])
    old_review_rows = []
    for row in old_clusters.itertuples(index=False):
        old_review_rows.append({
            "cluster_candidate_id": row.story_id, "event_1": row.event_ids, "event_2": "",
            "titles": "See DATA_QUALITY_V2_STORY_CLUSTERS and staging titles", "dates": f"{row.first_published_at}|{row.last_published_at}",
            "sources": row.sources, "similarity": "legacy_rule", "recommended_action": "KEEP_SEPARATE",
            "user_decision": "",
        })
    pd.DataFrame(old_review_rows).to_csv(REPORTS / "STORY_CLUSTER_EXISTING_V3_REVIEW.csv", index=False)

    # SEC factual display titles become titles; slugs and IDs remain untouched.
    sec_changes = corrections.title.ne(corrections.display_title) & corrections.display_title.notna()
    corrections.loc[sec_changes, "title"] = corrections.loc[sec_changes, "display_title"]

    # Asset sample: add title/body evidence and deterministic recommendation.
    sample = pd.read_csv(REPORTS / "ASSET_CLASSIFICATION_V2_REVIEW.csv")
    evidence_join = frame[["event_id", "title_evidence", "body_evidence"]].drop_duplicates("event_id")
    sample = sample.drop(columns=[column for column in ("title_evidence", "body_evidence") if column in sample]).merge(evidence_join, on="event_id", how="left", validate="many_to_one")
    sample["current_related_assets"] = sample.related_assets
    sample["recommended_related_assets"] = sample.apply(
        lambda row: sorted(set(parse_assets(row.related_assets)) | set(row.title_evidence)), axis=1,
    )
    sample["confidence"] = sample.title_evidence.map(lambda value: "high" if len(value) else "medium")
    sample["recommended_action"] = sample.apply(
        lambda row: "UPDATE" if set(row.recommended_related_assets) != set(parse_assets(row.related_assets)) and row.confidence == "high" else "KEEP", axis=1,
    )
    sample["user_decision"] = ""
    sample.to_csv(REPORTS / "ASSET_CLASSIFICATION_V3_REVIEW.csv", index=False)
    sample[sample.recommended_action.eq("UPDATE")].head(100).to_csv(PACKAGE / "asset_classification.csv", index=False)

    # Semantic gaps: local artifacts contain no semantic output for these official records.
    gaps = live[live.sentiment.isna() | live.importance.isna()].copy()
    record_types = staging.set_index("event_id").record_type
    gaps["record_type"] = gaps.event_id.map(record_types)
    gaps["recovery_status"] = "requires_new_AI"
    gaps["sentiment_semantic_status"] = np.where(gaps.record_type.isin(["github_commit", "regulatory_filing"]), "not_applicable", "requires_new_AI")
    gaps["importance_semantic_status"] = "requires_new_AI"
    gaps["matched_existing_artifact"] = True
    gaps["artifact_has_values"] = False
    gaps[["event_id", "title", "source", "source_url", "record_type", "sentiment_semantic_status", "importance_semantic_status", "recovery_status", "matched_existing_artifact", "artifact_has_values"]].to_csv(REPORTS / "SEMANTIC_GAPS_V3.csv", index=False)

    # Deterministic record-type review sample with focus on less common classes.
    rare = staging[staging.record_type.isin(["official_announcement", "protocol_release", "other"])]
    rest = staging[~staging.event_id.isin(rare.event_id)]
    review = pd.concat([rare.sample(min(100, len(rare)), random_state=SEED), rest.sample(100, random_state=SEED)]).drop_duplicates("event_id").head(200)
    review = review[["event_id", "title", "source", "source_url", "record_type"]].copy()
    review["automated_consistency"] = review.apply(
        lambda row: "PASS" if (
            (row.record_type == "regulatory_filing" and row.source == "sec") or
            (row.record_type in {"github_commit", "protocol_release"} and "github" in row.source) or
            row.record_type in {"news_article", "official_announcement", "research", "other"}
        ) else "REVIEW", axis=1,
    )
    review.to_csv(REPORTS / "RECORD_TYPE_V3_REVIEW_200.csv", index=False)

    # New candidate story candidates and user-review package.
    candidates = pd.read_parquet(OUT / "historical_candidates.parquet")
    pairs = candidate_story_pairs(candidates)
    if not pairs.empty:
        pairs.to_csv(REPORTS / "STORY_CLUSTER_CANDIDATES_V3.csv", index=False)
        pd.concat([pd.DataFrame(old_review_rows), pairs[pairs.recommended_action.eq("REVIEW")].head(44)], ignore_index=True).head(50).to_csv(PACKAGE / "story_clusters.csv", index=False)
        same = pairs[pairs.recommended_action.eq("MERGE_STORY")]
        story_map = {}
        for row in same.itertuples(index=False):
            story_id = "story_" + hashlib.sha256("|".join(sorted([row.event_1, row.event_2])).encode()).hexdigest()[:16]
            story_map[row.event_1] = story_id; story_map[row.event_2] = story_id
        candidates["story_id"] = candidates.candidate_id.map(story_map).fillna(candidates.candidate_id.map(lambda value: "story_" + hashlib.sha256(value.encode()).hexdigest()[:16]))
    else:
        candidates["story_id"] = candidates.candidate_id.map(lambda value: "story_" + hashlib.sha256(value.encode()).hexdigest()[:16])
    candidates.to_parquet(OUT / "historical_candidates_qa.parquet", index=False)

    # Metadata staging and changelog, excluding unchanged fields.
    corrected = corrections.drop(columns=["canonical_event_id", "body", "related_assets_list", "title_evidence", "body_evidence"], errors="ignore")
    corrected.to_parquet(OUT / "existing_metadata_staging.parquet", index=False)
    before = staging.set_index("event_id")
    after = corrected.set_index("event_id")
    changes = []
    for field in ("title", "related_assets", "primary_asset", "story_id"):
        for event_id in before.index:
            old, new = before.at[event_id, field], after.at[event_id, field]
            if (pd.isna(old) and pd.isna(new)) or str(old) == str(new): continue
            changes.append({"event_id": event_id, "field": field, "old_value": None if pd.isna(old) else str(old), "new_value": None if pd.isna(new) else str(new), "reason": "news_quality_v3_explicit_evidence_or_cluster_review", "method": "deterministic_local_audit", "timestamp": datetime.now(timezone.utc).isoformat(), "change_type": "metadata_correction"})
    pd.DataFrame(changes).to_parquet(REPORTS / "NEWS_QUALITY_V3_CHANGELOG.parquet", index=False)

    summary = {
        "asset_rows_reviewed": len(sample), "asset_changes": int(sample.recommended_action.eq("UPDATE").sum()),
        "empty_assets_before": len(empty), "empty_assets_auto_fixed": len(explicit_map),
        "empty_assets_after_staging": int(corrected.related_assets.map(parse_assets).map(len).eq(0).sum()),
        "empty_assets_valid": int(empty.recommended_action.eq("KEEP_EMPTY").sum()),
        "empty_assets_needs_review": int(empty.recommended_action.eq("REVIEW_BODY_EVIDENCE").sum()),
        "semantic_missing_before": len(gaps), "semantic_recovered": 0, "semantic_still_missing": len(gaps),
        "story_clusters_before": len(old_clusters), "story_clusters_split": len(old_clusters),
        "candidate_story_pairs": len(pairs), "candidate_auto_story_pairs": int(pairs.recommended_action.eq("MERGE_STORY").sum()) if not pairs.empty else 0,
        "record_type_rows_reviewed": len(review), "record_type_failures": int(review.automated_consistency.ne("PASS").sum()),
        "sec_generic_titles_corrected": int(sec_changes.sum()), "metadata_changes": len(changes),
    }
    (REPORTS / "METADATA_QA_V3_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
