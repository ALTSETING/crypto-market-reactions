"""Controlled, resumable 2017–2022 news backfill from publisher-native archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data/backfill_v3"
ARCHIVE_ROWS = OUT_DIR / "publisher_archive_inventory.parquet"
FETCH_ROWS = OUT_DIR / "publisher_page_verification.parquet"
OUTPUT = OUT_DIR / "historical_candidates.parquet"
USER_AGENT = "CryptoMarketReactions historical dataset audit (+contact: denis@example.com)"
ASSETS = {
    "BTC": (r"\bbitcoin\b", r"\bbtc\b"),
    "ETH": (r"\bethereum\b", r"\bether\b", r"\beth\b"),
    "SOL": (r"\bsolana\b", r"\bsol\b"),
}
SIGNAL = re.compile(
    r"\b(hack(?:ed)?|exploit|attack|breach|launch|mainnet|fork|upgrade|merge|halving|etf|sec|cftc|"
    r"lawsuit|sues?|charge[sd]?|arrest|ban(?:ned)?|approve[sd]?|reject(?:ed|s)?|bankrupt(?:cy)?|"
    r"collapse|acqui(?:re[sd]?|sition)|partner(?:ship)?|regulat(?:ion|or|ory)|outage|fund|filing|"
    r"ruling|settle(?:ment|s|d)?|record high|all.time high|crash|surge|plunge|exchange|wallet|"
    r"stablecoin|defi|ico|nft|ftx|terra|luna|binance|coinbase|microstrategy)\b",
    re.I,
)
LOW_VALUE = re.compile(r"\b(price analysis|top [0-9]+|what is|explained|prediction|watch these|how to buy)\b", re.I)


def normalize_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    host = parsed.netloc.casefold().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    return urlunparse(("https", host, path, "", "", "")) if host else ""


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def assets_for(title: str) -> list[str]:
    text = f" {normalize_title(title)} "
    return [asset for asset, patterns in ASSETS.items() if any(re.search(pattern, text) for pattern in patterns)]


def score(title: str) -> int:
    return 5 * len(assets_for(title)) + 4 * len(SIGNAL.findall(title)) - (10 if LOW_VALUE.search(title) else 0)


class GentleSession:
    def __init__(self, delay: float):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})
        self.delay = delay
        self.last_request = 0.0

    def get(self, url: str, timeout: int = 60) -> requests.Response:
        wait = self.delay - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.session.get(url, timeout=timeout, allow_redirects=True)
        self.last_request = time.monotonic()
        return response


def cointelegraph_inventory(client: GentleSession, stride: int) -> list[dict]:
    rows = []
    for page in range(1150, 2321, stride):
        response = client.get(f"https://cointelegraph.com/all-articles/editorial?page={page}")
        if response.status_code in {403, 429}:
            rows.append({"source": "cointelegraph", "archive_page": page, "http_status": response.status_code})
            break
        if response.status_code != 200:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for article in soup.select("article[data-testid=all-articles-page__result-item]"):
            link = article.select_one('a[href^="/news/"]')
            title_node = article.select_one("[data-testid=article-card__title]")
            date_node = article.select_one("[data-testid=article-card__published-at]")
            if not link or not title_node or not date_node:
                continue
            published = pd.to_datetime(date_node.get_text(" ", strip=True), utc=True, errors="coerce")
            if pd.isna(published) or not 2017 <= published.year <= 2022:
                continue
            title = title_node.get_text(" ", strip=True)
            rows.append({
                "source": "cointelegraph", "title": title, "published_at": published,
                "source_url": urljoin("https://cointelegraph.com", link.get("href")),
                "archive_page": page, "http_status": 200, "selection_score": score(title),
                "capture_method": f"publisher_archive_stride_{stride}",
            })
    return rows


def decrypt_sitemap_inventory(client: GentleSession) -> list[dict]:
    index = client.get("https://decrypt.co/sitemap_index.xml")
    if index.status_code != 200:
        return [{"source": "decrypt", "http_status": index.status_code}]
    root = ET.fromstring(index.text)
    sitemap_urls = []
    for node in root.findall("{*}sitemap"):
        loc = node.find("{*}loc")
        lastmod = node.find("{*}lastmod")
        if loc is None or lastmod is None:
            continue
        changed = pd.to_datetime(lastmod.text, utc=True, errors="coerce")
        if pd.notna(changed) and 2019 <= changed.year <= 2022:
            sitemap_urls.append(loc.text)
    rows = []
    for sitemap_url in sitemap_urls:
        response = client.get(sitemap_url)
        if response.status_code != 200:
            rows.append({"source": "decrypt", "source_url": sitemap_url, "http_status": response.status_code})
            continue
        page = ET.fromstring(response.text)
        for node in page.findall("{*}url"):
            loc, lastmod = node.find("{*}loc"), node.find("{*}lastmod")
            if loc is None or lastmod is None:
                continue
            published_hint = pd.to_datetime(lastmod.text, utc=True, errors="coerce")
            if pd.isna(published_hint) or not 2019 <= published_hint.year <= 2022:
                continue
            slug_title = urlparse(loc.text).path.rsplit("/", 1)[-1].replace("-", " ")
            rows.append({
                "source": "decrypt", "title": slug_title, "published_at": published_hint,
                "source_url": loc.text, "archive_page": sitemap_url, "http_status": 200,
                "selection_score": score(slug_title), "capture_method": "publisher_sitemap",
            })
    return rows


def extract_jsonld(markup: str) -> tuple[str | None, pd.Timestamp | None]:
    soup = BeautifulSoup(markup, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            value = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        queue = value if isinstance(value, list) else [value]
        while queue:
            node = queue.pop(0)
            if not isinstance(node, dict):
                continue
            title = node.get("headline") or node.get("name")
            date = node.get("datePublished") or node.get("dateCreated")
            if title and date:
                return str(title), pd.to_datetime(date, utc=True, errors="coerce")
            for nested in node.values():
                if isinstance(nested, dict): queue.append(nested)
                elif isinstance(nested, list): queue.extend(item for item in nested if isinstance(item, dict))
    return None, None


def verify_pages(client: GentleSession, selected: pd.DataFrame) -> pd.DataFrame:
    existing = pd.read_parquet(FETCH_ROWS) if FETCH_ROWS.exists() else pd.DataFrame()
    done = set(existing.source_url) if not existing.empty else set()
    rows = existing.to_dict("records") if not existing.empty else []
    blocked = 0
    for index, row in enumerate(selected.to_dict("records"), 1):
        if row["source_url"] in done:
            continue
        response = client.get(row["source_url"])
        status = response.status_code
        item = {"source_url": row["source_url"], "http_status": status, "final_url": response.url}
        if status == 200:
            title, published = extract_jsonld(response.text)
            item.update({"title": title, "published_at": published, "verification_status": "verified_200"})
            blocked = 0
        else:
            item["verification_status"] = {403: "blocked_403", 429: "rate_limited_429", 404: "not_found_404", 410: "gone_410"}.get(status, "unknown")
            blocked = blocked + 1 if status in {403, 429} else 0
        rows.append(item)
        if index % 25 == 0:
            pd.DataFrame(rows).to_parquet(FETCH_ROWS, index=False)
        if blocked >= 3:
            break
    result = pd.DataFrame(rows)
    result.to_parquet(FETCH_ROWS, index=False)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-year-source", type=int, default=100)
    parser.add_argument("--ct-stride", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.45)
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = GentleSession(args.delay)

    if ARCHIVE_ROWS.exists():
        inventory = pd.read_parquet(ARCHIVE_ROWS)
    else:
        rows = cointelegraph_inventory(client, args.ct_stride)
        rows.extend(decrypt_sitemap_inventory(client))
        inventory = pd.DataFrame(rows)
        inventory["archive_page"] = inventory["archive_page"].astype("string")
        inventory.to_parquet(ARCHIVE_ROWS, index=False)
    usable = inventory[
        inventory.title.notna() & inventory.published_at.notna() & inventory.source_url.notna()
    ].copy()
    usable["published_at"] = pd.to_datetime(usable.published_at, utc=True)
    usable["year"] = usable.published_at.dt.year
    usable["normalized_url"] = usable.source_url.map(normalize_url)
    usable["normalized_title"] = usable.title.map(normalize_title)
    usable = usable.drop_duplicates("normalized_url")
    usable = usable[usable.selection_score.gt(0) & ~usable.title.str.contains(LOW_VALUE, na=False)]
    selected = (
        usable.sort_values(["source", "year", "selection_score"], ascending=[True, True, False])
        .groupby(["source", "year"], group_keys=False).head(args.per_year_source)
    )

    # Publisher archive cards and sitemaps are discovery aids only.  The page
    # JSON-LD is required for an exact publication timestamp before reactions
    # can be calculated.
    verified = verify_pages(client, selected) if not selected.empty else pd.DataFrame()
    decrypt_selected = selected[selected.source.eq("decrypt")]
    decrypt = decrypt_selected.drop(columns=["title", "published_at"], errors="ignore").merge(
        verified[["source_url", "title", "published_at", "http_status", "verification_status", "final_url"]],
        on="source_url", how="left", suffixes=("", "_verified"), validate="one_to_one",
    )
    decrypt = decrypt[decrypt.http_status_verified.eq(200) & decrypt.title.notna() & decrypt.published_at.notna()].copy()
    decrypt["published_at"] = pd.to_datetime(decrypt.published_at, utc=True)
    decrypt = decrypt[decrypt.published_at.dt.year.between(2019, 2022)]
    ct_selected = selected[selected.source.eq("cointelegraph")]
    ct = ct_selected.drop(columns=["title", "published_at"], errors="ignore").merge(
        verified[["source_url", "title", "published_at", "http_status", "verification_status", "final_url"]],
        on="source_url", how="left", suffixes=("", "_verified"), validate="one_to_one",
    )
    ct = ct[ct.http_status_verified.eq(200) & ct.title.notna() & ct.published_at.notna()].copy()
    ct["published_at"] = pd.to_datetime(ct.published_at, utc=True)
    ct = ct[ct.published_at.dt.year.between(2017, 2022)]
    combined = pd.concat([ct, decrypt], ignore_index=True, sort=False)

    local_path = OUT_DIR / "local_recovery_internal.parquet"
    if local_path.exists():
        local = pd.read_parquet(local_path)
        local = local[~local.already_current_url & ~local.already_current_title].copy()
        local["verification_status"] = "verified_200_local_cache"
        local["final_url"] = local.source_url
        local["selection_score"] = local.title.map(score)
        local["capture_method"] = "local_scrapy_http_cache"
        combined = pd.concat([combined, local], ignore_index=True, sort=False)

    current = pd.read_parquet(ROOT / "data/website/events_mvp.parquet")
    current_urls = set(current.source_url.fillna("").map(normalize_url))
    current_titles = set(current.title.fillna("").map(normalize_title))
    combined["normalized_url"] = combined.source_url.map(normalize_url)
    combined["normalized_title"] = combined.title.map(normalize_title)
    combined = combined[
        ~combined.normalized_url.isin(current_urls) & ~combined.normalized_title.isin(current_titles)
    ].sort_values(["published_at", "source_url"]).drop_duplicates("normalized_url")
    combined["candidate_id"] = combined.apply(
        lambda row: "bf3-" + hashlib.sha256(f"{row.normalized_url}|{pd.Timestamp(row.published_at).isoformat()}".encode()).hexdigest()[:20], axis=1,
    )
    combined["record_type"] = "news_article"
    combined["related_assets"] = combined.title.map(assets_for)
    combined["primary_asset"] = combined.related_assets.map(lambda values: values[0] if len(values) == 1 else None)
    combined["category"] = "news"
    combined["provenance"] = combined.apply(lambda row: f"{row.source}:{row.capture_method}", axis=1)
    combined["quality_status"] = "accepted"
    combined["duplicate_candidate"] = False
    combined["story_candidate"] = False
    schema = ["candidate_id", "title", "published_at", "source", "source_url", "record_type", "related_assets", "primary_asset", "category", "provenance", "capture_method", "quality_status", "duplicate_candidate", "story_candidate"]
    combined[schema].to_parquet(OUTPUT, index=False)
    summary = {
        "archive_rows": len(inventory), "selected": len(selected), "accepted_candidates": len(combined),
        "by_year": combined.assign(year=pd.to_datetime(combined.published_at, utc=True).dt.year).year.value_counts().sort_index().to_dict(),
        "by_source": combined.source.value_counts().to_dict(),
        "fetch_statuses": verified.verification_status.value_counts(dropna=False).to_dict() if not verified.empty else {},
    }
    (ROOT / "reports/HISTORICAL_WEB_BACKFILL_V3.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
