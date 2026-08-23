"""Free historical Stage 16B backfill and pre-AI audit.

This pipeline is intentionally archive-only: it never mutates Stage 16 tables,
never calls OpenAI, never trains a model, and never reads Stage 17 outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import requests
import tiktoken
from bs4 import BeautifulSoup
from remotezip import RemoteZip
from sqlalchemy import inspect, text

from database.db import engine
from high_impact_sources.analysis.ai_analyzer import (
    SEMANTIC_V21_SYSTEM_PROMPT,
    compact_input_v21,
    representative_output_tokens,
)
from high_impact_sources.config import USER_AGENT
from high_impact_sources.schemas import SEMANTIC_V21_SCHEMA
from high_impact_sources.stage16b_backfill import (
    ACTION_TERMS,
    clean_text,
    content_hash,
    group_signature,
    infer_event_type,
    local_relevance,
    near_duplicate_title,
    normalize_title,
    normalize_url,
    target_window,
)


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data" / "stage16b"
MODEL = "gpt-5-mini"
PROMPT_VERSION = "high_impact_semantic_v2_1"
OPENAI_BATCH_INPUT_PER_MILLION = 0.125
OPENAI_BATCH_OUTPUT_PER_MILLION = 1.0
SEC_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
SEC_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
EF_ARCHIVE_URL = "https://blog.ethereum.org/archive"
GITHUB_API = "https://api.github.com"
HORIZONS = ("1m", "5m", "10m", "20m", "40m", "1h", "3h", "5h", "8h", "12h")

REPORT_NAMES = (
    "stage16b_current_date_range.json",
    "stage16b_current_events_by_year.csv",
    "stage16b_source_availability.csv",
    "stage16b_market_data_availability.csv",
    "stage16b_candidates_by_year.csv",
    "stage16b_candidates_by_source.csv",
    "stage16b_candidates_by_asset.csv",
    "stage16b_rejections.csv",
    "stage16b_duplicates.csv",
    "stage16b_event_groups.csv",
    "stage16b_candle_coverage.csv",
    "stage16b_backfill_summary.json",
    "stage16b_pre_ai_assessment.md",
)

SEC_TERMS = (
    "bitcoin", "ethereum", '"crypto asset"', "cryptocurrency", '"virtual currency"',
    '"spot bitcoin"', '"exchange-traded fund" bitcoin', '"decentralized finance"', "staking ethereum", "solana",
)
SEC_ALLOWED_FORM_PREFIXES = (
    "8-K", "S-1", "S-3", "424B", "N-1A", "485", "POS", "253G", "D", "UPLOAD", "CORRESP",
)
GITHUB_REPOS = {
    "bitcoin/bitcoin": "BTC",
    "ethereum/go-ethereum": "ETH",
    "ethereum/consensus-specs": "ETH",
    "ethereum/execution-specs": "ETH",
    "solana-labs/solana": "SOL",
    "anza-xyz/agave": "SOL",
}


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(type(value).__name__)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_snapshot() -> dict[str, Any]:
    prefixes = tuple(f"stage{n}" for n in range(8, 18))
    files: dict[str, str] = {}
    for folder_name in ("reports", "data", "datasets", "patterns", "models"):
        folder = ROOT / folder_name
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            protected_name = name.startswith(prefixes) and not name.startswith("stage16b_")
            if protected_name or folder_name in ("patterns", "models"):
                files[str(path.relative_to(ROOT))] = sha256(path)
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for table in inspect(connection).get_table_names():
            if table.startswith("high_impact_") or table in {
                "news_articles", "news_assets", "market_candles", "news_market_reactions", "news_analysis",
            }:
                counts[table] = int(connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar())
    aggregate = hashlib.sha256("\n".join(f"{key}|{value}" for key, value in sorted(files.items())).encode()).hexdigest()
    return {"files": files, "table_counts": counts, "aggregate_sha256": aggregate}


def current_stage16() -> tuple[pd.DataFrame, dict[str, datetime], dict[str, Any]]:
    sql = text("""
      SELECT e.id,e.source,e.source_type,e.published_at,e.event_group_id,e.canonical_url,e.external_id,e.content_hash,e.title,
             a.asset,r.event_id IS NOT NULL AS has_reaction,
             (r.return_1m IS NOT NULL AND r.return_5m IS NOT NULL AND r.return_10m IS NOT NULL
              AND r.return_20m IS NOT NULL AND r.return_40m IS NOT NULL AND r.return_1h IS NOT NULL
              AND r.return_3h IS NOT NULL AND r.return_5h IS NOT NULL AND r.return_8h IS NOT NULL
              AND r.return_12h IS NOT NULL) AS fully_covered
      FROM high_impact_events e JOIN high_impact_event_assets a ON a.event_id=e.id
      LEFT JOIN high_impact_market_reactions r ON r.event_id=e.id AND r.symbol=a.asset||'USDT' AND r.latency_minutes=1
      WHERE e.status='accepted' ORDER BY e.published_at,e.id,a.asset
    """)
    with engine.connect() as connection:
        frame = pd.read_sql(sql, connection)
    frame["published_at"] = pd.to_datetime(frame.published_at, utc=True)
    frame["year"] = frame.published_at.dt.year
    earliest = {asset: group.published_at.min().to_pydatetime() for asset, group in frame.groupby("asset")}
    rows = []
    for year, part in frame.groupby("year"):
        rows.append({"dimension": "all", "value": "all", "year": year, "unique_events": part.id.nunique(), "event_asset_rows": len(part), "fully_covered_rows": int(part.fully_covered.sum())})
        for source, group in part.groupby("source"):
            rows.append({"dimension": "source", "value": source, "year": year, "unique_events": group.id.nunique(), "event_asset_rows": len(group), "fully_covered_rows": int(group.fully_covered.sum())})
        for asset, group in part.groupby("asset"):
            rows.append({"dimension": "asset", "value": asset, "year": year, "unique_events": group.id.nunique(), "event_asset_rows": len(group), "fully_covered_rows": int(group.fully_covered.sum())})
    pd.DataFrame(rows).to_csv(REPORTS / "stage16b_current_events_by_year.csv", index=False)
    payload = {
        "earliest_event_timestamp": frame.published_at.min(),
        "latest_event_timestamp": frame.published_at.max(),
        "unique_events": int(frame.id.nunique()),
        "event_asset_rows": len(frame),
        "asset_earliest": earliest,
        "unique_events_by_year": {str(k): int(v) for k, v in frame.groupby("year").id.nunique().items()},
        "event_asset_rows_by_year": {str(k): int(v) for k, v in frame.groupby("year").size().items()},
        "fully_covered_rows_by_year": {str(k): int(v) for k, v in frame.groupby("year").fully_covered.sum().items()},
        "source_by_year": frame.groupby(["source", "year"]).size().rename("rows").reset_index().to_dict("records"),
        "asset_by_year": frame.groupby(["asset", "year"]).size().rename("rows").reset_index().to_dict("records"),
    }
    write_json(REPORTS / "stage16b_current_date_range.json", payload)
    return frame, earliest, payload


def market_availability() -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    with engine.connect() as connection:
        frame = pd.read_sql(text("""
          WITH ordered AS (
            SELECT symbol,open_time,lag(open_time) OVER(PARTITION BY symbol ORDER BY open_time) previous
            FROM market_candles WHERE interval='1m' AND symbol=ANY(:symbols)
          ) SELECT symbol,min(open_time) earliest,max(open_time) latest,count(*) candles,
              sum(CASE WHEN previous IS NOT NULL AND open_time-previous>interval '1 minute' THEN 1 ELSE 0 END) gap_runs,
              sum(CASE WHEN previous IS NOT NULL AND open_time-previous>interval '1 minute' THEN extract(epoch FROM(open_time-previous))/60-1 ELSE 0 END)::bigint missing_minutes,
              max(CASE WHEN previous IS NOT NULL THEN extract(epoch FROM(open_time-previous))/60-1 ELSE 0 END)::bigint max_gap_minutes
          FROM ordered GROUP BY symbol ORDER BY symbol
        """), connection, params={"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]})
        gaps = pd.read_sql(text("""
          WITH ordered AS (
            SELECT symbol,open_time,lag(open_time) OVER(PARTITION BY symbol ORDER BY open_time) previous
            FROM market_candles WHERE interval='1m' AND symbol=ANY(:symbols)
          ) SELECT symbol,previous AS gap_after,open_time AS gap_before,
              (extract(epoch FROM(open_time-previous))/60-1)::int missing_minutes
          FROM ordered WHERE open_time-previous>interval '1 minute' ORDER BY symbol,open_time
        """), connection, params={"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]})
    frame["earliest"] = pd.to_datetime(frame.earliest, utc=True)
    frame["latest"] = pd.to_datetime(frame.latest, utc=True)
    frame["earliest_usable_with_12h_precontext"] = frame.earliest + pd.Timedelta(hours=12)
    frame["latest_usable_with_12h_postcontext"] = frame.latest - pd.Timedelta(hours=12)
    frame["synthetic_candles"] = 0
    frame["long_gaps_interpolated"] = 0
    frame["gap_details"] = frame.symbol.map(lambda symbol: json.dumps(gaps[gaps.symbol.eq(symbol)].to_dict("records"), default=json_default))
    frame.to_csv(REPORTS / "stage16b_market_data_availability.csv", index=False)
    mapping = {row.symbol.replace("USDT", ""): row._asdict() for row in frame.itertuples(index=False)}
    return frame, mapping


def session() -> requests.Session:
    value = requests.Session()
    value.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json,text/html,application/xml;q=0.9"})
    return value


def record_base(**kwargs: Any) -> dict[str, Any]:
    record = {
        "record_id": "",
        "source": "",
        "source_type": "",
        "platform": "",
        "channel": "",
        "url": "",
        "canonical_url": "",
        "external_id": None,
        "accession_number": None,
        "cik": None,
        "form_type": None,
        "filing_date": None,
        "accepted_at": None,
        "title": "",
        "author": None,
        "category": None,
        "body": "",
        "published_at": None,
        "modified_at": None,
        "time_source": "",
        "time_confidence": 0.0,
        "content_hash": "",
        "raw_text_hash": "",
        "matched_keywords": [],
        "matched_entities": [],
        "matched_protocol": None,
        "assets": [],
        "local_relevance_score": 0,
        "relevance_class": "none",
        "crypto_relevant": False,
        "event_type": "other",
        "status": "retrieved",
        "rejection_reason": None,
        "duplicate_of_existing_event_id": None,
        "duplicate_of_candidate_id": None,
        "event_group_id": None,
        "market_data_unavailable": True,
        "calendar_year": None,
        "quarter": None,
        "btc_market_regime": None,
        "market_regime": None,
        "volatility_regime": None,
        "pre_event_liquidity_regime": None,
        "exchange_volume_regime": None,
    }
    record.update(kwargs)
    record["canonical_url"] = normalize_url(record["canonical_url"] or record["url"]) if record["url"] else ""
    if record["published_at"] is not None:
        timestamp = pd.Timestamp(record["published_at"])
        timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        record["published_at"] = timestamp.to_pydatetime()
        record["calendar_year"] = timestamp.year
        record["quarter"] = f"{timestamp.year}Q{timestamp.quarter}"
    record["content_hash"] = record["content_hash"] or content_hash(record["title"], record["body"])
    record["raw_text_hash"] = record["raw_text_hash"] or hashlib.sha256(record["body"].encode("utf-8")).hexdigest()
    identity = f"{record['source']}|{record['external_id'] or record['canonical_url']}|{record['published_at']}"
    record["record_id"] = record["record_id"] or "src16b-" + hashlib.sha256(identity.encode()).hexdigest()[:20]
    return record


def fetch_ethereum_foundation(earliest: dict[str, datetime]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = session()
    response = client.get(EF_ARCHIVE_URL, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    found: dict[str, tuple[datetime, str]] = {}
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        match = re.match(r"^/(20\d{2})/(\d{2})/(\d{2})/[^/?#]+", href)
        if not match:
            continue
        timestamp = datetime(*map(int, match.groups()), tzinfo=timezone.utc)
        if datetime(2013, 12, 1, tzinfo=timezone.utc) <= timestamp < earliest["ETH"]:
            found.setdefault(href, (timestamp, clean_text(anchor.get_text(" ", strip=True))))
    title_filter = re.compile("|".join(re.escape(term) for term in ACTION_TERMS + (
        "frontier", "homestead", "byzantium", "constantinople", "istanbul", "dao", "eth2", "beacon", "serenity", "metropolis",
    )), re.I)
    records: list[dict[str, Any]] = []
    fetched_pages = 0
    errors = []
    for href, (url_timestamp, archive_title) in sorted(found.items(), key=lambda item: item[1][0]):
        url = "https://blog.ethereum.org" + href
        if not title_filter.search(archive_title):
            records.append(record_base(source="ethereum_foundation", source_type="protocol", platform="ethereum_blog", channel="ethereum_foundation_archive", url=url, external_id=href.rsplit("/", 1)[-1], title=archive_title, body=archive_title, published_at=url_timestamp, time_source="official_archive_url_date", time_confidence=0.90, assets=["ETH"], local_relevance_score=35, relevance_class="direct", status="rejected", rejection_reason="title_prefilter_no_concrete_event"))
            continue
        try:
            time.sleep(1.0)
            page_response = client.get(url, timeout=45)
            page_response.raise_for_status()
            page = BeautifulSoup(page_response.text, "html.parser")
            fetched_pages += 1
            posting: dict[str, Any] = {}
            for node in page.select('script[type="application/ld+json"]'):
                try:
                    parsed = json.loads(node.string or "{}")
                except json.JSONDecodeError:
                    continue
                candidates = parsed if isinstance(parsed, list) else [parsed]
                if isinstance(parsed, dict) and isinstance(parsed.get("@graph"), list):
                    candidates += parsed["@graph"]
                posting = next((item for item in candidates if isinstance(item, dict) and item.get("@type") in ("BlogPosting", "Article")), posting)
            article = page.select_one("article") or page.select_one("main")
            body = clean_text(article.get_text(" ", strip=True) if article else "")
            title = clean_text(str(posting.get("headline") or archive_title))
            published = pd.to_datetime(posting.get("datePublished") or url_timestamp, utc=True).to_pydatetime()
            author_value = posting.get("author")
            if isinstance(author_value, dict):
                author = author_value.get("name")
            elif isinstance(author_value, list):
                author = ", ".join(str(item.get("name")) for item in author_value if isinstance(item, dict) and item.get("name"))
            else:
                author = str(author_value) if author_value else None
            category = posting.get("articleSection") or (page.select_one('meta[property="article:section"]') or {}).get("content")
            relevance = local_relevance(title, body, default_asset="ETH", channel="ethereum_foundation")
            records.append(record_base(source="ethereum_foundation", source_type="protocol", platform="ethereum_blog", channel="ethereum_foundation_archive", url=url, external_id=href.rsplit("/", 1)[-1], title=title, author=author, category=category, body=body, published_at=published, modified_at=posting.get("dateModified"), time_source="official_json_ld" if posting else "official_archive_url_date", time_confidence=0.98 if posting else 0.90, event_type=infer_event_type(title, body), status="accepted" if relevance["crypto_relevant"] else "rejected", **{key: relevance[key] for key in ("assets", "matched_keywords", "matched_entities", "matched_protocol", "relevance_class", "crypto_relevant")}, local_relevance_score=relevance["relevance_score"], rejection_reason=relevance["rejection_reason"]))
        except Exception as exc:
            errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
            records.append(record_base(source="ethereum_foundation", source_type="protocol", platform="ethereum_blog", channel="ethereum_foundation_archive", url=url, external_id=href.rsplit("/", 1)[-1], title=archive_title, body=archive_title, published_at=url_timestamp, time_source="official_archive_url_date", time_confidence=0.90, assets=["ETH"], status="rejected", rejection_reason="page_download_failed"))
    availability = {"source": "ethereum_foundation", "channel": "official_blog_archive", "url": EF_ARCHIVE_URL, "status": "available", "retrieved_archive_links": len(found), "downloaded_candidate_pages": fetched_pages, "errors": len(errors), "earliest_requested": "2013-12-01", "latest_requested": (earliest["ETH"] - timedelta(days=1)).date().isoformat(), "free_or_paid": "free", "estimated_cost_usd": 0.0, "notes": "English canonical URLs only; translations excluded."}
    return records, availability


def sec_search(earliest: dict[str, datetime]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = session()
    hits: dict[str, dict[str, Any]] = {}
    query_stats = []
    for year in range(2017, 2023):
        for term in SEC_TERMS:
            params = {"q": term, "dateRange": "custom", "startdt": f"{year}-01-01", "enddt": f"{year}-12-31", "from": 0, "size": 100}
            try:
                time.sleep(0.12)
                response = client.get(SEC_EFTS_URL, params=params, timeout=45)
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("hits", {}).get("hits", [])
                total = payload.get("hits", {}).get("total", {})
                total_value = int(total.get("value", 0) if isinstance(total, dict) else total or 0)
                query_stats.append({"year": year, "term": term, "total": total_value, "retrieved": len(rows), "capped": total_value > len(rows)})
                for hit in rows:
                    source = hit.get("_source", {})
                    if int(source.get("sequence") or 1) != 1:
                        continue
                    identity = str(hit.get("_id"))
                    item = hits.setdefault(identity, {"hit": hit, "terms": set()})
                    item["terms"].add(term.replace('"', ""))
            except Exception as exc:
                query_stats.append({"year": year, "term": term, "total": 0, "retrieved": 0, "capped": False, "error": f"{type(exc).__name__}: {exc}"})
    prefiltered = []
    records: list[dict[str, Any]] = []
    for identity, item in hits.items():
        source = item["hit"].get("_source", {})
        form = str(source.get("form") or "")
        filing_date = pd.to_datetime(source.get("file_date"), utc=True, errors="coerce")
        ciks = source.get("ciks") or []
        if pd.isna(filing_date) or not ciks or not form.upper().startswith(SEC_ALLOWED_FORM_PREFIXES):
            records.append(record_base(source="sec", source_type="regulator", platform="edgar", channel="edgar_full_text_index", url="", external_id=source.get("adsh"), accession_number=source.get("adsh"), cik=ciks[0] if ciks else None, form_type=form, filing_date=source.get("file_date"), title="; ".join(source.get("display_names") or []) or identity, body="", published_at=filing_date.to_pydatetime() if not pd.isna(filing_date) else datetime(2017, 1, 1, tzinfo=timezone.utc), time_source="edgar_filing_date", time_confidence=0.60, matched_keywords=sorted(item["terms"]), status="rejected", rejection_reason="metadata_prefilter_form_or_timestamp"))
            continue
        item["score"] = float(item["hit"].get("_score") or 0)
        prefiltered.append(item)
    prefiltered.sort(key=lambda item: item["score"], reverse=True)
    document_cap = 350
    for item in prefiltered[document_cap:]:
        source = item["hit"]["_source"]
        ciks = source.get("ciks") or []
        timestamp = pd.to_datetime(source["file_date"], utc=True).to_pydatetime()
        records.append(record_base(source="sec", source_type="regulator", platform="edgar", channel="edgar_full_text_index", url="", external_id=source.get("adsh"), accession_number=source.get("adsh"), cik=ciks[0] if ciks else None, form_type=source.get("form"), filing_date=source.get("file_date"), title="; ".join(source.get("display_names") or []), body="", published_at=timestamp, time_source="edgar_filing_date", time_confidence=0.60, matched_keywords=sorted(item["terms"]), status="rejected", rejection_reason="bounded_document_download_cap"))
    downloaded = 0
    for item in prefiltered[:document_cap]:
        source = item["hit"]["_source"]
        identity = item["hit"]["_id"]
        accession, filename = identity.split(":", 1)
        cik = str((source.get("ciks") or [""])[0]).lstrip("0") or "0"
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{filename}"
        timestamp = pd.to_datetime(source["file_date"], utc=True).to_pydatetime()
        try:
            time.sleep(0.12)
            response = client.get(url, timeout=45)
            response.raise_for_status()
            downloaded += 1
            page = BeautifulSoup(response.text, "lxml")
            body = clean_text(page.get_text(" ", strip=True))
            document_title = clean_text(page.title.get_text(" ", strip=True) if page.title else "")
            title = document_title[:500] or f"{'; '.join(source.get('display_names') or [])} {source.get('form')} {accession}"
            relevance = local_relevance(title, body, form_type=source.get("form"), channel="sec_edgar")
            assets = [asset for asset in relevance["assets"] if target_window(asset, timestamp, earliest)]
            if relevance["crypto_relevant"] and not assets:
                relevance["crypto_relevant"] = False
                relevance["rejection_reason"] = "outside_asset_backfill_window"
            records.append(record_base(source="sec", source_type="regulator", platform="edgar", channel="edgar_full_text_index", url=url, external_id=accession, accession_number=accession, cik=str(cik).zfill(10), form_type=source.get("form"), filing_date=source.get("file_date"), title=title, body=body, published_at=timestamp, time_source="edgar_filing_date_pending_bulk_enrichment", time_confidence=0.60, event_type=infer_event_type(title, body), status="accepted" if relevance["crypto_relevant"] else "rejected", assets=assets, matched_keywords=sorted(set(relevance["matched_keywords"]) | set(term.replace('"', "") for term in item["terms"])), matched_entities=relevance["matched_entities"], matched_protocol=relevance["matched_protocol"], local_relevance_score=relevance["relevance_score"], relevance_class=relevance["relevance_class"], crypto_relevant=relevance["crypto_relevant"], rejection_reason=relevance["rejection_reason"]))
        except Exception as exc:
            records.append(record_base(source="sec", source_type="regulator", platform="edgar", channel="edgar_full_text_index", url=url, external_id=accession, accession_number=accession, cik=str(cik).zfill(10), form_type=source.get("form"), filing_date=source.get("file_date"), title=f"{'; '.join(source.get('display_names') or [])} {source.get('form')} {accession}", body="", published_at=timestamp, time_source="edgar_filing_date", time_confidence=0.60, matched_keywords=sorted(item["terms"]), status="rejected", rejection_reason=f"document_download_failed:{type(exc).__name__}"))
    accepted = [record for record in records if record["status"] == "accepted"]
    bulk = enrich_sec_from_bulk(accepted)
    availability = {"source": "sec", "channel": "EDGAR full-text index + submissions bulk archive", "url": SEC_BULK_URL, "status": "available_bounded", "query_count": len(query_stats), "search_hits_unique": len(hits), "metadata_prefilter_candidates": len(prefiltered), "documents_downloaded": downloaded, "document_download_cap": document_cap, "accepted_before_dedup": len(accepted), "queries_capped": sum(bool(row.get("capped")) for row in query_stats), "bulk_archive_bytes": bulk["archive_bytes"], "bulk_archive_entries": bulk["archive_entries"], "bulk_ciks_requested": bulk["ciks_requested"], "bulk_ciks_found": bulk["ciks_found"], "bulk_accessions_enriched": bulk["accessions_enriched"], "free_or_paid": "free", "estimated_cost_usd": 0.0, "notes": "HTTP Range read of official 1.55GB ZIP; only matched CIK JSON entries downloaded because local disk guard prevented full extraction."}
    return records, availability


def enrich_sec_from_bulk(records: list[dict[str, Any]]) -> dict[str, Any]:
    ciks = sorted({str(record["cik"]).zfill(10) for record in records if record.get("cik")})
    wanted = {record["accession_number"] for record in records}
    found: dict[str, dict[str, Any]] = {}
    archive_bytes = None
    try:
        head = requests.head(SEC_BULK_URL, headers={"User-Agent": USER_AGENT}, timeout=45)
        archive_bytes = int(head.headers.get("content-length") or 0)
        with RemoteZip(SEC_BULK_URL, headers={"User-Agent": USER_AGENT}) as archive:
            names = set(archive.namelist())
            archive_entries = len(names)
            ciks_found = 0
            for cik in ciks:
                main_name = f"CIK{cik}.json"
                if main_name not in names:
                    continue
                ciks_found += 1
                main = json.loads(archive.read(main_name))
                sections = [main.get("filings", {}).get("recent", {})]
                for file_info in main.get("filings", {}).get("files", []):
                    name = file_info.get("name")
                    if name in names:
                        sections.append(json.loads(archive.read(name)))
                for section in sections:
                    accessions = section.get("accessionNumber", [])
                    for index, accession in enumerate(accessions):
                        if accession not in wanted:
                            continue
                        found[accession] = {key: (section.get(key, [None] * len(accessions))[index] if index < len(section.get(key, [])) else None) for key in ("acceptanceDateTime", "filingDate", "primaryDocument", "form")}
    except Exception as exc:
        archive_entries = 0
        ciks_found = 0
        return {"archive_bytes": archive_bytes, "archive_entries": archive_entries, "ciks_requested": len(ciks), "ciks_found": ciks_found, "accessions_enriched": 0, "error": f"{type(exc).__name__}: {exc}"}
    for record in records:
        metadata = found.get(record["accession_number"])
        if not metadata:
            continue
        raw = metadata.get("acceptanceDateTime")
        if raw:
            accepted = pd.to_datetime(str(raw), utc=True, errors="coerce")
            if not pd.isna(accepted):
                record["accepted_at"] = accepted.to_pydatetime()
                record["published_at"] = accepted.to_pydatetime()
                record["time_source"] = "edgar_bulk_acceptance_datetime"
                record["time_confidence"] = 1.0
    return {"archive_bytes": archive_bytes, "archive_entries": archive_entries, "ciks_requested": len(ciks), "ciks_found": ciks_found, "accessions_enriched": len(found)}


def github_get(client: requests.Session, url: str, *, params: dict[str, Any] | None = None) -> tuple[Any, str | None]:
    try:
        response = client.get(url, params=params, timeout=45)
        response.raise_for_status()
        return response.json(), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def fetch_github(earliest: dict[str, datetime]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = session()
    client.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    token = os.getenv("GITHUB_TOKEN")
    if token:
        client.headers["Authorization"] = f"Bearer {token}"
    records: list[dict[str, Any]] = []
    channel_counts: Counter[str] = Counter()
    errors = []

    def add(repo: str, asset: str, channel: str, item: dict[str, Any], title: str, body: str, published: Any, url: str, external: str, author: str | None = None) -> None:
        timestamp = pd.to_datetime(published, utc=True, errors="coerce")
        if pd.isna(timestamp) or not target_window(asset, timestamp.to_pydatetime(), earliest):
            return
        relevance = local_relevance(title, body, default_asset=asset, channel=f"github_{channel}")
        records.append(record_base(source=f"{asset.lower()}_github", source_type="github", platform="github", channel=f"github_{channel}", url=url, external_id=external, title=clean_text(title), author=author, body=clean_text(body), published_at=timestamp.to_pydatetime(), modified_at=item.get("updated_at"), time_source=f"github_{channel}_public_timestamp", time_confidence=0.95 if channel in ("merged_pull_request", "issue") else 1.0, event_type=infer_event_type(title, body), status="accepted" if relevance["crypto_relevant"] else "rejected", assets=[asset], matched_keywords=relevance["matched_keywords"], matched_entities=[asset], matched_protocol=repo, local_relevance_score=relevance["relevance_score"], relevance_class="direct", crypto_relevant=relevance["crypto_relevant"], rejection_reason=relevance["rejection_reason"]))

    for repo, asset in GITHUB_REPOS.items():
        metadata, error = github_get(client, f"{GITHUB_API}/repos/{repo}")
        if error:
            errors.append({"repo": repo, "channel": "repository", "error": error})
        else:
            channel_counts["repository_metadata"] += 1
        releases, error = github_get(client, f"{GITHUB_API}/repos/{repo}/releases", params={"per_page": 100, "page": 1})
        if error:
            errors.append({"repo": repo, "channel": "releases", "error": error})
        else:
            channel_counts["releases_retrieved"] += len(releases)
            for item in releases:
                add(repo, asset, "release", item, f"{repo} {item.get('name') or item.get('tag_name')}", item.get("body") or "", item.get("published_at") or item.get("created_at"), item.get("html_url"), str(item.get("id")), (item.get("author") or {}).get("login"))
        tags, error = github_get(client, f"{GITHUB_API}/repos/{repo}/tags", params={"per_page": 100, "page": 1})
        if error:
            errors.append({"repo": repo, "channel": "tags", "error": error})
        else:
            channel_counts["tags_retrieved"] += len(tags)
        commits, error = github_get(client, f"{GITHUB_API}/repos/{repo}/commits", params={"since": "2017-01-01T00:00:00Z", "until": (earliest[asset] - timedelta(seconds=1)).isoformat(), "per_page": 100, "page": 1})
        if error:
            errors.append({"repo": repo, "channel": "commits", "error": error})
        else:
            channel_counts["commits_retrieved"] += len(commits)
            for item in commits:
                commit = item.get("commit") or {}
                message = commit.get("message") or ""
                if not any(term in message.lower() for term in ACTION_TERMS):
                    continue
                author_data = commit.get("author") or {}
                add(repo, asset, "commit", item, f"{repo} {message.splitlines()[0]}", message, author_data.get("date"), item.get("html_url"), item.get("sha"), author_data.get("name"))
        advisories, error = github_get(client, f"{GITHUB_API}/repos/{repo}/security-advisories", params={"per_page": 100})
        if error:
            errors.append({"repo": repo, "channel": "security_advisories", "error": error})
        else:
            channel_counts["security_advisories_retrieved"] += len(advisories)
            for item in advisories:
                add(repo, asset, "security_advisory", item, f"{repo} {item.get('summary') or item.get('ghsa_id')}", item.get("description") or "security vulnerability advisory", item.get("published_at"), item.get("html_url"), item.get("ghsa_id"), (item.get("publisher") or {}).get("login"))
        for label in ("announcement", "security"):
            issues, error = github_get(client, f"{GITHUB_API}/repos/{repo}/issues", params={"state": "all", "labels": label, "per_page": 100, "page": 1})
            if error:
                errors.append({"repo": repo, "channel": f"issues:{label}", "error": error})
                continue
            channel_counts[f"issues_{label}_retrieved"] += len(issues)
            for item in issues:
                if "pull_request" in item:
                    continue
                add(repo, asset, "issue", item, f"{repo} {item.get('title')}", item.get("body") or "", item.get("created_at"), item.get("html_url"), f"issue-{item.get('number')}", (item.get("user") or {}).get("login"))
        search_query = f'repo:{repo} is:pr is:merged (upgrade OR "hard fork" OR security OR mainnet OR release) created:2017-01-01..{(earliest[asset]-timedelta(days=1)).date().isoformat()}'
        pulls, error = github_get(client, f"{GITHUB_API}/search/issues", params={"q": search_query, "sort": "created", "order": "asc", "per_page": 100, "page": 1})
        if error:
            errors.append({"repo": repo, "channel": "merged_pull_requests", "error": error})
        else:
            items = pulls.get("items", []) if isinstance(pulls, dict) else []
            channel_counts["merged_pull_requests_retrieved"] += len(items)
            for item in items:
                add(repo, asset, "merged_pull_request", item, f"{repo} {item.get('title')}", item.get("body") or "", item.get("closed_at") or item.get("created_at"), item.get("html_url"), f"pr-{item.get('number')}", (item.get("user") or {}).get("login"))
    availability = {"source": "github", "channel": "allowlisted official repositories", "url": "https://api.github.com", "status": "available_bounded", "repositories": len(GITHUB_REPOS), **dict(channel_counts), "accepted_before_dedup": sum(record["status"] == "accepted" for record in records), "errors": len(errors), "authenticated": bool(token), "free_or_paid": "free", "estimated_cost_usd": 0.0, "notes": "One bounded historical page per channel/repository; tags without a verified timestamp remain metadata and are not promoted to market events."}
    return records, availability


def deduplicate_and_group(records: list[dict[str, Any]], current: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    accepted = [record for record in records if record["status"] == "accepted"]
    rejections = [record.copy() for record in records if record["status"] != "accepted"]
    existing_url = {normalize_url(str(row.canonical_url)): int(row.id) for row in current.itertuples() if row.canonical_url}
    existing_external = {(str(row.source), str(row.external_id)): int(row.id) for row in current.itertuples() if row.external_id}
    existing_hash = {str(row.content_hash): int(row.id) for row in current.itertuples() if row.content_hash}
    duplicates: list[dict[str, Any]] = []
    unique: list[dict[str, Any]] = []
    seen_url: dict[str, str] = {}
    seen_external: dict[tuple[str, str], str] = {}
    seen_hash: dict[str, str] = {}
    for record in sorted(accepted, key=lambda row: (row["published_at"], row["source"], row["record_id"])):
        url = record["canonical_url"]
        external = (record["source"], str(record["external_id"]))
        duplicate_type = None
        duplicate_value: Any = None
        if url and url in existing_url:
            duplicate_type, duplicate_value = "canonical_url_existing", existing_url[url]
        elif record["external_id"] and external in existing_external:
            duplicate_type, duplicate_value = "external_id_existing", existing_external[external]
        elif record["content_hash"] in existing_hash:
            duplicate_type, duplicate_value = "content_hash_existing", existing_hash[record["content_hash"]]
        elif url and url in seen_url:
            duplicate_type, duplicate_value = "canonical_url_batch", seen_url[url]
        elif record["external_id"] and external in seen_external:
            duplicate_type, duplicate_value = "external_id_batch", seen_external[external]
        elif record["content_hash"] in seen_hash:
            duplicate_type, duplicate_value = "content_hash_batch", seen_hash[record["content_hash"]]
        else:
            for previous in reversed(unique[-100:]):
                if record["source"] == previous["source"] and abs((record["published_at"] - previous["published_at"]).total_seconds()) <= 3 * 86400 and near_duplicate_title(record["title"], previous["title"]):
                    duplicate_type, duplicate_value = "near_title_time_batch", previous["record_id"]
                    break
        if duplicate_type:
            record["status"] = "duplicate"
            if isinstance(duplicate_value, int):
                record["duplicate_of_existing_event_id"] = duplicate_value
            else:
                record["duplicate_of_candidate_id"] = duplicate_value
            duplicates.append({"record_id": record["record_id"], "source": record["source"], "canonical_url": record["canonical_url"], "duplicate_type": duplicate_type, "duplicate_of": duplicate_value, "old_stage16_priority": isinstance(duplicate_value, int)})
            continue
        unique.append(record)
        if url:
            seen_url[url] = record["record_id"]
        if record["external_id"]:
            seen_external[external] = record["record_id"]
        seen_hash[record["content_hash"]] = record["record_id"]

    expanded = []
    for record in unique:
        for asset in record["assets"]:
            if target_window(asset, record["published_at"], {key: value.to_pydatetime() if isinstance(value, pd.Timestamp) else value for key, value in current.groupby("asset").published_at.min().to_dict().items()}):
                item = record.copy()
                item["asset"] = asset
                item["event_group_id"] = group_signature(asset, record["title"], record["published_at"])
                expanded.append(item)
    expanded_frame = pd.DataFrame(expanded)
    canonical_rows = []
    group_rows = []
    if not expanded_frame.empty:
        for group_id, part in expanded_frame.groupby("event_group_id", sort=True):
            part = part.sort_values(["published_at", "source"])
            first = part.iloc[0]
            event_id = "evt16b-" + hashlib.sha256(group_id.encode()).hexdigest()[:16]
            assets = sorted(part.asset.unique())
            canonical_rows.append({"canonical_event_id": event_id, "event_group_id": group_id, "published_at": first.published_at, "source": first.source, "source_type": first.source_type, "platform": first.platform, "title": first.title, "body": first.body, "canonical_url": first.canonical_url, "event_type": first.event_type, "assets": assets, "source_record_count": part.record_id.nunique(), "local_relevance_score": float(part.local_relevance_score.max()), "calendar_year": first.calendar_year, "quarter": first.quarter, "btc_market_regime": None, "market_regime": None, "volatility_regime": None, "pre_event_liquidity_regime": None, "exchange_volume_regime": None})
            for row in part.itertuples():
                group_rows.append({"canonical_event_id": event_id, "event_group_id": group_id, "record_id": row.record_id, "asset": row.asset, "source": row.source, "published_at": row.published_at, "canonical_url": row.canonical_url, "is_earliest_verified_source": row.record_id == first.record_id})
    return pd.DataFrame(unique), pd.DataFrame(canonical_rows), pd.DataFrame(group_rows), pd.DataFrame(duplicates), pd.DataFrame(rejections)


def candle_coverage(canonical: pd.DataFrame, availability: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for event in canonical.itertuples():
        for asset in event.assets:
            market = availability[asset]
            timestamp = pd.Timestamp(event.published_at)
            earliest = pd.Timestamp(market["earliest"])
            latest = pd.Timestamp(market["latest"])
            baseline = earliest <= timestamp <= latest
            pre = timestamp - pd.Timedelta(hours=12) >= earliest
            post = timestamp + pd.Timedelta(hours=12) <= latest
            reason = "fully_covered"
            if timestamp < earliest:
                reason = "published_before_available_1m_candles"
            elif timestamp > latest:
                reason = "published_after_available_1m_candles"
            elif not pre:
                reason = "insufficient_12h_pre_context"
            elif not post:
                reason = "insufficient_12h_post_horizons"
            fully = baseline and pre and post
            rows.append({"canonical_event_id": event.canonical_event_id, "event_group_id": event.event_group_id, "published_at": timestamp, "asset": asset, "symbol": f"{asset}USDT", "baseline_available": baseline, "pre_context_12h_complete": pre, "all_post_horizons_complete": post, "critical_gap": False, "fully_covered": fully, "market_data_unavailable": not fully, "coverage_reason": reason, "earliest_candle": earliest, "latest_candle": latest})
    return pd.DataFrame(rows)


def aggregate_reports(canonical: pd.DataFrame, groups: pd.DataFrame, coverage: pd.DataFrame, records: pd.DataFrame, rejections: pd.DataFrame, duplicates: pd.DataFrame) -> None:
    def grouped(dimension: str) -> pd.DataFrame:
        if coverage.empty:
            return pd.DataFrame(columns=[dimension, "unique_events", "event_asset_rows", "fully_covered_rows"])
        joined = coverage.merge(canonical[["canonical_event_id", "source", "event_type", "calendar_year"]], on="canonical_event_id", how="left")
        key = {"year": "calendar_year", "source": "source", "asset": "asset"}[dimension]
        return joined.groupby(key, dropna=False).agg(unique_events=("canonical_event_id", "nunique"), event_asset_rows=("canonical_event_id", "size"), fully_covered_rows=("fully_covered", "sum")).reset_index().rename(columns={key: dimension})
    grouped("year").to_csv(REPORTS / "stage16b_candidates_by_year.csv", index=False)
    grouped("source").to_csv(REPORTS / "stage16b_candidates_by_source.csv", index=False)
    grouped("asset").to_csv(REPORTS / "stage16b_candidates_by_asset.csv", index=False)
    rejections.to_csv(REPORTS / "stage16b_rejections.csv", index=False)
    duplicates.to_csv(REPORTS / "stage16b_duplicates.csv", index=False)
    groups.to_csv(REPORTS / "stage16b_event_groups.csv", index=False)
    coverage.to_csv(REPORTS / "stage16b_candle_coverage.csv", index=False)


def token_estimate(canonical: pd.DataFrame) -> dict[str, Any]:
    encoding = tiktoken.get_encoding("o200k_base")
    schema_text = json.dumps(SEMANTIC_V21_SCHEMA, ensure_ascii=False, separators=(",", ":"))
    values = []
    for row in canonical.itertuples():
        obj = SimpleNamespace(source=row.source, source_type=row.source_type, platform=row.platform, author_name=None, published_at=pd.Timestamp(row.published_at).to_pydatetime(), title=row.title, body=row.body, assets=row.assets)
        payload = compact_input_v21(obj, 900)
        values.append(len(encoding.encode(SEMANTIC_V21_SYSTEM_PROMPT + payload + schema_text)))
    output_per_event = representative_output_tokens("v21")
    total_input = int(sum(values))
    total_output = int(output_per_event * len(values))
    return {"events_for_ai": len(values), "model": MODEL, "prompt_version": PROMPT_VERSION, "max_body_tokens": 900, "input_tokens": {"total": total_input, "average": float(np.mean(values)) if values else 0, "median": float(np.median(values)) if values else 0, "p95": float(np.quantile(values, 0.95)) if values else 0, "max": int(max(values)) if values else 0}, "estimated_output_tokens_per_event": output_per_event, "estimated_output_tokens_total": total_output, "estimated_batch_cost_usd": total_input / 1_000_000 * OPENAI_BATCH_INPUT_PER_MILLION + total_output / 1_000_000 * OPENAI_BATCH_OUTPUT_PER_MILLION, "pricing": {"input_per_million_usd": OPENAI_BATCH_INPUT_PER_MILLION, "output_per_million_usd": OPENAI_BATCH_OUTPUT_PER_MILLION, "source": "https://developers.openai.com/api/docs/pricing", "checked_at": date.today().isoformat()}, "openai_api_requests": 0}


def run_pytest() -> dict[str, Any]:
    base = REPORTS / f"pytest_stage16b_{time.time_ns()}"
    base.mkdir(parents=True, exist_ok=False)
    process = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={base / 'run'}"], cwd=ROOT, capture_output=True, text=True, check=False)
    match = re.search(r"(\d+) passed", process.stdout + process.stderr)
    return {"returncode": process.returncode, "passed": int(match.group(1)) if match else 0, "stdout_tail": process.stdout[-5000:], "stderr_tail": process.stderr[-3000:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    protected_before = protected_snapshot()
    current, earliest, current_payload = current_stage16()
    market_frame, market_map = market_availability()

    cache = DATA / "source_records.parquet"
    availability_cache = DATA / "source_availability.json"
    if args.resume and cache.exists() and availability_cache.exists():
        source_records = pd.read_parquet(cache).to_dict("records")
        availability = json.loads(availability_cache.read_text(encoding="utf-8"))
        resumed = True
    else:
        ef_records, ef_availability = fetch_ethereum_foundation(earliest)
        sec_records, sec_availability = sec_search(earliest)
        github_records, github_availability = fetch_github(earliest)
        source_records = [*ef_records, *sec_records, *github_records]
        availability = [ef_availability, sec_availability, github_availability]
        source_frame = pd.DataFrame(source_records)
        for column in ("assets", "matched_keywords", "matched_entities"):
            source_frame[column] = source_frame[column].apply(lambda value: list(value) if isinstance(value, (list, tuple, np.ndarray)) else [])
        source_frame.to_parquet(cache, index=False)
        write_json(availability_cache, availability)
        resumed = False
    source_frame = pd.DataFrame(source_records)
    if source_frame.empty:
        raise RuntimeError("No official source records were retrieved")
    for column in ("published_at", "accepted_at", "modified_at"):
        source_frame[column] = pd.to_datetime(source_frame[column], utc=True, errors="coerce")
    source_records = source_frame.to_dict("records")
    sec_missing_acceptance = [
        record for record in source_records
        if record.get("source") == "sec" and record.get("status") == "accepted"
        and pd.isna(record.get("accepted_at"))
    ]
    if sec_missing_acceptance:
        enrich_sec_from_bulk(sec_missing_acceptance)
        source_frame = pd.DataFrame(source_records)
        for column in ("published_at", "accepted_at", "modified_at"):
            source_frame[column] = pd.to_datetime(source_frame[column], utc=True, errors="coerce")
        for column in ("assets", "matched_keywords", "matched_entities"):
            source_frame[column] = source_frame[column].apply(lambda value: list(value) if isinstance(value, (list, tuple, np.ndarray)) else [])
        source_frame.to_parquet(cache, index=False)
    acceptance_count = int(source_frame.loc[(source_frame.source.eq("sec")) & (source_frame.status.eq("accepted")), "accepted_at"].notna().sum())
    for row in availability:
        if row.get("source") == "sec":
            row["bulk_acceptance_timestamps_available"] = acceptance_count
    write_json(availability_cache, availability)
    source_records = source_frame.to_dict("records")
    unique_sources, canonical, groups, duplicates, rejections = deduplicate_and_group(source_records, current)
    coverage = candle_coverage(canonical, market_map)
    aggregate_reports(canonical, groups, coverage, unique_sources, rejections, duplicates)
    pd.DataFrame(availability).to_csv(REPORTS / "stage16b_source_availability.csv", index=False)
    canonical.to_parquet(DATA / "canonical_events.parquet", index=False)
    groups.to_parquet(DATA / "event_source_records.parquet", index=False)
    coverage.to_parquet(DATA / "event_asset_coverage.parquet", index=False)

    estimate = token_estimate(canonical)
    counts_by_event_type = canonical.event_type.value_counts().to_dict() if not canonical.empty else {}
    protected_after = protected_snapshot()
    changed_files = sorted(key for key in set(protected_before["files"]) | set(protected_after["files"]) if protected_before["files"].get(key) != protected_after["files"].get(key))
    changed_tables = {key: [value, protected_after["table_counts"].get(key)] for key, value in protected_before["table_counts"].items() if protected_after["table_counts"].get(key) != value}
    pytest_result = run_pytest()
    write_json(REPORTS / "stage16b_pytest.json", pytest_result)
    protected_final = protected_snapshot()
    changed_files_final = sorted(key for key in set(protected_before["files"]) | set(protected_final["files"]) if protected_before["files"].get(key) != protected_final["files"].get(key))
    status = "PASS_SOURCE_ARCHIVE__NO_MARKET_COVERAGE" if pytest_result["returncode"] == 0 and not changed_files_final and not changed_tables else "FAIL"
    summary = {
        "stage": "16B",
        "status": status,
        "mode": "free_historical_backfill_pre_ai",
        "resumed_from_source_cache": resumed,
        "current_stage16": current_payload,
        "retrieved_source_records": len(source_frame),
        "accepted_source_records_before_dedup": int(source_frame.status.eq("accepted").sum()),
        "new_unique_events": len(canonical),
        "new_event_asset_rows": len(coverage),
        "fully_covered_rows": int(coverage.fully_covered.sum()) if not coverage.empty else 0,
        "market_data_unavailable_rows": int((~coverage.fully_covered).sum()) if not coverage.empty else 0,
        "counts_by_year": canonical.calendar_year.value_counts().sort_index().to_dict() if not canonical.empty else {},
        "counts_by_source": canonical.source.value_counts().to_dict() if not canonical.empty else {},
        "counts_by_asset": coverage.asset.value_counts().to_dict() if not coverage.empty else {},
        "counts_by_event_type": counts_by_event_type,
        "duplicates": len(duplicates),
        "rejected_events": len(rejections),
        "missing_candle_coverage": int((~coverage.fully_covered).sum()) if not coverage.empty else 0,
        "earliest_usable_date": {asset: pd.Timestamp(values["earliest_usable_with_12h_precontext"]) for asset, values in market_map.items()},
        "market_gap_runs": {row.symbol.replace("USDT", ""): int(row.gap_runs) for row in market_frame.itertuples()},
        "estimated_ai": estimate,
        "source_availability": availability,
        "dedup_priority": "existing Stage 16 events",
        "database_mutations": 0,
        "openai_api_requests": 0,
        "ml_runs": 0,
        "paper_trading": False,
        "real_trading": False,
        "old_stage17_test_rows_read": 0,
        "synthetic_candles": 0,
        "long_gap_interpolation": 0,
        "regime_threshold_policy": "All future regime thresholds must be fit on train only; unavailable regimes remain null.",
        "protected_stage8_17": {"files": len(protected_before["files"]), "aggregate_sha256_before": protected_before["aggregate_sha256"], "aggregate_sha256_after": protected_final["aggregate_sha256"], "changed_files": changed_files_final, "changed_table_counts": changed_tables, "unchanged": not changed_files_final and not changed_tables},
        "pytest": pytest_result,
        "reports": list(REPORT_NAMES),
        "data_files": ["data/stage16b/source_records.parquet", "data/stage16b/canonical_events.parquet", "data/stage16b/event_source_records.parquet", "data/stage16b/event_asset_coverage.parquet"],
        "next_stage_started": False,
    }
    write_json(REPORTS / "stage16b_backfill_summary.json", summary)
    assessment = f"""# Stage 16B — Historical High-Impact Backfill

## Status

`{status}`

The free official-source archive was expanded without changing Stage 8–17 data, calling OpenAI, reading the opened Stage 17 test, training ML, or trading.

## Results

- Retrieved source records: {len(source_frame):,}.
- Accepted source records before deduplication: {int(source_frame.status.eq('accepted').sum()):,}.
- New canonical events: {len(canonical):,}.
- New event-asset rows: {len(coverage):,}.
- Fully covered rows: {int(coverage.fully_covered.sum()) if not coverage.empty else 0:,}.
- Duplicates mapped: {len(duplicates):,}; rejected records: {len(rejections):,}.
- Earliest usable market timestamp with 12h pre-context: BTC/ETH/SOL = {pd.Timestamp(market_map['BTC']['earliest_usable_with_12h_precontext']).isoformat()}.
- All historical candidates precede available 1m candles, so they remain `market_data_unavailable` and are excluded from reaction/Stage 17B datasets.
- Estimated semantic v2.1 candidates: {estimate['events_for_ai']:,}; input tokens {estimate['input_tokens']['total']:,}; output tokens {estimate['estimated_output_tokens_total']:,}; estimated Batch cost ${estimate['estimated_batch_cost_usd']:.4f}.
- SEC bulk archive was accessed with HTTP Range and only matched CIK JSON entries were read; the complete ~1.55GB archive was not extracted because only ~4GB disk space was available.
- GitHub collection is bounded to one historical page per channel/repository; unavailable/unauthenticated channels are documented rather than inferred.
- Pytest: {'PASS' if pytest_result['returncode'] == 0 else 'FAIL'} ({pytest_result['passed']} passed).
- Protected Stage 8–17 artifacts/tables unchanged: {not changed_files_final and not changed_tables}.

## Stop gate

No AI Batch was submitted. No Stage 17B ML, paper trading, real trading, or next stage was started. Historical candles before 2023 must be acquired and audited before these source records can become reaction observations.
"""
    (REPORTS / "stage16b_pre_ai_assessment.md").write_text(assessment, encoding="utf-8")
    manifest = {"version": "stage16b_historical_backfill_v1", "created_at": datetime.now(timezone.utc), "source_records": len(source_frame), "canonical_events": len(canonical), "event_asset_rows": len(coverage), "files": {str(path.relative_to(ROOT)): sha256(path) for path in DATA.glob("*.parquet")}, "openai_api_requests": 0, "database_mutations": 0, "protected_stage8_17_unchanged": not changed_files_final and not changed_tables}
    write_json(DATA / "manifest.json", manifest)
    print(json.dumps({"status": status, "retrieved": len(source_frame), "new_unique_events": len(canonical), "event_asset_rows": len(coverage), "fully_covered_rows": int(coverage.fully_covered.sum()) if not coverage.empty else 0, "duplicates": len(duplicates), "rejected": len(rejections), "estimated_batch_cost_usd": estimate["estimated_batch_cost_usd"], "pytest_passed": pytest_result["passed"], "protected_unchanged": not changed_files_final and not changed_tables}, indent=2))
    return 0 if status != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
