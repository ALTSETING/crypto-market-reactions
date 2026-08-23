# Stage 16B — Historical High-Impact Backfill

## Status

`PASS_SOURCE_ARCHIVE__NO_MARKET_COVERAGE`

The free official-source archive was expanded without changing Stage 8–17 data, calling OpenAI, reading the opened Stage 17 test, training ML, or trading.

## Results

- Retrieved source records: 2,909.
- Accepted source records before deduplication: 364.
- New canonical events: 326.
- New event-asset rows: 326.
- Fully covered rows: 0.
- Duplicates mapped: 10; rejected records: 2,545.
- Earliest usable market timestamp with 12h pre-context: BTC/ETH/SOL = 2023-01-01T12:00:00+00:00.
- All historical candidates precede available 1m candles, so they remain `market_data_unavailable` and are excluded from reaction/Stage 17B datasets.
- Estimated semantic v2.1 candidates: 326; input tokens 370,787; output tokens 76,284; estimated Batch cost $0.1226.
- SEC bulk archive was accessed with HTTP Range and only matched CIK JSON entries were read; the complete ~1.55GB archive was not extracted because only ~4GB disk space was available.
- GitHub collection is bounded to one historical page per channel/repository; unavailable/unauthenticated channels are documented rather than inferred.
- Pytest: PASS (237 passed).
- Protected Stage 8–17 artifacts/tables unchanged: True.

## Stop gate

No AI Batch was submitted. No Stage 17B ML, paper trading, real trading, or next stage was started. Historical candles before 2023 must be acquired and audited before these source records can become reaction observations.
