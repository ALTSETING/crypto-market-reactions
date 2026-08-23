# Homework 6 — market-reaction sorting and filters

## Implementation

- Sorting is performed by Supabase before pagination for `newest`, `oldest`,
  `growth`, and `decline`, with `event_id` as the unique final tie-breaker.
- Reaction sorting uses the selected Related asset and one of `1m`, `5m`,
  `15m`, `1h`, `4h`, `24h`, or `average`; missing values use `NULLS LAST`.
- The API validates `asset`, `sort`, `horizon`, `marketDataOnly`, `page`,
  `pageSize`, `q`, `source`, `from`, and `to`. `pageSize` is capped at 50.
- UI additions: sort and horizon selects, Top gainers/losers, Only with market
  data, removable active-filter chips, Clear all filters, URL persistence, and
  the selected metric on every event card. Search remains explicit-submit only.
- Reaction sort is disabled for All events. Returning to All events resets it
  to Newest and removes Only with market data.

## Database

Migration: `database/migrations/004_add_average_reactions.sql`.

Generated columns:

- `btc_average_reaction`
- `eth_average_reaction`
- `sol_average_reaction`

Partial B-tree indexes:

- `ix_events_btc_average_reaction`
- `ix_events_eth_average_reaction`
- `ix_events_sol_average_reaction`

For asset `a`, the exact formula is:

```text
if num_nonnulls(a_1m, a_5m, a_15m, a_1h, a_4h, a_24h) >= 3:
  (coalesce(a_1m, 0) + coalesce(a_5m, 0) + coalesce(a_15m, 0)
   + coalesce(a_1h, 0) + coalesce(a_4h, 0) + coalesce(a_24h, 0))
  / num_nonnulls(a_1m, a_5m, a_15m, a_1h, a_4h, a_24h)
else NULL
```

The migration was applied twice successfully to verify repeatability. No
indexes were added for the 18 existing horizon columns because the table has
only 7,878 rows.

## Live Top 5 examples

All values below are percentage returns and come from the generated Average
field for the named asset.

### BTC

| # | Top gainer | Return | Top loser | Return |
|---|---|---:|---|---:|
| 1 | bitcoin/bitcoin Bitcoin Core 0.16.0 | +2.94% | iShares Bitcoin Trust ETF 8-K filing 0001193125-26-039518 | -2.94% |
| 2 | Exchange Listed Funds Trust (CIK 0001547950) 485APOS 0001398344-18-000775 | +2.49% | Bitcoin ETFs Extend Losses As Daily Outflows Hit $545 Million | -2.91% |
| 3 | BTC, ETH, SOL, XRP price news: Why is bitcoin down today | +2.21% | Bitcoin ETFs 'Hanging In There' Despite Price Plunge: Analyst | -2.91% |
| 4 | Crypto Treasuries Fall Deeply Underwater as Bitcoin, Ethereum and Solana Dive | +1.91% | XRP Sentiment Extremely Higher Than Bitcoin And Ethereum: Santiment | -2.91% |
| 5 | Donald Trump Names XRP, SOL, ADA, BTC and ETH as Part of U.S. Crypto Reserve | +1.90% | Bitcoin Price (BTC) Gives Up Some Gains | -2.67% |

### ETH

| # | Top gainer | Return | Top loser | Return |
|---|---|---:|---|---:|
| 1 | CoinDesk 20 Performance Update: Bitcoin and Ethereum Trade Flat as Index Drops 1.1% | +5.95% | ethereum/consensus-specs LAN party | -6.46% |
| 2 | DOGE, ADA, BTC Price News: Dogecoin, Cardano Lead Crypto Gains as Traders Weigh Fed Actions | +4.76% | ethereum/consensus-specs The Broken Star | -5.17% |
| 3 | Solidity Bugfix Release | +4.29% | Rex Shares, Osprey Funds File for MOVE ETF | -3.71% |
| 4 | ethereum/go-ethereum Tall Moose (v1.9.12) | +4.27% | Bitcoin (BTC) Price Posts Worst Q1 in a Decade, Raising Questions About Where the Cycle Stands | -3.62% |
| 5 | Why Sei Wants to Cut Cosmos Compatibility, Go All-In on Ethereum | +4.23% | Aster Airdrop Delayed Due to 'Data Inconsistencies' With Token Allocations | -3.58% |

### SOL

| # | Top gainer | Return | Top loser | Return |
|---|---|---:|---|---:|
| 1 | solana-labs/solana solana_token_audit#14: Derivation of an address | +2.56% | solana-labs/solana chore: bump serde_json from 1.0.75 to 1.0.78 (#22748) | -2.25% |
| 2 | solana-labs/solana solana_token_audit#15: Check for signing authority | +2.11% | solana-labs/solana Improve poh recorder metrics (#22730) | -2.07% |
| 3 | solana-labs/solana chore: bump libc from 0.2.112 to 0.2.115 (#22796) | +1.75% | gdlc-8k_20211001.htm | -1.55% |
| 4 | solana-labs/solana chore: bump fd-lock from 3.0.2 to 3.0.3 (#22813) | +1.43% | Document | -1.43% |
| 5 | Document | +1.41% | solana-labs/solana Always contact release.solana.com over https | -1.19% |

## Live verification

| Check | Result |
|---|---|
| BTC Average descending / ascending, first 20 | PASS / PASS |
| ETH Average descending / ascending, first 20 | PASS / PASS |
| SOL Average descending / ascending, first 20 | PASS / PASS |
| Specific horizon (`BTC 1h`) | PASS |
| NULLS LAST for BTC / ETH / SOL | PASS / PASS / PASS |
| Duplicate IDs between ETH pages 1 and 2 | 0 |
| Search + asset + dates + Average sort | PASS, 20/20 monotonic |
| Generated-average formula mismatches | 0 |
| Reaction sort without an asset | HTTP 400 |
| Total events | 7,878 |
| Asset counts | BTC 2,593; ETH 7,374; SOL 452 |

Average coverage is BTC 2,548 non-NULL / 45 NULL, ETH 7,337 / 37, and
SOL 26 / 426. These NULLs are intentionally not synthesized.

## Automated and browser checks

- `npm run lint`: PASS
- `npm run typecheck`: PASS
- `npm run test`: PASS — 4 files, 24 tests
- `npm run build`: PASS — production build
- `npm run security:bundle`: PASS — 25 client files checked
- `npm run smoke:browser`: PASS in real headless Chrome
  - 390 px viewport: `innerWidth=390`, `scrollWidth=390`
  - Average ETH metric: `+5.95%`
  - Top losers switched it to `-6.46%` and updated the URL
  - 1h switched the card metric to `ETH after 1 hour: -9.76%`
  - typing did not start a search; submitting did
  - All events removed asset, reaction sort, and market-data-only state

Screenshots: `reports/homework6-desktop.png` and
`reports/homework6-mobile.png`.

## Integrity and security

- Event IDs match the canonical Parquet exactly.
- All 18 database reaction fields match the canonical Parquet within floating
  serialization precision; no reaction field was updated by this migration.
- Parquet SHA-256 before and after:
  `78CC72F91BBD3CFBA595FF843486D2E8B82E4EA10A31F68666CE613C6D8EC833`.
- RLS remains enabled.
- Policy remains `events_public_read_only`, `SELECT`, role `anon`.
- `anon` still has only the `SELECT` table privilege.
- FTS remains operational (`ethereum` live check returned 1,318 rows).

## Changed files

- `database/migrations/004_add_average_reactions.sql`
- `database/README.md`
- `frontend/types/events.ts`
- `frontend/lib/reactions.ts`
- `frontend/lib/events-filters.ts`
- `frontend/lib/validation/events-query.ts`
- `frontend/lib/data/events.ts`
- `frontend/components/events-explorer.tsx`
- `frontend/components/event-card.tsx`
- `frontend/lib/reactions.test.ts`
- `frontend/lib/events-filters.test.ts`
- `frontend/lib/validation/events-query.test.ts`
- `frontend/scripts/browser-smoke.mjs`
- `frontend/package.json`
- `reports/homework6-desktop.png`
- `reports/homework6-mobile.png`
- `reports/homework6-final-report.md`

## Known limitations

- Production deployment was intentionally not started.
- SOL has only 26 events with at least three available horizon values; the
  other 426 stay NULL and are filtered by quick actions.
- Archival source titles such as `Document` were not rewritten because title
  cleanup, reclassification, and dataset mutation were outside this task.
