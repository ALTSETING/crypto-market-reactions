# Asset reclassification baseline

Captured on 2026-08-23 before classifier or dataset changes.

## Source snapshot

- Dataset: `data/website/events_mvp.parquet`
- Backup: `data/website/backups/events_mvp.pre_asset_reclassification_20260823.parquet`
- Source bytes: 2,168,296
- Backup bytes: 2,168,296
- Source SHA-256: `07db9074069310bd2f8d4ca66af44b6c76a8a0059a04b41dbcfff0510b985988`
- Backup SHA-256: `07db9074069310bd2f8d4ca66af44b6c76a8a0059a04b41dbcfff0510b985988`
- Exact backup copy verified: yes

## Baseline counts

| Metric | Value |
|---|---:|
| Total events | 7,878 |
| Unique event IDs | 7,878 |
| Events related to BTC | 479 |
| Events related to ETH | 7,450 |
| Events related to SOL | 110 |
| SOL events from SEC | 83 |
| Generic Coinbase filing titles among SOL events | 74 |
| Events assigned BTC + ETH + SOL | 74 |
| Events with no related assets | 0 |

`related_assets` counts are membership counts and therefore are not mutually exclusive.

## Semantic asset relevance distribution

The canonical inventory contains 8,039 event/asset rows for 7,878 events.

| Range | Rows |
|---|---:|
| 0.00–0.05 | 469 |
| >0.05–0.10 | 872 |
| >0.10–0.25 | 1,042 |
| >0.25–0.50 | 2,129 |
| >0.50–0.75 | 2,302 |
| >0.75–1.00 | 1,225 |

Overall relevance: min `0.01`, p25 `0.20`, median `0.45`, p75 `0.70`, max `1.00`.

SOL relevance: 110 rows; min `0.01`, p25 `0.02`, median `0.06`, p75 `0.62`, max `1.00`.

## Why earlier SOL counts differ (101 versus 110)

Both values are reproducible but measure different things:

- `110` is the number of events whose `related_assets` contains `SOL`.
- `101` is the number of those events with complete SOL market-reaction coverage at every published horizon.
- The remaining 9 SOL-classified events have incomplete SOL reaction coverage.

The difference is therefore a classification count versus a complete-market-data coverage count, not a row-count inconsistency.

## Known baseline defect

Generic Coinbase SEC filing metadata is assigned to BTC, ETH and SOL even when no specific asset is present in the available title/body. The 74 generic Coinbase filings account for every current three-asset assignment and dominate the 83 SEC rows in the SOL selection.
