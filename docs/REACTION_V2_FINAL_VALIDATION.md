# Reaction V2 final validation

## Result

Reaction Methodology V2 passed every mandatory calculation, identity, timezone, outlier, staging, and rollback gate. The immutable artifact was applied transactionally to the expected Supabase project on 2026-08-23 at 16:21:14 UTC. No non-reaction field changed.

## Methodology and data

- Method: first full one-minute candle strictly after publication, open-to-open return for 1m, 5m, 15m, 1h, 4h, and 24h.
- Exact-boundary rule: `14:30:00.000`, `14:30:00.001`, and `14:30:59.999` all reference `14:31:00` UTC.
- Source: official Binance Vision monthly BTCUSDT, ETHUSDT, and SOLUSDT 1m archives through 2026-07.
- Artifact: `data/reactions_v2/events_reactions_v2_final.parquet`.
- Artifact SHA-256: `be779f639f3471d182ad4c325e4ac4a65909105662ac1f3e5f43fb44eba70bfa`.
- Archive manifest hash: `43d1a30a962a837764ea65d7f29f171c257b59519682d19b5edace9825ab5871`.
- Rows / events: 23,634 / 7,878.
- Full coverage: BTC 7,805; ETH 7,805; SOL 7,586.

SOL reaction availability is broader-market context and is not evidence that an event is about Solana. The prepared frontend separates related assets from broader context; production publication of that frontend remains blocked by missing Vercel authentication.

## Mandatory audits

- Three Binance candles at 2023-03-24 12:39 UTC had shortened close times and zero volume. The official REST endpoint reproduces the archive rows, ruling out parser, duplicate, precision, and archive-boundary faults. They are excluded without interpolation, nearest-candle substitution, or forward-fill. Affected published V2 reactions: 0.
- V1/V2 sign flips: 1,088. The 100-case forensic sample includes BTC 35, ETH 35, SOL 30; all six horizons; every year 2017–2026; and the 20 largest absolute differences. Raw recalculation failures: 0.
- The 300-event stratified sample covers all available requested asset, year, source, and record-type strata. Metadata failures: 0.
- Independently recalculated reaction cells: 1,195 new plus the prior 500, total 1,695. Failures: 0; maximum numerical difference: 0.
- Reference-time, boundary, and timezone audit: PASS; systematic 1h/4h/5h/8h offsets: 0.
- Outlier audit: 360 extreme cells checked, failures 0, isolated endpoint spikes 0.
- Distribution audit found no asset/horizon/year group with an absolute extreme above 100%, and no scale/timezone signature.

Missing values and their machine-readable reasons are in `reports/REACTION_V2_MISSING_DATA.csv`. Exact per-horizon counts are retained in `reports/REACTION_V2_LOCAL_VALIDATION_STATUS.json`. Quality is stored per asset as `raw_verified_v2`, `partial_raw_verified_v2`, or `missing_market_data`; missing reasons are internal JSON and are not selected by public list/detail APIs.

## V1/V2 and rollback

V1 remains recoverable in `data/website/backups/pre_reaction_v2_cutover/`. The final backup hash is `11f84ef17c4c8e21a86f8391b36c217a65c3de9fa178ee91fbc76dff7cbc02d1`. The complete non-identical cell changelog contains 56,986 rows; identical values were omitted.

Rollback rehearsal executed V1 → V2 → exact V1 restoration → V2 on temporary production-shaped tables. Both V2 comparisons and the restored V1 comparison had zero mismatches. The executable rollback is `python -m scripts.database.reaction_v2_rollback --apply`.

## Database and production validation

- Staged/matched/live IDs: 7,878 / 7,878 / 7,878; unknown and missing IDs: 0.
- Updated rows: 7,878; V2 mismatches: 0; non-reaction rows changed: 0.
- Post-cutover random DB comparison: 100 events, 3,400 fields, 0 mismatches.
- Python: 377 passed. Frontend: 33 passed. ESLint, TypeScript, build, bundle scan, security smoke, SEO smoke, and browser smoke passed.
- Production core smoke passed for homepage, search, filters, pagination, three asset filters, gainers/losers, CSV, event pages, sitemap, robots, 404, mobile, and themes.
- SEO retained 7,879 sitemap URLs, 7,878 event URLs, canonical origin, stable slugs, and query noindex behavior.
- Direct anonymous Supabase SELECT remains blocked with HTTP 401; search and CSV remain capped at 50; client bundles contain neither the secret key nor database URL.
- Median before/after latency in milliseconds: homepage 188.4/182.8, search 541.4/317.5, event 191.8/186.6, sitemap 610.7/714.8. There is no consistent material regression.

One previously visited event page retained one old missing `btc_24h` value in its one-hour server cache (173/174 displayed values current). The DB, API, and uncached pages are correct. Publishing the prepared frontend would also refresh this cache, but Vercel CLI is logged out, so that publication is `BLOCKED — USER ACTION REQUIRED`. This is not a calculation/database rollback condition.

Open non-blocking work remains unchanged: 313 missing sentiment/importance values, full source URL audit including 403/429 responses, historical 2017–2022 backfill, distributed rate limiting, title-drift manual review, and two backfill candidates.
