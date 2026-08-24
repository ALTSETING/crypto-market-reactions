"""Capture the post-Reaction-V2 production baseline without mutating production."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import psycopg2
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
BACKUP = ROOT / "data/website/backups/pre_news_quality_v3"
EXPECTED_PROJECT_REF = "ickflwksigaotygtdyko"
EXPECTED_EVENTS = 7_878
GENERIC = {"document", "untitled", "article", "news", "home", "page"}


def normalize_database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("postgresql+psycopg2://"):
        return "postgresql://" + value.removeprefix("postgresql+psycopg2://")
    if value.startswith("postgres://"):
        return "postgresql://" + value.removeprefix("postgres://")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_assets(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).upper() for item in value]
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    try:
        parsed = json.loads(str(value))
        return [str(item).upper() for item in parsed] if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def normalized_title(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def frame_counts(frame: pd.DataFrame, columns: list[str], name: str) -> pd.DataFrame:
    return frame.groupby(columns, dropna=False).size().rename(name).reset_index()


def main() -> int:
    load_dotenv(ROOT / ".env")
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    parsed = urlparse(database_url)
    if EXPECTED_PROJECT_REF not in f"{parsed.hostname or ''} {parsed.username or ''}":
        raise RuntimeError("DATABASE_URL does not identify the expected Supabase project")
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM public.events ORDER BY event_id")
            columns = [item.name for item in cursor.description]
            live = pd.DataFrame(cursor.fetchall(), columns=columns)
            cursor.execute("SELECT to_regclass('public.alembic_version')")
            migrations = []
            if cursor.fetchone()[0] is not None:
                cursor.execute("SELECT version_num FROM public.alembic_version ORDER BY version_num")
                migrations = [str(row[0]) for row in cursor.fetchall()]
    finally:
        connection.close()
    if len(live) != EXPECTED_EVENTS or live.event_id.nunique() != EXPECTED_EVENTS or live.slug.nunique() != EXPECTED_EVENTS:
        raise RuntimeError("Production identity baseline failed")

    BACKUP.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    export = BACKUP / "supabase_events_post_reaction_v2.parquet"
    live.to_parquet(export, index=False)
    (BACKUP / "migration_state.json").write_text(json.dumps(migrations, indent=2) + "\n", encoding="utf-8")

    staging = pd.read_parquet(ROOT / "data/quality_v2/events_quality_v2_staging.parquet")
    audit = live.merge(
        staging[["event_id", "record_type", "story_id", "quality_status", "current_source_title"]],
        on="event_id", how="left", validate="one_to_one", suffixes=("", "_audit"),
    )
    audit["published_at"] = pd.to_datetime(audit.published_at, utc=True)
    audit["year"] = audit.published_at.dt.year
    audit["month"] = audit.published_at.dt.strftime("%Y-%m")
    audit["related_assets_list"] = audit.related_assets.map(parse_assets)
    audit["normalized_title"] = audit.title.map(normalized_title)

    by_year = frame_counts(audit, ["year"], "events")
    by_month = frame_counts(audit, ["month"], "events")
    by_source = frame_counts(audit, ["source"], "events").sort_values("events", ascending=False)
    by_type = frame_counts(audit, ["record_type"], "events").sort_values("events", ascending=False)
    coverage_source = frame_counts(audit, ["year", "source"], "events")
    coverage_type = frame_counts(audit, ["year", "record_type"], "events")
    asset_rows = []
    for row in audit[["year", "related_assets_list"]].itertuples(index=False):
        labels = row.related_assets_list or ["NONE"]
        asset_rows.extend({"year": int(row.year), "asset": asset} for asset in labels)
    coverage_asset = frame_counts(pd.DataFrame(asset_rows), ["year", "asset"], "events")
    for name, frame in {
        "NEWS_QUALITY_V3_EVENTS_BY_YEAR.csv": by_year,
        "NEWS_QUALITY_V3_EVENTS_BY_MONTH.csv": by_month,
        "NEWS_QUALITY_V3_EVENTS_BY_SOURCE.csv": by_source,
        "NEWS_QUALITY_V3_EVENTS_BY_RECORD_TYPE.csv": by_type,
        "NEWS_QUALITY_V3_COVERAGE_YEAR_SOURCE.csv": coverage_source,
        "NEWS_QUALITY_V3_COVERAGE_YEAR_ASSET.csv": coverage_asset,
        "NEWS_QUALITY_V3_COVERAGE_YEAR_RECORD_TYPE.csv": coverage_type,
    }.items():
        frame.to_csv(REPORTS / name, index=False)

    source_sample_path = REPORTS / "SOURCE_VERIFICATION_V2_SAMPLE.csv"
    source_sample = pd.read_csv(source_sample_path) if source_sample_path.exists() else pd.DataFrame()
    clusters_path = REPORTS / "DATA_QUALITY_V2_STORY_CLUSTERS.csv"
    clusters = pd.read_csv(clusters_path) if clusters_path.exists() else pd.DataFrame()
    years = {str(year): int(by_year.set_index("year").events.get(year, 0)) for year in range(2017, 2027)}
    summary = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "production_url": "https://crypto-market-reactions-nu.vercel.app",
        "expected_project_ref": EXPECTED_PROJECT_REF,
        "events_total": len(audit), "unique_event_ids": int(audit.event_id.nunique()),
        "unique_slugs": int(audit.slug.nunique()), "events_by_year": years,
        "events_2017_2022": int(audit.year.between(2017, 2022).sum()),
        "events_2023_2026": int(audit.year.between(2023, 2026).sum()),
        "events_without_related_assets": int(audit.related_assets_list.map(len).eq(0).sum()),
        "missing_sentiment": int(audit.sentiment.isna().sum()),
        "missing_importance": int(audit.importance.isna().sum()),
        "missing_sentiment_or_importance": int((audit.sentiment.isna() | audit.importance.isna()).sum()),
        "generic_titles": int(audit.normalized_title.isin(GENERIC).sum()),
        "duplicate_story_clusters": int(len(clusters)),
        "duplicate_story_articles": int(clusters.article_count.sum()) if not clusters.empty else 0,
        "source_url_status_rows": int(len(source_sample)),
        "title_verification_coverage": int(audit.current_source_title.notna().sum()),
        "record_types_missing_from_audit_join": int(audit.record_type.isna().sum()),
        "production_backup": str(export.relative_to(ROOT)),
        "production_backup_sha256": sha256(export),
        "migration_count": len(migrations),
    }
    (REPORTS / "news_quality_v3_baseline.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    year_lines = "\n".join(f"| {year} | {years[str(year)]:,} |" for year in range(2017, 2027))
    report = f"""# News Quality V3 baseline

Captured read-only from production after Reaction V2 at `{summary['captured_at']}`.

| Metric | Count |
|---|---:|
| Events | {len(audit):,} |
| 2017–2022 | {summary['events_2017_2022']:,} |
| 2023–2026 | {summary['events_2023_2026']:,} |
| Without related assets | {summary['events_without_related_assets']:,} |
| Missing sentiment | {summary['missing_sentiment']:,} |
| Missing importance | {summary['missing_importance']:,} |
| Missing either semantic field | {summary['missing_sentiment_or_importance']:,} |
| Generic titles | {summary['generic_titles']:,} |
| Existing story clusters / articles | {summary['duplicate_story_clusters']:,} / {summary['duplicate_story_articles']:,} |
| Source URLs previously sampled | {summary['source_url_status_rows']:,} |
| Current-title verification coverage | {summary['title_verification_coverage']:,} |

## Events by year

| Year | Events |
|---:|---:|
{year_lines}

Detailed month, source, record-type, asset, and year cross-tabs are stored in the `NEWS_QUALITY_V3_*` CSV reports. The production snapshot is `{summary['production_backup']}` with SHA-256 `{summary['production_backup_sha256']}`.
"""
    (DOCS / "NEWS_QUALITY_V3_BASELINE.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
