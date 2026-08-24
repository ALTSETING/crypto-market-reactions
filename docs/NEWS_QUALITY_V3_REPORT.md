# News Quality V3 report

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

All 7,878 existing URLs were inventoried: 6963 verified 200, 229 verified source artifacts, 52 blocked 403, and 634 unknown. Access restrictions are not mislabeled as broken.

## 8. Title drift

After HTML/JSON-LD and publisher-boilerplate normalization: 6961 exact, 917 unverified, and no material drift. No automatic title rewrite was made from a blocked/unverified page.

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
