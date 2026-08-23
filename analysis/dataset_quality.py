"""Read-only quality audit for the historical news/reaction dataset."""
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

def build_quality_report(session: Session, start: str | None = None, end: str | None = None, source: str | None = None, symbols: list[str] | None = None) -> dict:
    filters = ["n.is_valid = true"]
    params = {"start": start, "end": end, "source": source, "symbols": symbols or []}
    if start: filters.append("n.published_at >= CAST(:start AS timestamptz)")
    if end: filters.append("n.published_at < CAST(:end AS timestamptz)")
    if source: filters.append("n.source = :source")
    if symbols: filters.append("na.symbol = ANY(:symbols)")
    where = " AND ".join(filters)

    def scalar(sql: str) -> int:
        return int(session.execute(text(sql), params).scalar() or 0)

    summary = {
        "articles": scalar(f"SELECT COUNT(DISTINCT n.id) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where}"),
        "article_assets": scalar(f"SELECT COUNT(*) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where}"),
        "reactions": scalar(f"SELECT COUNT(*) FROM news_articles n JOIN news_assets na ON na.news_id=n.id JOIN news_market_reactions r ON r.news_id=n.id AND r.symbol=na.symbol WHERE {where}"),
        "missing_reactions": scalar(f"SELECT COUNT(*) FROM news_articles n JOIN news_assets na ON na.news_id=n.id LEFT JOIN news_market_reactions r ON r.news_id=n.id AND r.symbol=na.symbol WHERE {where} AND r.id IS NULL"),
        "future_dates": scalar(f"SELECT COUNT(DISTINCT n.id) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where} AND n.published_at > NOW()"),
        "published_after_modified": scalar(f"SELECT COUNT(DISTINCT n.id) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where} AND n.modified_at IS NOT NULL AND n.published_at > n.modified_at"),
        "short_articles": scalar(f"SELECT COUNT(DISTINCT n.id) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where} AND length(n.body) < 300"),
        "duplicate_urls": scalar("SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM news_articles GROUP BY url HAVING COUNT(*)>1) q"),
        "duplicate_canonical_urls": scalar("SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM news_articles WHERE canonical_url IS NOT NULL GROUP BY canonical_url HAVING COUNT(*)>1) q"),
        "duplicate_content_hashes": scalar("SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM news_articles GROUP BY content_hash HAVING COUNT(*)>1) q"),
        "anomalous_returns": scalar("SELECT COUNT(*) FROM news_market_reactions WHERE abs(return_5m)>100 OR abs(return_15m)>100 OR abs(return_30m)>100 OR abs(return_1h)>100 OR abs(return_4h)>100 OR abs(return_24h)>100"),
        "missing_candle_points": scalar(f"SELECT COUNT(*) FROM news_articles n JOIN news_assets na ON na.news_id=n.id CROSS JOIN (VALUES (0),(5),(15),(30),(60),(240),(1440)) h(minutes) LEFT JOIN market_candles c ON c.symbol=na.symbol AND c.interval='1m' AND c.open_time=date_trunc('minute',n.published_at)+interval '1 minute'+h.minutes*interval '1 minute' WHERE {where} AND c.id IS NULL"),
    }

    def distribution(select_sql: str) -> dict[str, int]:
        return {str(key): int(value) for key, value in session.execute(text(select_sql), params).all()}

    distributions = {
        "articles_per_source": distribution(f"SELECT n.source,COUNT(DISTINCT n.id) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where} GROUP BY n.source ORDER BY n.source"),
        "articles_per_asset": distribution(f"SELECT na.asset,COUNT(*) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where} GROUP BY na.asset ORDER BY na.asset"),
        "time_source": distribution(f"SELECT n.time_source,COUNT(DISTINCT n.id) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where} GROUP BY n.time_source ORDER BY n.time_source"),
        "time_confidence": distribution(f"SELECT CASE WHEN n.time_confidence>=0.95 THEN '0.95-1.00' WHEN n.time_confidence>=0.90 THEN '0.90-0.949' WHEN n.time_confidence>=0.70 THEN '0.70-0.899' ELSE '<0.70' END,COUNT(DISTINCT n.id) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where} GROUP BY 1 ORDER BY 1"),
        "articles_per_month": distribution(f"SELECT to_char(date_trunc('month',n.published_at),'YYYY-MM'),COUNT(DISTINCT n.id) FROM news_articles n JOIN news_assets na ON na.news_id=n.id WHERE {where} GROUP BY 1 ORDER BY 1"),
    }
    critical = ["missing_reactions", "future_dates", "published_after_modified", "short_articles", "duplicate_urls", "duplicate_canonical_urls", "duplicate_content_hashes", "anomalous_returns", "missing_candle_points"]
    return {"status": "PASS" if all(summary[key] == 0 for key in critical) else "FAIL", "generated_at": datetime.now(timezone.utc).isoformat(), "filters": params, "summary": summary, "distributions": distributions}

def export_quality_report(report: dict, directory: str | Path = "reports") -> tuple[Path, Path]:
    output = Path(directory); output.mkdir(parents=True, exist_ok=True)
    json_path = output / "dataset_quality_report.json"
    csv_path = output / "dataset_quality_report.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = [{"section": "summary", "metric": key, "value": value} for key, value in report["summary"].items()]
    for section, values in report["distributions"].items():
        rows.extend({"section": section, "metric": key, "value": value} for key, value in values.items())
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return csv_path, json_path
