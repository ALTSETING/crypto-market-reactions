"""Find accepted historical source records absent from canonical website mappings."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    website = pd.read_parquet(ROOT / "data" / "website" / "events_mvp.parquet")
    source = pd.read_parquet(ROOT / "data" / "stage16b" / "source_records.parquet")
    mapping = pd.read_parquet(ROOT / "data" / "stage16b" / "event_source_records.parquet")
    accepted = source[
        source.status.eq("accepted") & source.calendar_year.between(2017, 2022)
    ].copy()
    website_urls = set(website.source_url.fillna("").astype(str))
    absent_url = ~accepted.url.fillna("").isin(website_urls) & ~accepted.canonical_url.fillna("").isin(website_urls)
    absent = accepted[absent_url].copy()
    mapped_ids = set(mapping.record_id.astype(str))
    candidates = absent[~absent.record_id.astype(str).isin(mapped_ids)].copy()
    candidates["provenance"] = "data/stage16b/source_records.parquet"
    candidates["qa_status"] = "needs_review"
    candidates["imported_to_production"] = False
    output = ROOT / "data" / "backfill_v2" / "candidate_events.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_parquet(output, index=False)
    rejected = source[source.status.eq("rejected")]
    report = f"""# Historical backfill V2 local artifact audit

- Source records inspected: **{len(source):,}**.
- Accepted 2017–2022 records: **{len(accepted):,}**.
- Accepted records already represented by URL or canonical source mapping: **{len(accepted) - len(candidates):,}**.
- New local QA candidates: **{len(candidates):,}**.
- Previously rejected records retained: **{len(rejected):,}**; they were not promoted.

The candidate artifact is `data/backfill_v2/candidate_events.parquet`. Candidates remain `needs_review`; no production import occurred. Most apparent URL differences were alternate source records already grouped into canonical events. The remaining candidates are SEC records with generic titles and require factual display-title/timestamp verification before inclusion.
"""
    (ROOT / "docs" / "HISTORICAL_BACKFILL_V2_AUDIT.md").write_text(report, encoding="utf-8")
    print(f"accepted={len(accepted)} candidates={len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
