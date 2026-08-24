"""Deterministic Data Quality V2 audit and staging enrichment.

This module is deliberately read-only with respect to the canonical website
dataset and every database.  It writes reports and a versioned staging
artifact only; production cutover is a separate, explicit operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "data" / "website" / "events_mvp.parquet"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
STAGING = ROOT / "data" / "quality_v2"
ASSETS = ("BTC", "ETH", "SOL")
HORIZONS = ("1m", "5m", "15m", "1h", "4h", "24h")
GENERIC_TITLES = {"document", "untitled", "article", "news", "home", "page"}
RELEASE = "2026-08-data-quality-v2"
SEED = 20260823
INVENTORY = ROOT / "data" / "stage18b" / "canonical_inventory.parquet"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=json_default) + "\n",
        encoding="utf-8",
    )


def parse_assets(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    elif value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    else:
        try:
            items = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return []
    if not isinstance(items, list):
        return []
    return [str(item).upper() for item in items]


def normalize_title(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"https?://\S+", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_url(value: Any) -> str | None:
    text = str(value or "").strip()
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.netloc.casefold()
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    return urlunparse((parsed.scheme.casefold(), host, path, "", parsed.query, ""))


def record_type(source: Any, url: Any, title: Any) -> str:
    source_text = str(source or "").casefold()
    host = (urlparse(str(url or "")).hostname or "").casefold()
    title_text = str(title or "").casefold()
    combined = " ".join((source_text, host, title_text))
    if "sec.gov" in host or source_text == "sec" or " sec filing" in combined:
        return "regulatory_filing"
    if "github" in combined:
        if "/releases/" in str(url or "").casefold() or " release " in f" {title_text} ":
            return "protocol_release"
        return "github_commit"
    if any(token in combined for token in ("foundation", "official", "announcement", "blog.ethereum", "solana.com/news")):
        return "official_announcement"
    if any(token in combined for token in ("research", "paper", "arxiv")):
        return "research"
    if any(token in combined for token in ("coindesk", "cointelegraph", "decrypt", "cryptoslate", "blockworks")):
        return "news_article"
    return "other"


def source_type(source: Any, url: Any, assigned_record_type: str) -> str:
    if assigned_record_type in {"regulatory_filing", "github_commit", "protocol_release", "official_announcement"}:
        return "primary"
    host = (urlparse(str(url or "")).hostname or "").casefold()
    if host.endswith(".gov"):
        return "primary"
    if assigned_record_type == "news_article":
        return "publisher"
    return "other"


def sec_display_titles(events: pd.DataFrame) -> dict[str, str]:
    if not INVENTORY.exists():
        return {}
    generic_ids = set(events.loc[
        events.source.astype(str).str.casefold().eq("sec")
        & events.title.map(normalize_title).isin(GENERIC_TITLES),
        "event_id",
    ].astype(str))
    if not generic_ids:
        return {}
    inventory = pd.read_parquet(INVENTORY, columns=["canonical_event_id", "body"])
    inventory = inventory[inventory.canonical_event_id.astype(str).isin(generic_ids)].copy()
    inventory["body"] = inventory.body.fillna("").astype(str)
    inventory["body_length"] = inventory.body.str.len()
    inventory = inventory.sort_values("body_length", ascending=False).drop_duplicates("canonical_event_id")
    result: dict[str, str] = {}
    for row in inventory.itertuples(index=False):
        form_match = re.search(r"(?:^|\bFORM\s+)(8-K/A|10-[KQ](?:/A)?|S-1(?:/A)?|DRS(?:/A)?|424B[34]|253G2|CORRESP|DOSLTR)\b", row.body, re.I)
        form = form_match.group(1).upper() if form_match else None
        issuer = None
        if re.search(r"\bCoinbase Global,?\s+Inc\.?\b", row.body, re.I):
            issuer = "Coinbase Global"
        elif re.search(r"\bYouNow,?\s+Inc\.?\b", row.body, re.I):
            issuer = "YouNow"
        if form and issuer:
            result[str(row.canonical_event_id)] = f"{issuer} {form} Filing"
        elif form:
            result[str(row.canonical_event_id)] = f"SEC Form {form} Filing"
    return result


def asset_evidence(title: Any, asset: str) -> bool:
    text = f" {normalize_title(title)} "
    if asset == "SOL" and " solana beach " in text and not re.search(
        r"\b(crypto|blockchain|token|validator|network|sol\b)", text
    ):
        return False
    rules = {
        "BTC": (r"\bbitcoin\b", r"\bbtc\b"),
        "ETH": (r"\bethereum\b", r"\bether\b", r"\beth\b"),
        "SOL": (r"\bsolana\b", r"\bsol\b"),
    }
    return any(re.search(pattern, text) for pattern in rules[asset])


def build_story_ids(events: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Conservative grouping: exact normalized URL/title plus very close titles.

    Near-title links require a 48-hour publication window and cosine similarity
    >= 0.965.  Articles are grouped, never removed.
    """

    parent = list(range(len(events)))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for column in ("normalized_url", "normalized_title"):
        for _, indexes in events[events[column].notna() & events[column].ne("")].groupby(column).groups.items():
            indexes = list(indexes)
            for item in indexes[1:]:
                union(int(indexes[0]), int(item))

    titles = events.normalized_title.fillna("")
    usable = titles.str.len().ge(20)
    if usable.sum() >= 2:
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2)
        matrix = vectorizer.fit_transform(titles[usable])
        neighbors = NearestNeighbors(n_neighbors=min(4, matrix.shape[0]), metric="cosine", algorithm="brute")
        distances, indices = neighbors.fit(matrix).kneighbors(matrix)
        positions = np.flatnonzero(usable.to_numpy())
        for local_left, (row_distances, row_indices) in enumerate(zip(distances, indices)):
            left = int(positions[local_left])
            for distance, local_right in zip(row_distances[1:], row_indices[1:]):
                similarity = 1.0 - float(distance)
                if similarity < 0.965:
                    continue
                right = int(positions[int(local_right)])
                delta = abs(events.at[left, "published_at"] - events.at[right, "published_at"])
                if delta <= pd.Timedelta(hours=48):
                    union(left, right)

    groups: dict[int, list[int]] = {}
    for index in range(len(events)):
        groups.setdefault(find(index), []).append(index)
    story_by_index: dict[int, str] = {}
    rows: list[dict[str, Any]] = []
    for members in groups.values():
        event_ids = sorted(str(events.at[item, "event_id"]) for item in members)
        story = "story_" + hashlib.sha256("|".join(event_ids).encode()).hexdigest()[:16]
        for item in members:
            story_by_index[item] = story
        if len(members) > 1:
            rows.append({
                "story_id": story,
                "article_count": len(members),
                "event_ids": "|".join(event_ids),
                "sources": "|".join(sorted(set(str(events.at[item, "source"]) for item in members))),
                "first_published_at": min(events.at[item, "published_at"] for item in members),
                "last_published_at": max(events.at[item, "published_at"] for item in members),
            })
    clusters = pd.DataFrame(rows).sort_values(["article_count", "story_id"], ascending=[False, True]) if rows else pd.DataFrame(
        columns=["story_id", "article_count", "event_ids", "sources", "first_published_at", "last_published_at"]
    )
    return pd.Series(story_by_index).sort_index(), clusters


def stratified_asset_review(events: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    frames: list[pd.DataFrame] = []
    for label, count in (("BTC", 100), ("ETH", 100), ("SOL", 100), ("empty", 50), ("multi", 50)):
        if label in ASSETS:
            pool = events[events.related_assets_list.map(lambda values: label in values)]
        elif label == "empty":
            pool = events[events.related_assets_list.map(len).eq(0)]
        else:
            pool = events[events.related_assets_list.map(len).gt(1)]
        if pool.empty:
            continue
        take = min(count, len(pool))
        selected = pool.iloc[rng.choice(len(pool), size=take, replace=False)].copy()
        selected["review_stratum"] = label
        frames.append(selected)
    if not frames:
        return pd.DataFrame()
    sample = pd.concat(frames, ignore_index=True)
    sample["title_btc_evidence"] = sample.title.map(lambda value: asset_evidence(value, "BTC"))
    sample["title_eth_evidence"] = sample.title.map(lambda value: asset_evidence(value, "ETH"))
    sample["title_sol_evidence"] = sample.title.map(lambda value: asset_evidence(value, "SOL"))
    sample["automated_assessment"] = sample.apply(
        lambda row: "title_supported" if any(
            asset_evidence(row.title, asset) for asset in row.related_assets_list
        ) else ("empty_assignment" if not row.related_assets_list else "needs_source_review"),
        axis=1,
    )
    sample["manual_review_status"] = "pending"
    return sample[[
        "event_id", "review_stratum", "title", "source", "source_url", "published_at",
        "primary_asset", "related_assets", "title_btc_evidence", "title_eth_evidence",
        "title_sol_evidence", "automated_assessment", "manual_review_status",
    ]]


def audit(dataset: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    events = pd.read_parquet(dataset).reset_index(drop=True)
    events["published_at"] = pd.to_datetime(events.published_at, utc=True, errors="coerce")
    events["normalized_title"] = events.title.map(normalize_title)
    events["normalized_url"] = events.source_url.map(normalize_url)
    events["related_assets_list"] = events.related_assets.map(parse_assets)
    events["record_type"] = [record_type(row.source, row.source_url, row.title) for row in events.itertuples()]
    events["source_type"] = [source_type(row.source, row.source_url, row.record_type) for row in events.itertuples()]
    events["source_name"] = events.source
    events["capture_method"] = np.where(events.record_type.isin(["github_commit", "protocol_release"]), "official_api_or_archive", "historical_archive")
    events["dataset_release"] = RELEASE
    events["dataset_version"] = 2
    events["captured_title"] = events.title
    events["display_title"] = events.title
    for event_id, display_title in sec_display_titles(events).items():
        events.loc[events.event_id.astype(str).eq(event_id), "display_title"] = display_title
    events["current_source_title"] = pd.NA
    events["publication_time_source"] = "legacy_captured_metadata"
    events["publication_time_confidence"] = "unverified"
    events["publication_time_verified_at"] = pd.Series(
        pd.array([pd.NaT] * len(events), dtype="datetime64[ns, UTC]")
    )
    events["event_at"] = pd.Series(
        pd.array([pd.NaT] * len(events), dtype="datetime64[ns, UTC]")
    )
    events["event_time_source"] = pd.NA
    events["event_time_confidence"] = pd.NA
    official_same_time = events.record_type.isin(["github_commit", "protocol_release", "official_announcement"])
    events.loc[official_same_time, "event_at"] = events.loc[official_same_time, "published_at"]
    events.loc[official_same_time, "event_time_source"] = "publication_or_commit_metadata"
    events.loc[official_same_time, "event_time_confidence"] = "medium"
    events["primary_asset_confidence"] = np.select(
        [events.related_assets_list.map(len).eq(1) & events.primary_asset.notna(), events.primary_asset.notna()],
        ["high", "medium"],
        default="not_assigned",
    )

    story_ids, clusters = build_story_ids(events)
    events["story_id"] = story_ids.values

    now = pd.Timestamp.now(tz="UTC")
    reaction_columns = [f"{asset.lower()}_{horizon}" for asset in ASSETS for horizon in HORIZONS]
    numeric = events[reaction_columns].apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy(dtype=float)
    invalid_url = events.normalized_url.isna()
    invalid_asset_values = events.related_assets_list.map(lambda items: any(item not in ASSETS for item in items))
    primary_not_related = events.apply(
        lambda row: bool(pd.notna(row.primary_asset) and row.primary_asset not in row.related_assets_list), axis=1
    )
    generic_titles = events.normalized_title.isin(GENERIC_TITLES)
    blank_titles = events.normalized_title.eq("")
    short_titles = events.normalized_title.str.len().between(1, 9)
    long_titles = events.title.fillna("").str.len().gt(300)
    future_timestamps = events.published_at.gt(now)
    invalid_timestamps = events.published_at.isna()
    duplicate_event_id = events.event_id.duplicated(keep=False)
    duplicate_slug = events.slug.duplicated(keep=False) if "slug" in events else pd.Series(False, index=events.index)
    duplicate_url = events.normalized_url.notna() & events.normalized_url.duplicated(keep=False)
    duplicate_title = events.normalized_title.ne("") & events.normalized_title.duplicated(keep=False)
    nonfinite = int(np.isinf(values).sum())
    nan_cells = int(np.isnan(values).sum())
    impossible = int((values[np.isfinite(values)] <= -100).sum())
    extreme = int((np.abs(values[np.isfinite(values)]) > 50).sum())

    reference_issues: dict[str, Any] = {}
    for asset in ASSETS:
        prefix = asset.lower()
        ref = pd.to_datetime(events[f"{prefix}_reference_time"], utc=True, errors="coerce")
        has_reaction = events[[f"{prefix}_{h}" for h in HORIZONS]].notna().any(axis=1)
        reference_issues[asset] = {
            "reaction_rows": int(has_reaction.sum()),
            "missing_reference_time": int((has_reaction & ref.isna()).sum()),
            "reference_before_publication": int((has_reaction & ref.lt(events.published_at)).sum()),
            "latency_counts": {
                str(key): int(value)
                for key, value in events.loc[
                    has_reaction, f"{prefix}_reference_latency_minutes"
                ].value_counts(dropna=False).items()
            },
        }

    critical = invalid_timestamps | blank_titles | invalid_url | invalid_asset_values | primary_not_related
    review = generic_titles | short_titles | long_titles | duplicate_url | duplicate_title
    events["quality_status"] = np.select([critical, review], ["rejected", "needs_review"], default="accepted")
    events["is_public"] = events.quality_status.isin(["verified", "accepted"])

    years = events.assign(year=events.published_at.dt.year).groupby("year", dropna=False).size()
    months = events.assign(month=events.published_at.dt.strftime("%Y-%m")).groupby("month", dropna=False).size()
    sources = events.groupby("source", dropna=False).size().sort_values(ascending=False)
    categories = events.groupby("category", dropna=False).size().sort_values(ascending=False)
    record_types = events.groupby("record_type", dropna=False).size().sort_values(ascending=False)

    coverage_rows = []
    for year, part in events.assign(year=events.published_at.dt.year).groupby("year"):
        for asset in ASSETS:
            related = part.related_assets_list.map(lambda items: asset in items)
            full = part[[f"{asset.lower()}_{h}" for h in HORIZONS]].notna().all(axis=1)
            coverage_rows.append({
                "year": int(year), "asset": asset, "events": len(part),
                "related_events": int(related.sum()), "full_reaction_rows": int(full.sum()),
            })
    coverage = pd.DataFrame(coverage_rows)

    report = {
        "generated_at": now.isoformat(),
        "dataset": str(dataset.relative_to(ROOT)),
        "dataset_sha256": sha256_file(dataset),
        "events": len(events),
        "unique_event_id": int(events.event_id.nunique()),
        "unique_slug": int(events.slug.nunique()) if "slug" in events else None,
        "publication_min": events.published_at.min(),
        "publication_max": events.published_at.max(),
        "identity": {
            "duplicate_event_id_rows": int(duplicate_event_id.sum()),
            "duplicate_slug_rows": int(duplicate_slug.sum()),
            "duplicate_source_url_rows": int(duplicate_url.sum()),
            "duplicate_normalized_title_rows": int(duplicate_title.sum()),
            "malformed_source_url_rows": int(invalid_url.sum()),
            "invalid_timestamp_rows": int(invalid_timestamps.sum()),
            "future_timestamp_rows": int(future_timestamps.sum()),
            "blank_title_rows": int(blank_titles.sum()),
            "generic_title_rows": int(generic_titles.sum()),
            "short_title_rows": int(short_titles.sum()),
            "long_title_rows": int(long_titles.sum()),
        },
        "classification": {
            "empty_related_assets": int(events.related_assets_list.map(len).eq(0).sum()),
            "invalid_related_assets": int(invalid_asset_values.sum()),
            "primary_not_related": int(primary_not_related.sum()),
            "multi_asset": int(events.related_assets_list.map(len).gt(1).sum()),
            "primary_asset_null": int(events.primary_asset.isna().sum()),
        },
        "semantic": {
            "missing_category": int(events.category.isna().sum()),
            "missing_sentiment": int(events.sentiment.isna().sum()),
            "missing_importance": int(events.importance.isna().sum()),
            "missing_sentiment_score": int(events.sentiment_score.isna().sum()),
            "sentiment_score_outside_minus1_plus1": int(events.sentiment_score.dropna().abs().gt(1).sum()),
            "importance_outside_zero_one": int(((events.importance.dropna() < 0) | (events.importance.dropna() > 1)).sum()),
        },
        "market": {
            "missing_reaction_cells": nan_cells,
            "infinite_reaction_cells": nonfinite,
            "returns_lte_minus_100": impossible,
            "absolute_returns_gt_50": extreme,
            "reference_time": reference_issues,
            "methodology_counts": events.reaction_methodology.value_counts(dropna=False).astype(int).to_dict(),
        },
        "coverage": {
            "by_year": {str(int(key)): int(value) for key, value in years.items() if pd.notna(key)},
            "by_month": {str(key): int(value) for key, value in months.items()},
            "by_source": {str(key): int(value) for key, value in sources.items()},
            "by_asset": Counter(asset for items in events.related_assets_list for asset in items),
            "by_record_type": {str(key): int(value) for key, value in record_types.items()},
        },
        "categories": {str(key): int(value) for key, value in categories.items()},
        "quality_status": events.quality_status.value_counts().astype(int).to_dict(),
        "stories": {
            "unique_story_count": int(events.story_id.nunique()),
            "article_count": len(events),
            "multi_article_story_count": len(clusters),
            "articles_in_multi_article_stories": int(clusters.article_count.sum()) if len(clusters) else 0,
            "largest_cluster": int(clusters.article_count.max()) if len(clusters) else 1,
        },
    }
    return report, events, clusters


def write_outputs(report: dict[str, Any], events: pd.DataFrame, clusters: pd.DataFrame) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    write_json(REPORTS / "DATA_QUALITY_V2_BASELINE.json", report)
    coverage = report["coverage"]
    coverage_rows = []
    for year, count in coverage["by_year"].items():
        coverage_rows.append({"year": int(year), "events": count})
    pd.DataFrame(coverage_rows).to_csv(REPORTS / "DATA_QUALITY_V2_COVERAGE_BY_YEAR.csv", index=False)
    events.assign(year=events.published_at.dt.year).groupby(
        ["year", "source", "record_type"], dropna=False
    ).size().rename("events").reset_index().to_csv(REPORTS / "DATA_QUALITY_V2_COVERAGE_DETAIL.csv", index=False)
    clusters.to_csv(REPORTS / "DATA_QUALITY_V2_STORY_CLUSTERS.csv", index=False)
    review = stratified_asset_review(events)
    review.to_csv(REPORTS / "ASSET_CLASSIFICATION_V2_REVIEW.csv", index=False)

    outlier_rows = []
    for asset in ASSETS:
        for horizon in HORIZONS:
            column = f"{asset.lower()}_{horizon}"
            usable = events[events[column].notna()]
            for direction, part in (("positive", usable.nlargest(100, column)), ("negative", usable.nsmallest(100, column))):
                for row in part[["event_id", "title", "source", "source_url", "published_at", column]].itertuples(index=False):
                    outlier_rows.append({
                        "event_id": row.event_id, "asset": asset, "horizon": horizon,
                        "direction": direction, "reaction": getattr(row, column), "title": row.title,
                        "source": row.source, "source_url": row.source_url,
                        "published_at": row.published_at, "review_status": "pending",
                    })
    pd.DataFrame(outlier_rows).drop_duplicates(["event_id", "asset", "horizon"]).to_csv(
        REPORTS / "REACTION_OUTLIER_REVIEW.csv", index=False
    )

    sol = events[events.related_assets_list.map(lambda items: "SOL" in items)].copy()
    sol_columns = [f"sol_{h}" for h in HORIZONS]
    sol["full_sol_reactions"] = sol[sol_columns].notna().all(axis=1)
    sol["sol_gap_reason"] = np.select(
        [
            sol.published_at.lt(pd.Timestamp("2020-08-11", tz="UTC")),
            sol[sol_columns].isna().all(axis=1),
            sol[sol_columns].isna().any(axis=1),
        ],
        ["before_binance_solusdt_listing", "missing_derived_path_or_pipeline", "partial_missing_market_data"],
        default="complete",
    )
    sol[["event_id", "published_at", "title", "source", "full_sol_reactions", "sol_gap_reason", *sol_columns]].to_csv(
        REPORTS / "SOL_REACTION_GAP_AUDIT.csv", index=False
    )

    staging_drop = ["related_assets_list", "normalized_title", "normalized_url"]
    events.drop(columns=staging_drop).to_parquet(STAGING / "events_quality_v2_staging.parquet", index=False)
    added_fields = [
        "record_type", "source_type", "source_name", "capture_method", "dataset_release",
        "dataset_version", "captured_title", "display_title", "current_source_title",
        "publication_time_source", "publication_time_confidence", "publication_time_verified_at",
        "event_at", "event_time_source", "event_time_confidence", "primary_asset_confidence",
        "story_id", "quality_status", "is_public",
    ]
    changelog = pd.DataFrame(
        ({
            "event_id": row.event_id,
            "field": field,
            "old_value": None,
            "new_value": None if pd.isna(getattr(row, field)) else str(getattr(row, field)),
            "reason": "Data Quality V2 deterministic staging enrichment",
            "script_version": RELEASE,
            "timestamp": report["generated_at"],
        } for row in events.itertuples(index=False) for field in added_fields)
    )
    changelog.to_parquet(REPORTS / "DATA_QUALITY_V2_CHANGELOG.parquet", index=False)

    identity = report["identity"]
    semantic = report["semantic"]
    market = report["market"]
    lines = [
        "# Data Quality V2 baseline",
        "",
        f"Generated: `{report['generated_at']}` from `{report['dataset']}`.",
        "",
        "## Identity",
        "",
        f"- Events / unique IDs: **{report['events']:,} / {report['unique_event_id']:,}**.",
        f"- SHA-256: `{report['dataset_sha256']}`.",
        f"- Range: **{report['publication_min'].isoformat()}** to **{report['publication_max'].isoformat()}**.",
        f"- Duplicate URL rows: **{identity['duplicate_source_url_rows']:,}**; duplicate normalized-title rows: **{identity['duplicate_normalized_title_rows']:,}**.",
        f"- Malformed URLs: **{identity['malformed_source_url_rows']:,}**; generic titles: **{identity['generic_title_rows']:,}**.",
        "",
        "## Coverage by year",
        "",
        *[f"- {year}: **{count:,}**" for year, count in report["coverage"]["by_year"].items()],
        "",
        "## Semantic and market fields",
        "",
        f"- Missing category / sentiment / importance: **{semantic['missing_category']:,} / {semantic['missing_sentiment']:,} / {semantic['missing_importance']:,}**.",
        f"- Missing reaction cells: **{market['missing_reaction_cells']:,}**; infinite: **{market['infinite_reaction_cells']}**; <= -100%: **{market['returns_lte_minus_100']}**.",
        f"- Existing reaction methodologies: `{json.dumps(market['methodology_counts'], sort_keys=True)}`.",
        "",
        "## Conservative story grouping",
        "",
        f"- Articles / unique stories: **{report['events']:,} / {report['stories']['unique_story_count']:,}**.",
        f"- Multi-article stories: **{report['stories']['multi_article_story_count']:,}**; largest cluster: **{report['stories']['largest_cluster']}**.",
        "",
        "No canonical dataset or production database was modified. Derived fields are in the staging Parquet and remain subject to review.",
    ]
    (DOCS / "DATA_QUALITY_V2_BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    report, events, clusters = audit(args.dataset.resolve())
    write_outputs(report, events, clusters)
    print(json.dumps({
        "events": report["events"],
        "stories": report["stories"]["unique_story_count"],
        "quality_status": report["quality_status"],
        "baseline": "reports/DATA_QUALITY_V2_BASELINE.json",
        "staging": "data/quality_v2/events_quality_v2_staging.parquet",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
