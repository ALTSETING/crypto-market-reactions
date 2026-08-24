"""Full source URL inventory and cache-backed title-drift audit."""

from __future__ import annotations

import ast
import gzip
import html
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
PACKAGE = REPORTS / "USER_REVIEW_PACKAGE"
CACHE = ROOT / ".scrapy/httpcache"


def normalize_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    host = parsed.netloc.casefold().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    return urlunparse(("https", host, path, "", "", "")) if host else ""


def normalize_title(value: object) -> str:
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return ""
    text = html.unescape(str(value or "")).casefold()
    text = text.replace("·", " ").replace("В·", " ")
    text = re.sub(r"\b(bitcoin price news|btc price|breaking|updated)\s*:\s*", "", text)
    text = re.sub(r"\s*[|\-]\s*(cointelegraph|coindesk|decrypt)\s*$", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = re.sub(r"\s+ethereum foundation blog\s*$", "", text)
    text = re.sub(r"\s+by\s+[a-z0-9_-]+\s+(pull request|issue)\s+\d+\s+", " ", text)
    text = re.sub(r"\s+(pull request|issue)\s+\d+\s+", " ", text)
    text = re.sub(r"\s+[a-f0-9]{6,}\s*$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def title_comparison(captured: object, current: object) -> tuple[str, float | None]:
    left, right = normalize_title(captured), normalize_title(current)
    if not right:
        return "unverified", None
    left_tokens = {token for token in left.split() if token != "release"}
    right_tokens = {token for token in right.split() if token != "release"}
    token_score = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    sequence_score = SequenceMatcher(None, left, right).ratio()
    similarity = max(token_score, sequence_score)
    if left == right or left_tokens == right_tokens:
        return "exact", similarity
    return ("minor_edit" if similarity >= 0.90 else "material_edit"), similarity


def head_markup(path: Path) -> str:
    with path.open("rb") as handle: signature = handle.read(2)
    opener = gzip.open if signature == b"\x1f\x8b" else open
    with opener(path, "rb") as handle: raw = handle.read(512 * 1024)
    return raw.decode("utf-8", errors="replace")


def extract_title(markup: str) -> str | None:
    for pattern in [r'"headline"\s*:\s*"((?:\\.|[^"\\])+)"']:
        match = re.search(pattern, markup, flags=re.I)
        if not match: continue
        value = match.group(1)
        try: value = json.loads(f'"{value}"')
        except json.JSONDecodeError: pass
        return re.sub(r"\s+", " ", html.unescape(value)).strip()
    soup = BeautifulSoup(markup, "html.parser")
    node = soup.find("meta", attrs={"property": "og:title"})
    if node and node.get("content"):
        return re.sub(r"\s+", " ", html.unescape(str(node["content"]))).strip()
    return None


def cache_index(current_urls: set[str]) -> dict[str, dict]:
    result = {}
    for meta_path in CACHE.glob("*/*/*/meta"):
        try: meta = ast.literal_eval(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, SyntaxError): continue
        raw_url = meta.get("response_url") or meta.get("url") or ""
        url = normalize_url(raw_url)
        if url not in current_urls: continue
        status = int(meta.get("status", 0))
        existing = result.get(url)
        if existing and existing.get("timestamp", 0) >= float(meta.get("timestamp", 0)): continue
        current_title = None
        body = meta_path.parent / "response_body"
        if status == 200 and body.exists():
            try: current_title = extract_title(head_markup(body))
            except (OSError, gzip.BadGzipFile, EOFError): pass
        result[url] = {
            "http_status": status, "final_url": raw_url,
            "verified_at": datetime.fromtimestamp(float(meta.get("timestamp", 0)), tz=timezone.utc).isoformat(),
            "current_source_title": current_title, "timestamp": float(meta.get("timestamp", 0)),
            "verification_status": {200: "verified_200", 301: "redirect", 302: "redirect", 403: "blocked_403", 429: "rate_limited_429", 404: "not_found_404", 410: "gone_410"}.get(status, "unknown"),
            "verification_method": "scrapy_http_cache",
        }
    return result


def main() -> int:
    PACKAGE.mkdir(parents=True, exist_ok=True)
    live = pd.read_parquet(ROOT / "data/website/backups/pre_news_quality_v3/supabase_events_post_reaction_v2.parquet")
    live["published_at"] = pd.to_datetime(live.published_at, utc=True)
    live["normalized_url"] = live.source_url.map(normalize_url)
    cache = cache_index(set(live.normalized_url))
    source_records = pd.read_parquet(ROOT / "data/stage16b/source_records.parquet")
    accepted_urls = set(source_records.loc[source_records.status.eq("accepted"), "url"].fillna("").map(normalize_url)) | set(source_records.loc[source_records.status.eq("accepted"), "canonical_url"].fillna("").map(normalize_url))
    sampled = pd.read_csv(REPORTS / "SOURCE_VERIFICATION_V2_SAMPLE.csv").set_index("event_id")
    reaction_cols = [f"{asset}_{h}" for asset in ("btc", "eth", "sol") for h in ("1m", "5m", "15m", "1h", "4h", "24h")]
    live["max_abs_reaction"] = live[reaction_cols].abs().max(axis=1)
    rows = []
    for event in live.itertuples(index=False):
        data = cache.get(event.normalized_url)
        if data:
            row = {**data}
        elif event.event_id in sampled.index:
            sample = sampled.loc[event.event_id]
            status = int(sample.source_http_status) if pd.notna(sample.source_http_status) else None
            row = {
                "http_status": status, "final_url": sample.source_final_url,
                "verified_at": sample.source_last_verified_at, "current_source_title": sample.current_source_title,
                "verification_status": {200: "verified_200", 403: "blocked_403", 429: "rate_limited_429", 404: "not_found_404", 410: "gone_410"}.get(status, "unknown"),
                "verification_method": "source_verification_v2_live_sample",
            }
        elif event.normalized_url in accepted_urls:
            row = {"http_status": None, "final_url": event.source_url, "verified_at": None, "current_source_title": None, "verification_status": "verified_source_artifact", "verification_method": "stage16b_accepted_source_record"}
        else:
            row = {"http_status": None, "final_url": event.source_url, "verified_at": None, "current_source_title": None, "verification_status": "unknown", "verification_method": "unverified"}
        title_status, similarity = title_comparison(event.title, row.get("current_source_title"))
        rows.append({
            "event_id": event.event_id, "source": event.source, "source_url": event.source_url,
            "final_url": row.get("final_url"), "http_status": row.get("http_status"),
            "verification_status": row["verification_status"], "verified_at": row.get("verified_at"),
            "redirect_chain": "" if row.get("final_url") in {None, event.source_url} else f"{event.source_url} -> {row.get('final_url')}",
            "verification_method": row["verification_method"], "captured_title": event.title,
            "current_source_title": row.get("current_source_title"), "title_verified_at": row.get("verified_at"),
            "title_match_status": title_status, "title_similarity": similarity,
            "published_at": event.published_at, "importance": event.importance,
            "max_abs_reaction": event.max_abs_reaction,
        })
    audit = pd.DataFrame(rows)
    audit.to_parquet(REPORTS / "SOURCE_URL_AUDIT_V2.parquet", index=False)

    material = audit[audit.title_match_status.eq("material_edit")].copy()
    material["recommended_action"] = "REVIEW_MATERIAL_TITLE_EDIT"
    material["user_decision"] = ""
    material.to_csv(REPORTS / "TITLE_DRIFT_MANUAL_REVIEW.csv", index=False)
    material.head(100).to_csv(PACKAGE / "title_drift.csv", index=False)
    blocked = audit[audit.verification_status.isin(["blocked_403", "rate_limited_429", "unknown"])].copy()
    blocked["priority"] = (
        blocked.published_at.dt.year.le(2022).astype(int) * 4 +
        blocked.importance.fillna(0).astype(float).gt(70).astype(int) * 3 +
        blocked.max_abs_reaction.fillna(0).astype(float).gt(10).astype(int) * 2 +
        blocked.title_match_status.ne("exact").astype(int)
    )
    blocked["recommended_action"] = "MANUAL_OPEN"
    blocked["user_decision"] = ""
    blocked.sort_values(["priority", "published_at"], ascending=[False, True]).head(100).to_csv(REPORTS / "URL_MANUAL_REVIEW_NEEDED.csv", index=False)
    blocked.sort_values(["priority", "published_at"], ascending=[False, True]).head(100).to_csv(PACKAGE / "blocked_urls.csv", index=False)

    statuses = audit.verification_status.value_counts().to_dict()
    titles = audit.title_match_status.value_counts().to_dict()
    report = f"""# Source URL Audit V2

- Existing production URLs inventoried: **{len(audit):,}**.
- Statuses: `{json.dumps(statuses, sort_keys=True)}`.
- Title verification: `{json.dumps(titles, sort_keys=True)}`.
- Material title-drift candidates: **{len(material):,}**.
- Manual URL package: **{min(100, len(blocked)):,}** prioritized rows.

Publisher pages already present in the Scrapy cache use their captured HTTP status and capture timestamp; this avoids re-hammering thousands of news pages. Stage16b accepted official-source records retain a distinct `verified_source_artifact` status rather than falsely claiming a new HTTP 200. HTTP 403/429 are classified as access restrictions, not dead links. No CAPTCHA, proxy, paywall, login, or anti-bot bypass was attempted. CoinDesk's current sitemap request returned 429/Vercel Security Checkpoint and was not retried.
"""
    (ROOT / "docs/SOURCE_URL_AUDIT_V2.md").write_text(report, encoding="utf-8")
    summary = {"urls_checked": len(audit), "statuses": statuses, "title_statuses": titles, "material_title_drift": len(material), "manual_urls": min(100, len(blocked))}
    (REPORTS / "SOURCE_URL_AUDIT_V2_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
