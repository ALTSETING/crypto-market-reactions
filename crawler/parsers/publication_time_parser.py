"""Publication timestamp extraction with explicit confidence levels."""
from dataclasses import dataclass
from datetime import datetime, timezone
import dateparser
from bs4 import BeautifulSoup
from trafilatura import extract_metadata
from crawler.parsers.jsonld_parser import find_jsonld_value

@dataclass(frozen=True)
class PublicationTime:
    published_at: datetime
    raw: str
    source: str
    confidence: float

def _utc(raw: str, now: datetime | None = None) -> datetime | None:
    parsed = dateparser.parse(raw, settings={"RETURN_AS_TIMEZONE_AWARE": True, "TO_TIMEZONE": "UTC", "TIMEZONE": "UTC"})
    if parsed is None:
        return None
    parsed = parsed.astimezone(timezone.utc)
    return None if parsed > (now or datetime.now(timezone.utc)) else parsed

def parse_publication_time(html: str, now: datetime | None = None) -> PublicationTime | None:
    """Extract first-publication time in priority order; never use dateModified."""
    soup = BeautifulSoup(html, "lxml")
    primary = soup.find("meta", attrs={"property": "article:published_time"})
    candidates: list[tuple[str | None, str, float]] = [(find_jsonld_value(html, "datePublished"), "json_ld", 1.0), (primary.get("content") if primary else None, "meta_tag", 0.95)]
    for attrs in ({"name": "publish-date"}, {"name": "publication_date"}, {"name": "date"}, {"itemprop": "datePublished"}):
        tag = soup.find("meta", attrs=attrs)
        candidates.append((tag.get("content") if tag else None, "meta_tag", 0.95))
    tag = soup.find("time", attrs={"datetime": True})
    candidates.append((tag.get("datetime") if tag else None, "html_time", 0.90))
    for raw, source, confidence in candidates:
        if raw and (parsed := _utc(str(raw), now)):
            return PublicationTime(parsed, str(raw), source, confidence)
    try:
        metadata = extract_metadata(html)
        raw = metadata.date if metadata else None
    except Exception:
        raw = None
    if raw and (parsed := _utc(raw, now)):
        return PublicationTime(parsed, raw, "trafilatura", 0.70)
    return None
