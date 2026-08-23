# PostgreSQL / Supabase import preparation

Do not import the stage files directly as one wide table. Build a deterministic export layer first.

## Required transformations

1. Create one `events` row per `canonical_event_id` (7 878 current unique events), choosing and documenting the canonical title/body/published timestamp.
2. Preserve all alternative publications in `event_sources` with source, original URL, canonical URL, author/platform/external ID and source timestamps.
3. Move BTC/ETH/SOL relationships to `event_assets`; do not duplicate the event body for every asset.
4. Store AI outputs in `event_ai_analysis` with `schema_version`, `prompt_version`, model/provenance and original score scale. Map `sem_event_type` to the public category and `sem_content_valence`/score to sentiment only after scale validation.
5. Build `event_reactions` keyed by `(event_id, asset, reaction_version)` with UTC baseline, baseline price, calculation method and nullable `return_1m`, `5m`, `15m`, `1h`, `4h`, `24h`.
6. Preserve raw/abnormal return distinction and document that stored returns are percentage values, not decimal fractions.
7. Add import lineage: source file, source row/member ID, content hash, imported timestamp and dataset version.

## Missing/unfinished data for the MVP contract

- Stage18b lacks 1m and 15m in its canonical reaction table.
- Current canonical reactions are generally for the related asset, not all BTC/ETH/SOL for every event.
- Raw Binance ZIP files stop at 2022-12. Later event windows exist, but a complete local 2023–2026 candle archive or PostgreSQL dump was not found.
- Re-export the original PostgreSQL `market_candles` table if it still exists elsewhere, or reacquire official 1m candles, then calculate the same six horizons for all three assets.
- Resolve 161 duplicated event-asset rows (`8 039 rows - 7 878 canonical IDs`) through the normalized event/source/asset model rather than dropping them blindly.
- Review 18 empty bodies and one missing canonical URL; original URLs are present for every row.
- Decide how to represent 92 rows without full market coverage (nullable reactions plus a reason/status is recommended).

## Suggested schema

```text
events
  id, canonical_event_id, title, body, published_at_utc, category

event_sources
  id, event_id, source, original_url, canonical_url, author,
  platform, external_id, source_published_at, content_hash

event_assets
  event_id, asset, symbol, relevance, detection_source

event_ai_analysis
  event_id, schema_version, prompt_version, model_name,
  sentiment, importance, novelty, confidence, raw_payload, analyzed_at

event_reactions
  event_id, asset, reaction_version, baseline_time, baseline_price,
  return_1m, return_5m, return_15m, return_1h, return_4h, return_24h,
  coverage_status, calculation_metadata
```

Add indexes for `published_at_utc`, `event_assets.asset`, `event_sources.source`, unique original/canonical URLs where appropriate, and PostgreSQL full-text search over title/body. CSV export should query this normalized model and pivot reaction horizons only at export time.
