"""Controlled external verification of a deterministic 200-event sample."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "data" / "website" / "events_mvp.parquet"
REPORT = ROOT / "reports" / "SOURCE_VERIFICATION_V2_SAMPLE.csv"
SUMMARY = ROOT / "reports" / "SOURCE_VERIFICATION_V2_SUMMARY.json"
SEED = 20260823
SAMPLE_SIZE = 200
USER_AGENT = "CryptoReactionDataQualityAudit/2.0 (+source verification; non-aggressive)"


def choose_sample(events: pd.DataFrame) -> pd.DataFrame:
    frame = events.copy()
    frame["year"] = pd.to_datetime(frame.published_at, utc=True).dt.year
    frame["stratum"] = frame.source.astype(str) + "|" + frame.year.astype(str)
    groups = [part.sample(frac=1, random_state=SEED) for _, part in frame.groupby("stratum")]
    rows = []
    position = 0
    while len(rows) < min(SAMPLE_SIZE, len(frame)):
        progressed = False
        for group in groups:
            if position < len(group):
                rows.append(group.iloc[position])
                progressed = True
                if len(rows) == SAMPLE_SIZE:
                    break
        if not progressed:
            break
        position += 1
    return pd.DataFrame(rows).reset_index(drop=True)


def jsonld_values(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        graph = value.get("@graph")
        return [value, *(graph if isinstance(graph, list) else [])]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def extract_metadata(html: str) -> tuple[str | None, str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    title = None
    published = None
    modified = None
    for selector, attribute in (
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
    ):
        node = soup.select_one(selector)
        if node and node.get(attribute):
            title = str(node.get(attribute)).strip()
            break
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    for selector in ('meta[property="article:published_time"]', 'meta[name="date"]'):
        node = soup.select_one(selector)
        if node and node.get("content"):
            published = str(node.get("content")).strip()
            break
    node = soup.select_one('meta[property="article:modified_time"]')
    if node and node.get("content"):
        modified = str(node.get("content")).strip()
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for item in jsonld_values(parsed):
            title = title or item.get("headline") or item.get("name")
            published = published or item.get("datePublished")
            modified = modified or item.get("dateModified")
    return title, published, modified


def verify(row: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    output = dict(row)
    output.update({
        "source_http_status": None, "source_final_url": None, "current_source_title": None,
        "current_published_at": None, "current_modified_at": None, "redirected": False,
        "error": None, "source_last_verified_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        response = requests.get(
            str(row["source_url"]),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=(5, 15),
            allow_redirects=True,
        )
        output["source_http_status"] = response.status_code
        output["source_final_url"] = response.url
        output["redirected"] = response.url.rstrip("/") != str(row["source_url"]).rstrip("/")
        if response.status_code == 200 and "html" in response.headers.get("content-type", "").lower():
            title, published, modified = extract_metadata(response.text[:2_000_000])
            output["current_source_title"] = title
            output["current_published_at"] = published
            output["current_modified_at"] = modified
    except requests.RequestException as exc:
        output["error"] = type(exc).__name__ + ": " + re.sub(r"\s+", " ", str(exc))[:300]
    output["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return output


def main() -> int:
    events = pd.read_parquet(EVENTS)
    sample = choose_sample(events)[["event_id", "title", "published_at", "source", "source_url", "related_assets"]]
    rows = []
    # Four workers is intentionally conservative across publisher hosts.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(verify, row) for row in sample.to_dict("records")]
        for future in as_completed(futures):
            rows.append(future.result())
    result = pd.DataFrame(rows).sort_values("event_id")
    result["publication_difference_seconds"] = (
        pd.to_datetime(result.current_published_at, utc=True, errors="coerce")
        - pd.to_datetime(result.published_at, utc=True, errors="coerce")
    ).dt.total_seconds()
    result["title_changed"] = (
        result.current_source_title.notna()
        & result.current_source_title.str.strip().str.casefold().ne(result.title.str.strip().str.casefold())
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(REPORT, index=False)
    statuses = result.source_http_status.fillna("timeout_or_error").astype(str).value_counts().to_dict()
    summary = {
        "sample_size": len(result),
        "http_status_counts": statuses,
        "redirected_urls": int(result.redirected.sum()),
        "current_titles_captured": int(result.current_source_title.notna().sum()),
        "title_drift_rows": int(result.title_changed.sum()),
        "publication_timestamps_captured": int(result.current_published_at.notna().sum()),
        "publication_timestamp_exact_matches": int(result.publication_difference_seconds.abs().le(1).sum()),
        "errors": int(result.error.notna().sum()),
        "all_url_audit_status": "pending_non_aggressive_batches",
    }
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
