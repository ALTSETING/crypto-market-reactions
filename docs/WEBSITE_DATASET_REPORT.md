# Website MVP dataset report

Generated from immutable local artifacts by `scripts/processing/build_website_dataset.py`.

## 1. Event count and identity

- Total rows: **7,878**.
- Unique `event_id`: **7,878**.
- Duplicate `event_id`: **0**.
- Publication range: **2017-01-03T10:48:14+00:00** to **2026-07-01T00:00:00+00:00**.
- Missing titles: **0**.
- Missing source URLs: **0**.
- Ambiguous `primary_asset` left NULL: **316**. `related_assets` remains authoritative.
- Full article `body` is deliberately absent; it remains only in the master archive.

## 2. Final columns

- `event_id`
- `title`
- `published_at`
- `source`
- `source_url`
- `primary_asset`
- `related_assets`
- `category`
- `sentiment`
- `sentiment_score`
- `importance`
- `ai_schema_version`
- `ai_prompt_version`
- `ai_original_scale`
- `archive_dataset_source`
- `archive_member_id`
- `reaction_methodology`
- `reaction_value_unit`
- `btc_1m`
- `btc_5m`
- `btc_15m`
- `btc_1h`
- `btc_4h`
- `btc_24h`
- `btc_reaction_source`
- `btc_reference_time`
- `btc_reference_latency_minutes`
- `eth_1m`
- `eth_5m`
- `eth_15m`
- `eth_1h`
- `eth_4h`
- `eth_24h`
- `eth_reaction_source`
- `eth_reference_time`
- `eth_reference_latency_minutes`
- `sol_1m`
- `sol_5m`
- `sol_15m`
- `sol_1h`
- `sol_4h`
- `sol_24h`
- `sol_reaction_source`
- `sol_reference_time`
- `sol_reference_latency_minutes`

`related_assets` is a JSON array string so Parquet and CSV carry the same import-safe representation. Reaction values are percentage points; `0.5` means `+0.5%`.

## 3. Reaction sources and priority rules

1. **Dataset A (6,851 canonical events):** Stage 13A supplies BTC/ETH 1m, 5m and 15m; Stage 11 supplies BTC/ETH 1h, 4h and 24h. Both use the same baseline and open-to-open percentage-return formula. Their overlapping 5m/15m values match exactly.
2. **Dataset B/C:** Stage 18b canonical market supplies 5m, 1h, 4h and 24h; Stage 18 price paths supply 1m and 15m. Values present in both Stage 18 sources match exactly.
3. **Stage 16 fallback:** only `latency_minutes=1` rows are eligible, and only for 1m/5m/1h missing cells because that latency matches Stage 18. Fallback result: `{"filled_cells": 3, "mapped_rows": 668, "new_reaction_rows": 0, "source_rows_latency_1": 668, "unmapped_rows": 0}`.
4. A lower-priority value never overwrites a non-NULL higher-priority value. Missing values remain NULL; no zero filling or interpolation is used.

Per-asset source counts: `{"BTC": {"<NULL>": 548, "stage13a_early+stage11_abnormal_returns": 6851, "stage18b_canonical_market+stage18_price_paths": 479}, "ETH": {"<NULL>": 428, "stage13a_early+stage11_abnormal_returns": 6851, "stage16_market_reactions_latency_1_fallback": 1, "stage18b_canonical_market+stage18_price_paths": 598}, "SOL": {"<NULL>": 7768, "stage18b_canonical_market+stage18_price_paths": 110}}`.

## 4. Reference-price methodology

- Dataset A: `reference_time = floor(published_at to minute) + 1 minute`; reference price is the 1m candle **open** at that time. Horizon return is `(open(reference_time + horizon) / reference_open - 1) × 100`. This is latency 0 relative to the next-full-minute baseline.
- Dataset B/C: `reference_time = floor(published_at to minute) + 2 minutes`; equivalently next full minute plus one latency minute. The same open-to-open percentage formula is used.
- Stage 16 `latency_minutes=1` uses the same B/C reference definition and was verified against Stage 18 paths.
- Dataset A was not silently shifted to Stage 18 latency 1: the required BTC endpoint candles are not locally preserved. The chosen methodology is explicit in `reaction_methodology`, per-asset source, reference-time and latency columns.

Conflict audit: `{"dataset_a_latency0_vs_stage18_latency1": {"1": {"max_abs_difference": 1.7952323367960599, "median_abs_difference": 0.07125605474050944, "rows": 6851}, "15": {"max_abs_difference": 1.9964669032153548, "median_abs_difference": 0.0701618705058138, "rows": 6851}, "5": {"max_abs_difference": 1.3246773543828305, "median_abs_difference": 0.07066604419830869, "rows": 6851}}, "stage13a_vs_stage11_max_abs_difference": {"btc_15m": 0.0, "btc_5m": 0.0, "eth_15m": 0.0, "eth_5m": 0.0}, "stage16_latency1_vs_stage18_paths": {"1": {"max_abs_difference": 0.0, "rows": 667}, "5": {"max_abs_difference": 0.0, "rows": 667}, "60": {"max_abs_difference": 0.0, "rows": 667}}, "stage18_market_vs_paths_max_abs_difference": {"1h": 0.0, "24h": 0.0, "4h": 0.0, "5m": 0.0}}`.

## 5. Overall coverage

| Asset | 1m | 5m | 15m | 1h | 4h | 24h | full 6 |
|---|---|---|---|---|---|---|---|
| BTC | 7,285 (92.5%) | 7,285 (92.5%) | 7,285 (92.5%) | 7,285 (92.5%) | 7,285 (92.5%) | 7,285 (92.5%) | 7,285 (92.5%) |
| ETH | 7,413 (94.1%) | 7,413 (94.1%) | 7,412 (94.1%) | 7,413 (94.1%) | 7,412 (94.1%) | 7,412 (94.1%) | 7,412 (94.1%) |
| SOL | 101 (1.3%) | 101 (1.3%) | 101 (1.3%) | 101 (1.3%) | 101 (1.3%) | 101 (1.3%) | 101 (1.3%) |

- Events with a full six-horizon set for at least one asset: **7,787**.
- Events with a full set for their unambiguous primary asset: **7,472**.
- Events with all 18 BTC/ETH/SOL reaction fields: **74**.

## 6. Coverage by period

| Period | Asset | Events | 1m | 5m | 15m | 1h | 4h | 24h | full 6 |
|---|---|---|---|---|---|---|---|---|---|
| 2017-2022 | BTC | 477 | 108 | 108 | 108 | 108 | 108 | 108 | 108 |
| 2017-2022 | ETH | 477 | 279 | 279 | 279 | 279 | 279 | 279 | 279 |
| 2017-2022 | SOL | 477 | 42 | 42 | 42 | 42 | 42 | 42 | 42 |
| 2023-2026 | BTC | 7,401 | 7,177 | 7,177 | 7,177 | 7,177 | 7,177 | 7,177 | 7,177 |
| 2023-2026 | ETH | 7,401 | 7,134 | 7,134 | 7,133 | 7,134 | 7,133 | 7,133 | 7,133 |
| 2023-2026 | SOL | 7,401 | 59 | 59 | 59 | 59 | 59 | 59 | 59 |

For 2023–2026, dataset A BTC/ETH values survive only as trusted derived Stage 11/13A outputs; the complete local raw candle archive is absent. Stage 18 paths permit direct OHLC verification for related-asset B/C values and for A/ETH latency-1 values, but the MVP deliberately retains the internally consistent latency-0 A family.

## 7. Quality checks

- NULL counts per reaction column: `{"btc_15m": 593, "btc_1h": 593, "btc_1m": 593, "btc_24h": 593, "btc_4h": 593, "btc_5m": 593, "eth_15m": 466, "eth_1h": 465, "eth_1m": 465, "eth_24h": 466, "eth_4h": 466, "eth_5m": 465, "sol_15m": 7777, "sol_1h": 7777, "sol_1m": 7777, "sol_24h": 7777, "sol_4h": 7777, "sol_5m": 7777}`.
- Missing category / sentiment / importance: **0 / 313 / 313**.
- Infinite reaction values: **0**.
- Returns at or below -100%: **0**.
- Events participating in duplicate `source_url` values: **0** across **0** URLs.
- Exact normalized-title duplicate events: **15** in **3** groups.
- Near-duplicate title pairs with char-ngram cosine similarity ≥ 0.92: **41**.
- Near-duplicate examples: `[{"left_event_id": "evt18-08b9f2f2cbba3dfa72d4", "right_event_id": "evt18-b3334bc7df529e489f58", "similarity": 0.9318913134471861}, {"left_event_id": "evt18-05d45b17b865ac378fe3", "right_event_id": "evt18-39d321db29aa996bf711", "similarity": 0.9505787442750955}, {"left_event_id": "evt18-0573fb53753f1206bf9f", "right_event_id": "evt18-d8b92f4207478459419d", "similarity": 0.993614880229911}, {"left_event_id": "evt18-597654fe643211bf2394", "right_event_id": "evt18-79a55ff43f429ff6f0a9", "similarity": 0.922564708539442}, {"left_event_id": "evt18-954735ffefb525f7bfa2", "right_event_id": "evt18-ed3c11800a1be3cdf59e", "similarity": 0.9718739659689936}, {"left_event_id": "evt18-8326b92349e28f1ec289", "right_event_id": "evt18-954735ffefb525f7bfa2", "similarity": 0.9712064619132902}, {"left_event_id": "evt18-5f564a6dfaac6c0454ed", "right_event_id": "evt18-954735ffefb525f7bfa2", "similarity": 0.9684610577598832}, {"left_event_id": "evt18-1e059d05a95ee9547a4e", "right_event_id": "evt18-2b1f20fa71f0ed889ea4", "similarity": 0.9309532705452792}, {"left_event_id": "evt18-69097db99ae8789d37b8", "right_event_id": "evt18-8aa1f3c798223cf941c8", "similarity": 0.9273979073320531}, {"left_event_id": "evt18-5531d8fcbee59ea17990", "right_event_id": "evt18-ea8dc622ccea8ed00d53", "similarity": 0.960308230652983}]`.

## 8. Deterministic 20-event validation sample

Seed: `18022`. Ten events were sampled from dataset A and ten from B/C. Dataset A output cells were compared with Stage 13A/Stage 11 source values. B/C values were additionally recalculated from path baseline/endpoint opens.

| event_id | family | cells | formula checks | max abs diff | status |
|---|---|---|---|---|---|
| evt18-918176f02399b132550b | A | 12 | 0 | 0 | PASS |
| evt18-bcc38cf475d96e51a24a | A | 12 | 0 | 0 | PASS |
| evt18-f9b2fec0354aa7377e78 | A | 12 | 0 | 0 | PASS |
| evt18-d4765e4dcdadb64afe59 | A | 12 | 0 | 0 | PASS |
| evt18-5aa6eee46473acf11771 | A | 12 | 0 | 0 | PASS |
| evt18-b50c76f9cf188d097d00 | A | 12 | 0 | 0 | PASS |
| evt18-cd2ec77f00dc54903c1b | A | 12 | 0 | 0 | PASS |
| evt18-9e2020986a0c95796931 | A | 12 | 0 | 0 | PASS |
| evt18-70848ab7cf2d425b162e | A | 12 | 0 | 0 | PASS |
| evt18-7a5192f78ca1ec7c40f6 | A | 12 | 0 | 0 | PASS |
| evt18-a8904d75f3707a04b840 | C | 6 | 6 | 0 | PASS |
| evt18-a6c79eb3ca1ebb3d3582 | B | 6 | 6 | 0 | PASS |
| evt18-6221661cff131f15c780 | C | 12 | 12 | 0 | PASS |
| evt18-d6571eea0146e33de023 | B | 6 | 6 | 0 | PASS |
| evt18-49f7b1bd51f989dc008b | C | 6 | 6 | 0 | PASS |
| evt18-e796f280c561a387a4ec | B | 6 | 6 | 0 | PASS |
| evt18-3be03b423fb258a2f126 | C | 6 | 6 | 0 | PASS |
| evt18-1e4718c5f68e82412897 | B | 6 | 6 | 0 | PASS |
| evt18-a189ce7ec837275fdecf | B | 6 | 6 | 0 | PASS |
| evt18-e955046ad8d0b628c2bb | B | 6 | 6 | 0 | PASS |

## 9. Detected problems

- The archive has two valid reference families: latency 0 for A and latency 1 for B/C. They are disclosed, not blended within an event family.
- SOL coverage is sparse and correctly NULL before listing/when no trustworthy related-asset path exists.
- Cross-asset BTC/ETH/SOL reactions are unavailable for many B/C events; only preserved related-asset paths are used.
- `primary_asset` is NULL when multiple assets tie for the highest semantic relevance; `related_assets` preserves all associations.
- Exact and near-duplicate URLs/titles need editorial review before public search indexing; they were not dropped automatically.
- The latest event (`2026-07-01`) lacks a complete Stage 18 24-hour path. Stage 16 latency 1 safely fills only 1m/5m/1h; 15m/4h/24h remain NULL because that source does not provide compatible values for those horizons.

## 10. Recommendations before PostgreSQL/Supabase import

1. Keep `event_id` as the immutable natural identifier and enforce a unique constraint.
2. Parse `related_assets` into an `event_assets` join table during normalized import.
3. Preserve per-asset `reaction_source`, `reference_time` and `reference_latency_minutes`; do not hide the two methodologies.
4. Review ambiguous primary assets, duplicate URLs/titles, and missing AI values without destructive deduplication.
5. If a uniform reference definition and complete three-asset coverage are required, first recover/reacquire the full 1m BTC/ETH/SOL candle archive and rebuild every event under one versioned methodology.
6. Retain NULLs as SQL NULL and record a reaction-calculation version during import.
