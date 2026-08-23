"""Shared article parser used by every news spider."""
from datetime import datetime, timezone
from hashlib import sha256
import trafilatura
from bs4 import BeautifulSoup
from crawler.parsers.asset_detector import detect_assets
from crawler.parsers.jsonld_parser import find_jsonld_value
from crawler.parsers.publication_time_parser import parse_publication_time

def parse_article(html: str, url: str, source: str, discovered_at: datetime | None = None) -> dict:
    """Extract normalized fields from article HTML without site-specific logic."""
    soup = BeautifulSoup(html, "lxml")
    body = (trafilatura.extract(html, include_comments=False, include_tables=False) or "").strip()
    if not body:
        article = soup.find("article")
        body = article.get_text(" ", strip=True) if article else ""
    title = (find_jsonld_value(html, "headline") or (soup.title.string if soup.title else "") or "").strip()
    canonical = soup.find("link", rel="canonical")
    author_tag = soup.find("meta", attrs={"name": "author"})
    author = find_jsonld_value(html, "author") or (str(author_tag.get("content")) if author_tag and author_tag.get("content") else None)
    timestamp = parse_publication_time(html)
    now = datetime.now(timezone.utc)
    return {"source": source, "url": url, "canonical_url": canonical.get("href") if canonical else None, "title": title, "body": body, "author": author, "published_at": timestamp.published_at if timestamp else None, "modified_at": None, "discovered_at": discovered_at or now, "crawled_at": now, "published_at_raw": timestamp.raw if timestamp else None, "time_source": timestamp.source if timestamp else "missing", "time_confidence": timestamp.confidence if timestamp else 0.0, "content_hash": sha256(body.encode("utf-8")).hexdigest(), "assets": detect_assets(title, body)}
