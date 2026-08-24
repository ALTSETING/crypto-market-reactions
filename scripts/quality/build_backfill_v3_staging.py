"""Build production-shaped News Quality V3 rows without touching production."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/backfill_v3"
REPORTS = ROOT / "reports"
HORIZONS = ("1m", "5m", "15m", "1h", "4h", "24h")
ASSETS = ("BTC", "ETH", "SOL")


def slugify(title: str, candidate_id: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().casefold()
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")[:80] or "historical-event"
    return f"{stem}-{candidate_id.removeprefix('bf3-')[:10]}"


def json_assets(value: object) -> list[str]:
    if isinstance(value, str):
        return list(json.loads(value))
    return list(value)


def main() -> int:
    candidates = pd.read_parquet(DATA / "historical_candidates_qa.parquet")
    candidates = candidates[candidates.quality_status.eq("accepted")].copy()
    reactions = pd.read_parquet(DATA / "historical_candidate_reactions_v2.parquet")
    existing = pd.read_parquet(
        ROOT / "data/website/backups/pre_news_quality_v3/supabase_events_post_reaction_v2.parquet"
    )
    now = datetime.now(timezone.utc)
    rows = []
    reaction_index = reactions.set_index(["event_id", "asset"])
    for candidate in candidates.itertuples(index=False):
        related = json_assets(candidate.related_assets)
        row: dict[str, object] = {
            "event_id": candidate.candidate_id,
            "slug": slugify(candidate.title, candidate.candidate_id),
            "title": candidate.title,
            "published_at": candidate.published_at,
            "source": candidate.source,
            "source_url": candidate.source_url,
            "primary_asset": None if pd.isna(candidate.primary_asset) else candidate.primary_asset,
            "related_assets": related,
            "category": candidate.category,
            "sentiment": None,
            "sentiment_score": None,
            "importance": None,
            "ai_schema_version": "news_quality_v3_not_scored",
            "ai_prompt_version": None,
            "ai_original_scale": "not_scored",
            "archive_dataset_source": "C",
            "archive_member_id": f"news_quality_v3:{candidate.candidate_id}",
            "reaction_methodology": "reaction_v2_next_full_minute_open_to_open",
            "reaction_value_unit": "percent",
            "record_type": candidate.record_type,
            "story_id": candidate.story_id,
            "captured_title": candidate.title,
            "current_source_title": candidate.title,
            "display_title": candidate.title,
            "source_type": "publisher",
            "source_name": candidate.source,
            "capture_method": candidate.capture_method,
            "publication_time_source": "publisher_page_jsonld",
            "publication_time_confidence": "high",
            "publication_time_verified_at": now,
            "event_at": None,
            "event_time_source": None,
            "event_time_confidence": None,
            "primary_asset_confidence": "high" if len(related) == 1 else "not_assigned",
            "source_http_status": "verified_200",
            "source_final_url": candidate.source_url,
            "source_verified_at": now,
            "quality_status": "accepted",
            "is_public": True,
            "dataset_version": 3,
            "dataset_release": "2026-08-news-quality-v3",
            "created_at": now,
            "updated_at": now,
        }
        for asset in ASSETS:
            prefix = asset.casefold()
            value = reaction_index.loc[(candidate.candidate_id, asset)]
            for horizon in HORIZONS:
                row[f"{prefix}_{horizon}"] = None if pd.isna(value[horizon]) else float(value[horizon])
            row[f"{prefix}_reference_time"] = value.reference_time
            row[f"{prefix}_reference_latency_minutes"] = 0
            quality = {
                "verified_raw": "raw_verified_v2",
                "partial_verified_raw": "partial_raw_verified_v2",
                "missing": "missing_market_data",
            }[value.reaction_quality]
            row[f"{prefix}_reaction_quality"] = quality
            row[f"{prefix}_reaction_source"] = None if value.reaction_quality == "missing" else value.source
            reasons = {}
            for horizon in HORIZONS:
                if pd.isna(value[horizon]):
                    reasons[horizon] = (
                        "asset_not_available_yet"
                        if value.missing_reason == "before_listing_or_archive_unavailable"
                        else "missing_market_data"
                    )
            row[f"{prefix}_reaction_missing_reason"] = reasons or None
            available = [row[f"{prefix}_{horizon}"] for horizon in HORIZONS if row[f"{prefix}_{horizon}"] is not None]
            row[f"{prefix}_average_reaction"] = float(np.mean(available)) if available else None
        rows.append(row)
    staging = pd.DataFrame(rows)
    if staging.event_id.duplicated().any() or staging.slug.duplicated().any():
        raise RuntimeError("new event IDs/slugs are not unique")
    if set(staging.event_id) & set(existing.event_id) or set(staging.slug) & set(existing.slug):
        raise RuntimeError("new event identity collides with production")
    staging.to_parquet(DATA / "production_rows_staging.parquet", index=False)

    changelog_path = REPORTS / "NEWS_QUALITY_V3_CHANGELOG.parquet"
    changelog = pd.read_parquet(changelog_path)
    additions = pd.DataFrame({
        "event_id": staging.event_id,
        "field": "event",
        "old_value": None,
        "new_value": staging.title,
        "reason": "verified_historical_publisher_backfill",
        "method": "publisher_archive_plus_page_jsonld",
        "timestamp": now.isoformat(),
        "change_type": "historical_backfill_addition",
    })
    pd.concat([changelog, additions], ignore_index=True).to_parquet(changelog_path, index=False)
    payload = {
        "staged_rows": len(staging),
        "unique_event_ids": staging.event_id.nunique(),
        "unique_slugs": staging.slug.nunique(),
        "existing_identity_collisions": 0,
        "years": staging.assign(year=pd.to_datetime(staging.published_at, utc=True).dt.year).year.value_counts().sort_index().to_dict(),
        "empty_related_assets": int(staging.related_assets.map(len).eq(0).sum()),
        "unscored_semantics": int(staging.importance.isna().sum()),
    }
    (REPORTS / "BACKFILL_V3_STAGING_SUMMARY.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
