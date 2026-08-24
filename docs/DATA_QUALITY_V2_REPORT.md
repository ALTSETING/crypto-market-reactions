# Data Quality V2 report

## 1. Executive summary

The 7,878-row canonical archive was backed up and audited without changing production. A versioned staging dataset adds provenance, record type, story grouping, quality status, display titles, and time metadata. Reaction V2 was rebuilt separately from official checksum-verified Binance 1m archives and passed 500/500 raw-cell recalculations.

## 2. Baseline

- Events / unique IDs: 7,878 / 7,878.
- Dataset SHA-256: `78cc72f91bbd3cfba595ff843486d2e8b82e4ea10a31f68666ce613c6d8ec833`.
- Range: 2017-01-03T10:48:14+00:00 to 2026-07-01T00:00:00+00:00.
- Backup: `data/website/backups/pre_data_quality_v2/` with hashes.

## 3. Problems found

- Coverage is extremely uneven: 477 events in 2017–2022 versus 7,401 in 2023–2026.
- Two V1 reaction baselines coexist (6,851 latency-0 rows; 1,027 latency-1 rows).
- Missing reaction cells: 53,013.
- Empty related-assets arrays: 303.
- Missing sentiment / importance: 313 / 313.
- Generic titles: 11; normalized duplicate-title rows: 15.
- External sample: {'200': 133, '403': 52, '429': 15}.

## 4. Problems fixed

- Added conservative `story_id` grouping without deleting articles.
- Assigned deterministic record types to all 7,878 staging rows.
- Added factual display titles for 11 generic SEC records while preserving captured titles.
- Added quality/provenance/time/version metadata in staging and an append-only changelog.
- Downloaded and checksum-validated Binance monthly archives through 2026-07.
- Built uniform Reaction V2 without interpolation or overwriting V1.
- Removed unqualified “verified” wording, split related reactions from market context, changed gainers/losers default to a concrete 1h horizon, normalized source selection, made homepage stats dynamic, and corrected Article JSON-LD to WebPage.

## 5. Problems still open

- BLOCKED — Full 7,878-URL verification: stopped after the 200-row stratified batch returned 52 HTTP 403 and 15 HTTP 429 responses; anti-bot/rate limits were not bypassed.
- BLOCKED — Publication timestamps beyond the externally exposed metadata sample remain unverified; 41/200 sources exposed a parseable publication timestamp.
- BLOCKED — 313 missing sentiment/importance rows require recovery from a trusted stored analysis artifact or an explicitly approved paid AI run.
- BLOCKED — Distributed rate limiting requires an external account/service such as Upstash or a paid platform feature.
- BLOCKED — Production cutover is withheld until the remaining 300-event source-level validation and deployment rollback rehearsal pass.

## 6. BLOCKED items

- BLOCKED — Full 7,878-URL verification: stopped after the 200-row stratified batch returned 52 HTTP 403 and 15 HTTP 429 responses; anti-bot/rate limits were not bypassed.
- BLOCKED — Publication timestamps beyond the externally exposed metadata sample remain unverified; 41/200 sources exposed a parseable publication timestamp.
- BLOCKED — 313 missing sentiment/importance rows require recovery from a trusted stored analysis artifact or an explicitly approved paid AI run.
- BLOCKED — Distributed rate limiting requires an external account/service such as Upstash or a paid platform feature.
- BLOCKED — Production cutover is withheld until the remaining 300-event source-level validation and deployment rollback rehearsal pass.

## 7. Historical coverage

- 2017: 83
- 2018: 45
- 2019: 124
- 2020: 57
- 2021: 78
- 2022: 90
- 2023: 101
- 2024: 143
- 2025: 4,080
- 2026: 3,077

Local source artifacts contained 334 accepted 2017–2022 records: 332 were already represented by URL/canonical mapping and 2 SEC records were placed in `data/backfill_v2/candidate_events.parquet` for QA only.

## 8. Source verification

The 200-row stratified batch returned 133×200, 52×403 and 15×429. No paywall, captcha, authentication, or anti-bot restriction was bypassed. Exact current-title differences are audit flags, not automatic historical-title replacements.

## 9. Timestamp verification

All dataset timestamps are timezone-aware UTC. External metadata exposed 41 publication timestamps; 15 matched within one second. No timestamp was silently corrected.

## 10. Title drift

Current titles were captured separately for 133 pages. 127 exact string differences require editorial review; captured titles remain unchanged.

## 11. Duplicate/story clustering

- Articles / stories: 7,878 / 7,862.
- Multi-article clusters: 6; articles in them: 22.
- Largest cluster: 11.

Statistics were not switched to story-level because clustering is intentionally conservative and still requires review.

## 12. Asset classification

The 400-row stratified review artifact includes 100 BTC, 100 ETH, 100 SOL, plus up to 50 empty and 50 multi-asset rows. Solana Beach and generic Coinbase regression cases are covered. No automatic asset corrections were promoted.

## 13. Record types

{"github_commit": 209, "news_article": 6715, "official_announcement": 121, "protocol_release": 301, "regulatory_filing": 503, "research": 29}

## 14. Binance archive coverage

288 official monthly ZIPs match their checksums. Full validation found zero duplicates and three invalid-duration candles at the same 2023-03-24 minute; those rows remain excluded.

## 15. Reaction methodology V2

`reference_time = floor(published_at, 1m) + 1m`; return = `(open(reference+horizon)/open(reference)-1)*100`. Missing candles remain NULL with a reason. Artifact: `data/reactions_v2/events_reactions_v2.parquet`.

## 16. V1 vs V2 comparison

Comparable cells: 88,791; sign flips: 1,088. Detailed differences by asset, year, dataset family, source and horizon are in `reports/REACTION_V1_V2_COMPARISON.csv`.

## 17. Reaction QA

500/500 sampled cells passed independent recalculation; maximum absolute difference: 0.

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

- Staging events: 7,878; stories: 7,862.
- Verified raw V2 rows BTC / ETH / SOL: 7,805 / 7,805 / 7,586.
- Quality status: {"accepted": 7863, "needs_review": 15}.
- Changelog entries: 149,682.

## 24. Exact source files changed

- `scripts/quality/full_dataset_audit.py`
- `scripts/quality/build_reactions_v2.py`
- `scripts/quality/verify_source_sample.py`
- `scripts/quality/search_audit.py`
- `scripts/quality/local_backfill_audit.py`
- `scripts/quality/finalize_report.py`
- `historical_market_data/cli.py`
- `tests/test_data_quality_v2.py`
- `database/migrations/006_data_quality_v2_staging.sql`
- `frontend/app/page.tsx`
- `frontend/app/events/[slug]/page.tsx`
- `frontend/components/events-explorer.tsx`
- `frontend/components/reaction-table.tsx`
- `frontend/lib/data/events.ts`
- `frontend/lib/events-filters.ts`
- `frontend/lib/reactions.ts`
- `frontend/lib/seo.ts`
- `frontend/lib/validation/events-query.ts`
- `frontend/types/events.ts`

Generated data/reports are listed by `git status` and remain staging/audit artifacts.

## 25. Recommended next steps

1. Manually review the 2 backfill candidates, 15 needs-review records, story clusters, title drift and asset sample.
2. Resume source verification only in source-specific low-rate batches or with publisher-approved access.
3. Recover the 313 semantic gaps from trusted stored outputs; approve a paid AI run only if recovery fails.
4. Apply migration and V2 import to staging, run a 300-event source-level review and rollback rehearsal, then consider production cutover.
