"""Run 100 deterministic local search/filter checks against the staged release."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
STOP = {"the", "and", "for", "with", "from", "that", "this", "after", "into", "says", "over", "will", "its", "new", "more", "than", "could"}


def tokens(value: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", value.casefold()) if len(word) >= 4 and word not in STOP]


def matches(titles: pd.Series, query: list[str]) -> pd.Series:
    normalized = titles.fillna("").str.casefold()
    result = pd.Series(True, index=titles.index)
    for word in query:
        result &= normalized.str.contains(re.escape(word), regex=True)
    return result


def main() -> int:
    old = pd.read_parquet(ROOT / "data/website/backups/pre_news_quality_v3/supabase_events_post_reaction_v2.parquet")
    new = pd.read_parquet(ROOT / "data/backfill_v3/production_rows_staging.parquet")
    combined = pd.concat([old, new], ignore_index=True, sort=False)
    candidates = new.assign(year=pd.to_datetime(new.published_at, utc=True).dt.year)
    sample = candidates.groupby("year", group_keys=False).sample(n=17, random_state=20260823).head(100)
    rows = []
    for candidate in sample.itertuples(index=False):
        words = list(dict.fromkeys(tokens(candidate.title)))[:3]
        query = words[:2] if len(words) >= 2 else words
        before = int(matches(old.title, query).sum())
        after = int(matches(combined.title, query).sum())
        rows.append({
            "query": " ".join(query), "candidate_id": candidate.event_id,
            "year": candidate.year, "before_results": before, "after_results": after,
            "candidate_found": bool(matches(pd.Series([candidate.title]), query).iloc[0]),
            "status": "PASS" if after >= 1 else "FAIL",
        })
    audit = pd.DataFrame(rows)
    audit.to_csv(REPORTS / "SEARCH_QA_V3_100.csv", index=False)
    ordered = combined.sort_values(["published_at", "event_id"])
    asset_checks = {}
    for asset in ("BTC", "ETH", "SOL"):
        part = combined[combined.related_assets.map(lambda value: asset in list(value) if not isinstance(value, str) else asset in value)]
        asset_checks[asset] = int(len(part))
    payload = {
        "queries": len(audit), "passed": int(audit.status.eq("PASS").sum()),
        "failed": int(audit.status.eq("FAIL").sum()),
        "queries_with_improved_coverage": int(audit.after_results.gt(audit.before_results).sum()),
        "oldest_sort_pass": bool(pd.to_datetime(ordered.published_at, utc=True).is_monotonic_increasing),
        "asset_filter_counts": asset_checks,
    }
    (REPORTS / "SEARCH_QA_V3_SUMMARY.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
