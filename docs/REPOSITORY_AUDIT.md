# Repository and dataset audit

Дата аудиту: 2026-08-22. Усі підрахунки зроблено read-only до очищення.

## Поточна архітектура

- `crawler/` — Scrapy spiders, parsing title/body/time, asset detection, validation, deduplication і запис у PostgreSQL.
- `database/` — SQLAlchemy models/repositories та Alembic migrations для news, assets, 1m candles, reactions і AI analysis.
- `market/` — Binance client, імпорт candles і базовий calculator для 5m/15m/30m/1h/4h/24h.
- `historical_market_data/` — офіційні Binance Vision archives, checksum/validation, gap audit і stage16c reactions.
- `analysis/`, `ml/`, `scripts/` — AI enrichment, canonicalization, feature building, reaction datasets та legacy ML/backtesting experiments.
- `data/` — основні versioned Parquet datasets, raw candle ZIP і minute-level event price paths.
- `reports/` — AI batch inputs/outputs, reaction exports, manifests, audits і попередні experiment results.

## Архів новин

Найповніша автономна копія — `data/stage18b/canonical_inventory.parquet`:

| Метрика | Значення |
|---|---:|
| Рядків event × asset | 8 039 |
| Унікальних canonical events | 7 878 |
| Унікальних member IDs | 7 891 |
| Основний старий корпус (dataset A) | 6 851 |
| High-impact/official records (dataset B) | 862 рядки / 714 events |
| Historical backfill (dataset C) | 326 |
| Date range | 2017-01-03 — 2026-07-01 UTC |
| URL | 8 039 / 8 039 |
| Canonical URL | 8 038 / 8 039 |
| Непорожній body | 8 021 / 8 039 |

Asset rows: ETH 7 450, BTC 479, SOL 110. Основні sources: CoinDesk 3 646, Decrypt 2 404, Cointelegraph 801, SEC 657, Ethereum GitHub 245, ETH GitHub 170, BTC GitHub 67, SOL GitHub 27, Ethereum Foundation 22.

Формат — Apache Parquet. Важливі групи колонок:

- identity/content: `member_id`, `canonical_event_id`, `published_at`, `source`, `url`, `canonical_url`, `title`, `body`, `content_hash`;
- relation: `asset`, `symbol`, `event_group_id`, `dataset_source`, `source_mappings`;
- AI: `sem_relevance`, `sem_content_valence(_score)`, `sem_importance`, `sem_novelty`, `sem_confidence`, `sem_event_type` та інші semantic fields;
- provenance/deduplication: `normalized_url`, `normalized_title`, `text_fingerprint`, `duplicate_root`, prior-exposure/split fields.

`data/stage18/canonical_inventory.parquet` — попередня версія того самого inventory. `data/stage16b/source_records.parquet` (2 909 source records) і `event_source_records.parquet` зберігають детальнішу provenance для historical backfill. Окремого локального database dump немає; configured PostgreSQL на момент аудиту не працює.

## AI analysis

- `reports/stage9_eth_results.csv`: 7 065 news IDs з sentiment, importance, novelty, credibility, expected direction, category, confidence, relevance і token/cost metadata. Canonical dataset A після filtering/grouping містить 6 851 рядок.
- `reports/stage9_eth_batch_input.jsonl` та `stage9_eth_batch_output.jsonl`: збережені batch requests/responses.
- `reports/stage16_semantic_v21_results.csv`: 714 high-impact events із розширеною semantic schema.
- `reports/stage16_semantic_v21_*input/output.jsonl`: збережені batch artifacts.
- `data/stage18b/canonical_inventory.parquet`: інтегрований normalized snapshot. Базові semantic поля заповнені для 7 713–8 039 рядків; розширені high-impact поля — для 862 rows.

Embeddings-файлів або vector index під час аудиту не знайдено.

## Price reactions

- `data/stage18b/canonical_market.parquet`: 8 039 event-asset rows, 7 947 fully covered. Готові `raw_return_5m`, `10m`, `20m`, `40m`, `1h`, `90m`, `2h`, `3h`, `4h`, `5h`, `6h`, `8h`, `10h`, `12h`, `18h`, `24h`, а також MFE/MAE і pre-event context.
- `reports/stage16_market_reactions.parquet`: 3 340 latency-specific rows. Містить `return_1m`, `5m`, `10m`, `20m`, `40m`, `1h`, `3h`, `5h`, `8h`, `12h`, abnormal returns, volatility, volume shock і excursions.
- `reports/stage13a_eth_early_returns.parquet`: 6 851 ETH events із ранніми ETH/BTC reactions на 1m/2m/3m/5m/10m/15m.
- `market/reaction_calculator.py`: legacy calculator на exact 1m candle grid для 5m/15m/30m/1h/4h/24h.

Обмеження: готового уніфікованого набору `event × BTC/ETH/SOL × 1m/5m/15m/1h/4h/24h` немає. Stage18b переважно зберігає реакцію related asset; 1m і 15m не входять до його canonical market table.

## Market data

Raw official Binance monthly ZIP:

| Symbol | Interval | Files | Range | Size |
|---|---|---:|---|---:|
| BTCUSDT | 1m | 65 | 2017-08 — 2022-12 | 133.11 MiB |
| ETHUSDT | 1m | 65 | 2017-08 — 2022-12 | 122.18 MiB |
| SOLUSDT | 1m | 29 | 2020-08 — 2022-12 | 46.32 MiB |

Location: `data/raw/binance/spot/monthly/klines/<SYMBOL>/1m/`.

Derived event windows: `data/stage18/price_paths/`, partitioned by `asset/year/month`:

| Asset | Parquet partitions | Rows | Years |
|---|---:|---:|---|
| BTC | 88 | 625 394 | 2017–2026 |
| ETH | 104 | 10 680 692 | 2017–2026 |
| SOL | 45 | 145 541 | 2020–2026 |

Each path row contains event ID/time, `minute_offset`, OHLCV and raw open/high/low return percentages. These are processed event windows, not a complete standalone exchange-wide candle archive.

## Raw vs processed

Raw/recoverability-critical:

- `data/raw/**/*.zip` — Binance candles;
- `.scrapy/httpcache/` — 115 614 cached response files; potential raw article recovery source;
- AI batch input/output JSONL in `reports/`;
- `data/stage16b/source_records.parquet` — historical source records.

Processed but protected:

- `data/stage12/` through `data/stage18b/`;
- `datasets/**/*.parquet|csv`;
- substantive `reports/**/*.csv|json|jsonl|parquet|md`;
- `models/` and `patterns/` as experiment provenance;
- crawl/download/checksum/coverage manifests.

## Legacy research/trading code classification

- `trading/` contained only empty placeholders and was safe to remove.
- `ml/stage13_experiments.py`, `ml/stage14_utility.py`, `analysis/stage17*.py` and corresponding `run_stage13*`–`run_stage18*` entrypoints are ML/backtesting/research-oriented.
- They were retained because several also define canonicalization, CandleGrid, unified market construction, forensic hashes or price-path generation required to audit/rebuild the preserved datasets.
- Live order execution, Binance order placement, position management and functioning paper-trading code were not found.
