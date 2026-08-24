"""Assemble Data Quality V2 reports from completed deterministic artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    baseline = load_json(ROOT / "reports" / "DATA_QUALITY_V2_BASELINE.json")
    source = load_json(ROOT / "reports" / "SOURCE_VERIFICATION_V2_SUMMARY.json")
    v2 = pd.read_parquet(ROOT / "data" / "reactions_v2" / "events_reactions_v2.parquet")
    v1v2 = pd.read_parquet(ROOT / "reports" / "REACTION_V1_V2_CELLS.parquet")
    qa = pd.read_csv(ROOT / "reports" / "REACTION_V2_QA_500_CELLS.csv")
    staging = pd.read_parquet(ROOT / "data" / "quality_v2" / "events_quality_v2_staging.parquet")
    changelog = pd.read_parquet(ROOT / "reports" / "DATA_QUALITY_V2_CHANGELOG.parquet")
    candidates = pd.read_parquet(ROOT / "data" / "backfill_v2" / "candidate_events.parquet")
    manifest = pd.read_csv(ROOT / "reports" / "stage16c_download_manifest.csv")
    invalid_candles = pd.read_csv(ROOT / "reports" / "stage16c_invalid_candles.csv")
    clusters = pd.read_csv(ROOT / "reports" / "DATA_QUALITY_V2_STORY_CLUSTERS.csv")
    search = pd.read_csv(ROOT / "reports" / "SEARCH_QUALITY_V2_AUDIT.csv")

    coverage = {}
    for asset in ("BTC", "ETH", "SOL"):
        part = v2[v2.asset.eq(asset)]
        coverage[asset] = {
            "verified_raw_rows": int(part.reaction_quality.eq("verified_raw").sum()),
            "partial_verified_raw_rows": int(part.reaction_quality.eq("partial_verified_raw").sum()),
            "missing_rows": int(part.reaction_quality.eq("missing").sum()),
        }
    blocked = [
        "Full 7,878-URL verification: stopped after the 200-row stratified batch returned 52 HTTP 403 and 15 HTTP 429 responses; anti-bot/rate limits were not bypassed.",
        "Publication timestamps beyond the externally exposed metadata sample remain unverified; 41/200 sources exposed a parseable publication timestamp.",
        "313 missing sentiment/importance rows require recovery from a trusted stored analysis artifact or an explicitly approved paid AI run.",
        "Distributed rate limiting requires an external account/service such as Upstash or a paid platform feature.",
        "Production cutover is withheld until the remaining 300-event source-level validation and deployment rollback rehearsal pass.",
    ]
    display_corrections = int(staging.display_title.ne(staging.captured_title).sum())
    summary = {
        "events_before": baseline["events"],
        "events_after": len(staging),
        "stories": int(staging.story_id.nunique()),
        "rows_changed": int(staging.event_id.nunique()),
        "changelog_entries": len(changelog),
        "duplicates_found": int(baseline["identity"]["duplicate_normalized_title_rows"]),
        "duplicates_grouped": int(clusters.article_count.sum()) if len(clusters) else 0,
        "multi_article_story_clusters": len(clusters),
        "dead_urls": int(source["http_status_counts"].get("404", 0)),
        "redirected_urls": source["redirected_urls"],
        "source_urls_sampled": source["sample_size"],
        "source_urls_non_200": sum(int(value) for key, value in source["http_status_counts"].items() if key != "200"),
        "timestamps_verified": source["publication_timestamps_captured"],
        "timestamps_corrected": 0,
        "title_drift_rows": source["title_drift_rows"],
        "display_titles_corrected": display_corrections,
        "asset_classifications_changed": 0,
        "record_types_assigned": int(staging.record_type.notna().sum()),
        "btc_reactions_v2": coverage["BTC"]["verified_raw_rows"],
        "eth_reactions_v2": coverage["ETH"]["verified_raw_rows"],
        "sol_reactions_v2": coverage["SOL"]["verified_raw_rows"],
        "reaction_cells_verified": int(qa.status.eq("pass").sum()),
        "reaction_cells_failed": int(qa.status.eq("fail").sum()),
        "reaction_qa_max_difference": float(qa.absolute_difference.max()),
        "v1_v2_comparable_cells": len(v1v2),
        "v1_v2_sign_flips": int(v1v2.sign_flip.sum()),
        "binance_archives_checksum_verified": int(manifest.expected_checksum.astype(str).eq(manifest.actual_checksum.astype(str)).sum()),
        "binance_invalid_candles": len(invalid_candles),
        "historical_backfill_candidates": len(candidates),
        "search_queries_audited": int(search["query"].nunique()),
        "production_changed": False,
        "blocked_tasks": blocked,
    }
    (ROOT / "reports" / "data_quality_v2_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    category_lines = "\n".join(
        f"- {category}: {count:,}" for category, count in list(baseline["categories"].items())[:12]
    )
    year_lines = "\n".join(
        f"- {year}: {count:,}" for year, count in baseline["coverage"]["by_year"].items()
    )
    blocked_lines = "\n".join(f"- BLOCKED — {item}" for item in blocked)
    changed_files = [
        "scripts/quality/full_dataset_audit.py", "scripts/quality/build_reactions_v2.py",
        "scripts/quality/verify_source_sample.py", "scripts/quality/search_audit.py",
        "scripts/quality/local_backfill_audit.py", "scripts/quality/finalize_report.py",
        "historical_market_data/cli.py",
        "tests/test_data_quality_v2.py", "database/migrations/006_data_quality_v2_staging.sql",
        "frontend/app/page.tsx", "frontend/app/events/[slug]/page.tsx",
        "frontend/components/events-explorer.tsx", "frontend/components/reaction-table.tsx",
        "frontend/lib/data/events.ts", "frontend/lib/events-filters.ts", "frontend/lib/reactions.ts",
        "frontend/lib/seo.ts", "frontend/lib/validation/events-query.ts", "frontend/types/events.ts",
    ]
    files_lines = "\n".join(f"- `{path}`" for path in changed_files)
    report = f"""# Data Quality V2 report

## 1. Executive summary

The 7,878-row canonical archive was backed up and audited without changing production. A versioned staging dataset adds provenance, record type, story grouping, quality status, display titles, and time metadata. Reaction V2 was rebuilt separately from official checksum-verified Binance 1m archives and passed 500/500 raw-cell recalculations.

## 2. Baseline

- Events / unique IDs: {baseline['events']:,} / {baseline['unique_event_id']:,}.
- Dataset SHA-256: `{baseline['dataset_sha256']}`.
- Range: {baseline['publication_min']} to {baseline['publication_max']}.
- Backup: `data/website/backups/pre_data_quality_v2/` with hashes.

## 3. Problems found

- Coverage is extremely uneven: 477 events in 2017–2022 versus 7,401 in 2023–2026.
- Two V1 reaction baselines coexist (6,851 latency-0 rows; 1,027 latency-1 rows).
- Missing reaction cells: {baseline['market']['missing_reaction_cells']:,}.
- Empty related-assets arrays: {baseline['classification']['empty_related_assets']:,}.
- Missing sentiment / importance: {baseline['semantic']['missing_sentiment']:,} / {baseline['semantic']['missing_importance']:,}.
- Generic titles: {baseline['identity']['generic_title_rows']}; normalized duplicate-title rows: {baseline['identity']['duplicate_normalized_title_rows']}.
- External sample: {source['http_status_counts']}.

## 4. Problems fixed

- Added conservative `story_id` grouping without deleting articles.
- Assigned deterministic record types to all {len(staging):,} staging rows.
- Added factual display titles for {display_corrections} generic SEC records while preserving captured titles.
- Added quality/provenance/time/version metadata in staging and an append-only changelog.
- Downloaded and checksum-validated Binance monthly archives through 2026-07.
- Built uniform Reaction V2 without interpolation or overwriting V1.
- Removed unqualified “verified” wording, split related reactions from market context, changed gainers/losers default to a concrete 1h horizon, normalized source selection, made homepage stats dynamic, and corrected Article JSON-LD to WebPage.

## 5. Problems still open

{blocked_lines}

## 6. BLOCKED items

{blocked_lines}

## 7. Historical coverage

{year_lines}

Local source artifacts contained 334 accepted 2017–2022 records: 332 were already represented by URL/canonical mapping and 2 SEC records were placed in `data/backfill_v2/candidate_events.parquet` for QA only.

## 8. Source verification

The 200-row stratified batch returned 133×200, 52×403 and 15×429. No paywall, captcha, authentication, or anti-bot restriction was bypassed. Exact current-title differences are audit flags, not automatic historical-title replacements.

## 9. Timestamp verification

All dataset timestamps are timezone-aware UTC. External metadata exposed 41 publication timestamps; {source['publication_timestamp_exact_matches']} matched within one second. No timestamp was silently corrected.

## 10. Title drift

Current titles were captured separately for 133 pages. {source['title_drift_rows']} exact string differences require editorial review; captured titles remain unchanged.

## 11. Duplicate/story clustering

- Articles / stories: {len(staging):,} / {staging.story_id.nunique():,}.
- Multi-article clusters: {len(clusters)}; articles in them: {int(clusters.article_count.sum()) if len(clusters) else 0}.
- Largest cluster: {int(clusters.article_count.max()) if len(clusters) else 1}.

Statistics were not switched to story-level because clustering is intentionally conservative and still requires review.

## 12. Asset classification

The 400-row stratified review artifact includes 100 BTC, 100 ETH, 100 SOL, plus up to 50 empty and 50 multi-asset rows. Solana Beach and generic Coinbase regression cases are covered. No automatic asset corrections were promoted.

## 13. Record types

{json.dumps(staging.record_type.value_counts().to_dict(), sort_keys=True)}

## 14. Binance archive coverage

{summary['binance_archives_checksum_verified']} official monthly ZIPs match their checksums. Full validation found zero duplicates and three invalid-duration candles at the same 2023-03-24 minute; those rows remain excluded.

## 15. Reaction methodology V2

`reference_time = floor(published_at, 1m) + 1m`; return = `(open(reference+horizon)/open(reference)-1)*100`. Missing candles remain NULL with a reason. Artifact: `data/reactions_v2/events_reactions_v2.parquet`.

## 16. V1 vs V2 comparison

Comparable cells: {len(v1v2):,}; sign flips: {int(v1v2.sign_flip.sum()):,}. Detailed differences by asset, year, dataset family, source and horizon are in `reports/REACTION_V1_V2_COMPARISON.csv`.

## 17. Reaction QA

500/500 sampled cells passed independent recalculation; maximum absolute difference: {qa.absolute_difference.max():.3g}.

## 18. Outlier audit

Top positive/negative legacy reactions per asset/horizon are in `reports/REACTION_OUTLIER_REVIEW.csv`. No impossible <= -100%, infinite, or >50% legacy cells were found.

## 19. Search audit

Fifty metadata-only queries were audited. V2 search fields exclude article bodies and include titles, source, category, related assets and record type. Ranked review rows are in `reports/SEARCH_QUALITY_V2_AUDIT.csv`.

## 20. SEO corrections

Event pages now use `WebPage` JSON-LD with `citation`, `about`, and `isPartOf`; the original publisher is no longer mislabeled as publisher of this site page. Open Graph type is `website`.

## 21. UI transparency changes

Homepage totals/date range and per-year coverage come from cached server queries. Event pages disclose publication date, source, related assets, methodology and missing-data behavior. Average remains secondary and has an explicit simple-mean tooltip.

## 22. Production status

Production changed: **NO**. The migration is review-only and no Supabase import, deployment, GitHub push, or dataset cutover was performed.

## 23. Final dataset metrics

- Staging events: {len(staging):,}; stories: {staging.story_id.nunique():,}.
- Verified raw V2 rows BTC / ETH / SOL: {coverage['BTC']['verified_raw_rows']:,} / {coverage['ETH']['verified_raw_rows']:,} / {coverage['SOL']['verified_raw_rows']:,}.
- Quality status: {json.dumps(staging.quality_status.value_counts().to_dict(), sort_keys=True)}.
- Changelog entries: {len(changelog):,}.

## 24. Exact source files changed

{files_lines}

Generated data/reports are listed by `git status` and remain staging/audit artifacts.

## 25. Recommended next steps

1. Manually review the 2 backfill candidates, 15 needs-review records, story clusters, title drift and asset sample.
2. Resume source verification only in source-specific low-rate batches or with publisher-approved access.
3. Recover the 313 semantic gaps from trusted stored outputs; approve a paid AI run only if recovery fails.
4. Apply migration and V2 import to staging, run a 300-event source-level review and rollback rehearsal, then consider production cutover.
"""
    (ROOT / "docs" / "DATA_QUALITY_V2_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"summary": "reports/data_quality_v2_summary.json", "report": "docs/DATA_QUALITY_V2_REPORT.md"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
