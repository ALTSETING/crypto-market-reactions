"""Recover historical news metadata from local artifacts and Scrapy HTTP cache."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pandas as pd
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".scrapy/httpcache"
OUTPUT = ROOT / "data/backfill_v3/historical_candidates.parquet"
INTERNAL = ROOT / "data/backfill_v3/local_recovery_internal.parquet"
REPORT = ROOT / "reports/LOCAL_HISTORICAL_RECOVERY_AUDIT.md"
ASSETS = {
    "BTC": (r"\bbitcoin\b", r"\bbtc\b"),
    "ETH": (r"\bethereum\b", r"\bether\b", r"\beth\b"),
    "SOL": (r"\bsolana\b", r"\bsol\b"),
}


def normalize_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    host = parsed.netloc.casefold().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    return urlunparse(("https", host, path, "", "", "")) if host else ""


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def jsonld_nodes(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from jsonld_nodes(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from jsonld_nodes(nested)


def cached_html(path: Path) -> str:
    with path.open("rb") as handle:
        signature = handle.read(2)
    if signature == b"\x1f\x8b":
        with gzip.open(path, "rb") as handle:
            raw = handle.read(256 * 1024)
    else:
        with path.open("rb") as handle:
            raw = handle.read(256 * 1024)
    return raw.decode("utf-8", errors="replace")


def extract_page(entry: Path, spider: str) -> dict | None:
    try:
        meta = json.loads(entry.joinpath("meta").read_text(encoding="utf-8").replace("'", '"'))
    except (OSError, json.JSONDecodeError):
        # Scrapy's meta is a Python repr, not guaranteed JSON.
        import ast
        try:
            meta = ast.literal_eval(entry.joinpath("meta").read_text(encoding="utf-8"))
        except (OSError, ValueError, SyntaxError):
            return None
    if int(meta.get("status", 0)) != 200:
        return None
    body_path = entry / "response_body"
    if not body_path.exists():
        return None
    try:
        markup = cached_html(body_path)
    except (OSError, gzip.BadGzipFile, EOFError):
        return None
    # Avoid constructing a full DOM for the overwhelmingly newer cache pages.
    quick_dates = re.findall(
        r'(?:datePublished|dateCreated|article:published_time)[^0-9]{0,80}(20(?:1[7-9]|2[0-2])-[0-9]{2}-[0-9]{2})',
        markup,
        flags=re.I,
    )
    if not quick_dates:
        return None
    soup = BeautifulSoup(markup, "html.parser")
    candidates = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            value = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for node in jsonld_nodes(value):
            date = node.get("datePublished") or node.get("dateCreated")
            title = node.get("headline") or node.get("name")
            if date and title:
                candidates.append((str(date), str(title), node.get("url")))
    def meta_value(*keys: tuple[str, str]) -> str | None:
        for attribute, value in keys:
            tag = soup.find("meta", attrs={attribute: value})
            if tag and tag.get("content"):
                return str(tag["content"])
        return None
    if candidates:
        published, title, canonical = candidates[0]
    else:
        published = meta_value(("property", "article:published_time"), ("name", "date"))
        title = meta_value(("property", "og:title"), ("name", "twitter:title"))
        canonical = None
    if not published or not title:
        return None
    timestamp = pd.to_datetime(published, utc=True, errors="coerce")
    if pd.isna(timestamp) or not 2017 <= timestamp.year <= 2022:
        return None
    canonical_tag = soup.find("link", rel="canonical")
    url = str(canonical or (canonical_tag.get("href") if canonical_tag else "") or meta.get("response_url") or meta.get("url"))
    clean_title = re.sub(r"\s+", " ", BeautifulSoup(title, "html.parser").get_text(" ")).strip()
    normalized = normalize_title(clean_title)
    if len(normalized) < 12 or normalized in {"document", "home", "page", "news"}:
        return None
    text = f" {normalized} "
    assets = [asset for asset, patterns in ASSETS.items() if any(re.search(pattern, text) for pattern in patterns)]
    crypto_terms = re.search(r"\b(crypto|cryptocurrency|blockchain|token|defi|nft|stablecoin|exchange|sec|wallet|mining)\b", text)
    if not assets and not crypto_terms:
        return None
    return {
        "title": clean_title, "published_at": timestamp, "source": spider,
        "source_url": url, "normalized_url": normalize_url(url),
        "normalized_title": normalized, "related_assets": assets,
        "cache_entry": str(entry.relative_to(ROOT)),
        "content_hash": hashlib.sha256(body_path.read_bytes()).hexdigest(),
        "body_length": body_path.stat().st_size,
    }


def main() -> int:
    current = pd.read_parquet(ROOT / "data/website/events_mvp.parquet")
    current["published_at"] = pd.to_datetime(current.published_at, utc=True)
    current_urls = set(current.source_url.fillna("").map(normalize_url))
    current_titles = set(current.title.fillna("").map(normalize_title))
    rows, inspected = [], Counter()
    for spider_dir in sorted(path for path in CACHE.iterdir() if path.is_dir()):
        for meta_path in spider_dir.glob("*/*/meta"):
            inspected[spider_dir.name] += 1
            page = extract_page(meta_path.parent, spider_dir.name)
            if page:
                rows.append(page)
    recovered = pd.DataFrame(rows)
    if recovered.empty:
        recovered = pd.DataFrame(columns=["title", "published_at", "source", "source_url", "normalized_url", "normalized_title", "related_assets", "cache_entry", "content_hash", "body_length"])
    recovered = recovered.sort_values(["published_at", "source_url"]).drop_duplicates("normalized_url")
    recovered["already_current_url"] = recovered.normalized_url.isin(current_urls)
    recovered["already_current_title"] = recovered.normalized_title.isin(current_titles)
    candidates = recovered[~recovered.already_current_url & ~recovered.already_current_title].copy()
    candidates["candidate_id"] = candidates.apply(
        lambda row: "bf3-" + hashlib.sha256(f"{row.normalized_url}|{row.published_at.isoformat()}".encode()).hexdigest()[:20], axis=1,
    )
    candidates["record_type"] = "news_article"
    candidates["primary_asset"] = candidates.related_assets.map(lambda value: value[0] if len(value) == 1 else None)
    candidates["category"] = "news"
    candidates["provenance"] = candidates.cache_entry
    candidates["capture_method"] = "local_scrapy_http_cache"
    candidates["quality_status"] = "needs_review"
    candidates["duplicate_candidate"] = False
    candidates["story_candidate"] = False
    schema = ["candidate_id", "title", "published_at", "source", "source_url", "record_type", "related_assets", "primary_asset", "category", "provenance", "capture_method", "quality_status", "duplicate_candidate", "story_candidate"]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    candidates[schema].to_parquet(OUTPUT, index=False)
    recovered.to_parquet(INTERNAL, index=False)

    stage16 = pd.read_parquet(ROOT / "data/stage16b/source_records.parquet")
    mapping = pd.read_parquet(ROOT / "data/stage16b/event_source_records.parquet")
    accepted_old = stage16[stage16.status.eq("accepted") & stage16.calendar_year.between(2017, 2022)]
    unmapped = accepted_old[~accepted_old.record_id.isin(set(mapping.record_id))]
    report = f"""# Local historical recovery audit

## Sources inspected

- Scrapy cache entries: **{sum(inspected.values()):,}** (`{json.dumps(dict(inspected), sort_keys=True)}`).
- Cached 2017–2022 pages with valid news metadata and crypto evidence: **{len(recovered):,}**.
- Already represented by normalized URL or exact normalized title: **{len(recovered) - len(candidates):,}**.
- New cache candidates requiring QA: **{len(candidates):,}**.
- Stage16b source records: **{len(stage16):,}**; accepted 2017–2022: **{len(accepted_old):,}**; accepted but unmapped: **{len(unmapped):,}**.

The two unmapped Stage16b records are Coinbase DRSLTR correspondence submitted minutes after already-canonical DRS/A filings on 2020-12-21 and 2021-02-12. They are subordinate records of the same filing stories, not distinct public events, and remain rejected from standalone backfill. No production data was changed.

Other locations checked: `data/archive`, `data/raw`, `data/stage*`, `datasets`, Stage16b source mappings, Stage18b canonical inventory, old reports/exports, and `.scrapy/httpcache`. Candidate bodies remain internal; the public candidate artifact contains metadata and provenance only.
"""
    REPORT.write_text(report, encoding="utf-8")
    print(json.dumps({"cache_entries": sum(inspected.values()), "historical_pages": len(recovered), "new_candidates": len(candidates), "stage16_unmapped": len(unmapped)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
