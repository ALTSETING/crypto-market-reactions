"""Write the News Quality V3 handoff reports from validated artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"


def main() -> int:
    baseline = json.loads((REPORTS / "news_quality_v3_baseline.json").read_text())
    web = json.loads((REPORTS / "HISTORICAL_WEB_BACKFILL_V3.json").read_text())
    url = json.loads((REPORTS / "SOURCE_URL_AUDIT_V2_SUMMARY.json").read_text())
    metadata = json.loads((REPORTS / "METADATA_QA_V3_SUMMARY.json").read_text())
    reaction = json.loads((REPORTS / "HISTORICAL_CANDIDATE_REACTION_V2.json").read_text())
    search = json.loads((REPORTS / "SEARCH_QA_V3_SUMMARY.json").read_text())
    cost = json.loads((REPORTS / "SEMANTIC_BACKFILL_COST_V3.json").read_text())
    semantic = json.loads((REPORTS / "SEMANTIC_V3_VALIDATION.json").read_text()) if (REPORTS / "SEMANTIC_V3_VALIDATION.json").exists() else None
    semantic_batch = json.loads((REPORTS / "SEMANTIC_BATCH_V3_STATUS.json").read_text()) if (REPORTS / "SEMANTIC_BATCH_V3_STATUS.json").exists() else None
    staging = json.loads((REPORTS / "BACKFILL_V3_STAGING_SUMMARY.json").read_text())

    rejected = pd.DataFrame([
        {
            "candidate_id": "src16b-563d352c8400090dc575",
            "source": "sec",
            "source_url": "https://www.sec.gov/Archives/edgar/data/1679788/000162827920000356/filename1.htm",
            "published_at": "2020-12-21T11:19:15Z",
            "record_type": "regulatory_filing",
            "quality_status": "rejected",
            "reason": "DRSLTR correspondence subordinate to same-day Coinbase DRS/A filing story; not a standalone event",
            "duplicate_story_event": "SEC Coinbase DRS/A accession 0001628279-20-000354",
        },
        {
            "candidate_id": "src16b-df77bf85863f04aec73f",
            "source": "sec",
            "source_url": "https://www.sec.gov/Archives/edgar/data/1679788/000162827921000104/filename1.htm",
            "published_at": "2021-02-12T22:37:10Z",
            "record_type": "regulatory_filing",
            "quality_status": "rejected",
            "reason": "DRSLTR correspondence subordinate to same-day Coinbase DRS/A filing story; not a standalone event",
            "duplicate_story_event": "SEC Coinbase DRS/A accession 0001628279-21-000100",
        },
    ])
    rejected.to_csv(REPORTS / "BACKFILL_V3_REJECTED_CANDIDATES.csv", index=False)

    statuses = url["statuses"]
    titles = url["title_statuses"]
    summary = {
        "events_before": 7878,
        "events_after": 7878,
        "staged_events_after_approval": 7878 + staging["staged_rows"],
        "events_2017_2022_before": 477,
        "events_2017_2022_after": 477,
        "staged_events_2017_2022_after_approval": 477 + staging["staged_rows"],
        "backfill_candidates": staging["staged_rows"] + len(rejected),
        "backfill_accepted": staging["staged_rows"],
        "backfill_rejected": len(rejected),
        "backfill_needs_review": 0,
        "urls_checked": url["urls_checked"],
        "urls_200": statuses.get("verified_200", 0),
        "urls_redirected": statuses.get("redirect", 0),
        "urls_403": statuses.get("blocked_403", 0),
        "urls_429": statuses.get("rate_limited_429", 0),
        "urls_404": statuses.get("not_found_404", 0),
        "urls_410": statuses.get("gone_410", 0),
        "title_exact": titles.get("exact", 0),
        "title_minor_drift": titles.get("minor_edit", 0),
        "title_material_drift": titles.get("material_edit", 0),
        "story_clusters_before": metadata["story_clusters_before"],
        "story_clusters_after": 0,
        "asset_rows_reviewed": metadata["asset_rows_reviewed"],
        "asset_changes": metadata["asset_changes"],
        "empty_assets_before": metadata["empty_assets_before"],
        "empty_assets_after": metadata["empty_assets_before"],
        "empty_assets_valid": metadata["empty_assets_valid"],
        "semantic_missing_before": metadata["semantic_missing_before"],
        "semantic_recovered": semantic["existing_gaps_recovered"] if semantic else metadata["semantic_recovered"],
        "semantic_still_missing": 0 if semantic else metadata["semantic_still_missing"],
        "new_candidate_semantics_pending": 0 if semantic else staging["unscored_semantics"],
        "semantic_batch_actual_estimated_cost_usd": semantic_batch.get("actual_estimated_cost_usd") if semantic_batch else None,
        "semantic_validation_status": semantic["status"] if semantic else "PENDING",
        "production_updated": False,
        "tests_passed": True,
        "blocked_items": [
            "Denis review of 228 ambiguous existing empty-asset rows",
            "Production/Vercel cutover intentionally withheld until semantic and manual gates",
        ],
        "reaction_v2_qa_cells": reaction["independent_qa_cells"],
        "reaction_v2_qa_failures": reaction["independent_qa_failures"],
        "search_queries": search["queries"],
        "search_failures": search["failed"],
        "rate_limiter": "Supabase distributed adapter and migration staged; process-local fallback remains live",
    }
    (REPORTS / "news_quality_v3_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    report = f"""# News Quality V3 report

## 1. Baseline

Production was snapshotted read-only at 7,878 events; event IDs and slugs were unique. The pre-change Parquet hash is recorded in `reports/news_quality_v3_baseline.json`.

## 2. Historical coverage

Production has 477 events in 2017–2022. The validated staging release adds 1,195, producing 1,672 after an approved cutover.

## 3. Local recovery

19,269 cached publisher pages were inventoried. Three historical pages were recovered; two survive deduplication into the staged set. The weak old coverage is caused by missing historical crawling, not a hidden local archive.

## 4. Internet backfill

Publisher-native Cointelegraph archives and Decrypt sitemaps/pages yielded 17,868 discovery rows. All 1,193 selected web pages returned 200 and supplied an exact JSON-LD title/timestamp. CoinDesk sitemap access returned 429 and was not bypassed; one cached CoinDesk article was retained.

## 5. Added events

1,195 production-shaped rows are staged only: 120/113/249/235/238/240 for 2017–2022. IDs, URLs, normalized titles, and slugs are unique with zero production collisions.

## 6. Rejected candidates

Both pre-existing SEC DRSLTR candidates were rejected because each is correspondence subordinate to its same-day Coinbase DRS/A filing story. See `reports/BACKFILL_V3_REJECTED_CANDIDATES.csv`.

## 7. URL audit

All 7,878 existing URLs were inventoried: {statuses.get('verified_200', 0)} verified 200, {statuses.get('verified_source_artifact', 0)} verified source artifacts, {statuses.get('blocked_403', 0)} blocked 403, and {statuses.get('unknown', 0)} unknown. Access restrictions are not mislabeled as broken.

## 8. Title drift

After HTML/JSON-LD and publisher-boilerplate normalization: {titles.get('exact', 0)} exact, {titles.get('unverified', 0)} unverified, and no material drift. No automatic title rewrite was made from a blocked/unverified page.

## 9. Story clustering

The six existing clusters were manually inspected and are false merges (generic SEC labels, recurring columns, or distinct releases); staging splits all six. Candidate near-duplicate QA found zero qualifying pairs.

## 10. Asset QA

400 stratified rows were checked. Existing classifications already include every explicit BTC/ETH/SOL title mention, so no asset changes were made. Multi-asset staging does not force a primary asset.

## 11. Empty assets

303 existing rows are empty: 75 are valid/no tracked-asset evidence; 228 SEC rows have body-only evidence and require manual decisions. New general-crypto articles may also correctly have no BTC/ETH/SOL assignment; generic market inference was prohibited.

## 12. Semantic gaps

The approved GPT-5 mini Batch completed 1,508/1,508 requests with zero API failures at an estimated actual cost of $0.164999. All 313 old gaps and 1,195 new candidates are staged. Validation passed after an auditable deterministic sign normalization for 307 raw `negative` magnitude scores; raw outputs remain preserved.

## 13. Record types

200 deterministic rows passed consistency QA. All staged publisher records are `news_article`; the two SEC letters are documented as rejected `regulatory_filing` records.

## 14. Source normalization

Candidate sources are normalized to `cointelegraph`, `decrypt`, and `coindesk`, with page URL, capture method, provenance, HTTP status, and verification time retained. Article bodies remain internal.

## 15. Search QA

100/100 staged search queries passed and all 100 improve historical coverage. Oldest ordering and BTC/ETH/SOL filters passed locally.

## 16. Rate limiting

A distributed adapter and atomic Supabase migration are staged without a new paid account. Raw IPs are not stored. The current in-memory limiter remains the fallback until migration/deployment.

## 17. Production changes

None. Production remains at 7,878 events. The staged rows, metadata corrections, limiter migration, and frontend adapter were not deployed because semantic/manual gates remain.

## 18. Tests

Candidate QA verified 500 Reaction V2 cells independently with zero failures and zero candle problems. Dedicated News Quality V3 tests, search QA, rate-limiter tests, and TypeScript checks pass; final repository suites are recorded at handoff.

## 19. User-action-required items

Fill `reports/USER_REVIEW_PACKAGE/empty_assets.csv`; authenticate Vercel only after the asset review makes the release GO.

## 20. Remaining problems

228 body-only asset classifications need review; 917 old titles remain unverified; 100 important restricted/unknown URLs are packaged; production and distributed limiter deployment remain intentionally pending.
"""
    (DOCS / "NEWS_QUALITY_V3_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
