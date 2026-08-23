# Supabase Live Import Report

Date: 2026-08-22  
Dataset: `data/website/events_mvp.parquet`

## 1. Connection status

- Status: **PASS**.
- Target database: `postgres`; connected database role: `postgres`.
- The Direct Connection host resolved only to IPv6, which was unavailable from
  the current workstation. Live work therefore used the Supabase Session pooler
  in `eu-west-1` over IPv4 and TLS.
- The database password and full `DATABASE_URL` were never printed or written
  to source files. `.env` is excluded by `.gitignore`; `.env.example` contains
  only a placeholder.

## 2. Migration status

- `database/migrations/001_create_events.sql`: **applied successfully** in one
  transaction to an initially clean database state.
- `database/migrations/002_enable_events_readonly_rls.sql`: **applied
  successfully** after import and verification.
- `public.events` exists with 49 columns, one primary key, one UNIQUE slug
  constraint, a generated `tsvector`, 12 total constraints, and 8 indexes.

## 3. Actual schema

The live schema matches the migration. The groups below list all 49 columns.

| Group | Live PostgreSQL columns |
|---|---|
| Required event text/time | `event_id text`, `slug text`, `title text`, `published_at timestamptz`, `source text`, `source_url text` |
| Classification | `primary_asset text NULL`, `related_assets text[]`, `category text`, `sentiment text NULL`, `sentiment_score float8 NULL`, `importance float8 NULL` |
| AI/archive metadata | `ai_schema_version text`, `ai_prompt_version text NULL`, `ai_original_scale text`, `archive_dataset_source text`, `archive_member_id text`, `reaction_methodology text`, `reaction_value_unit text` |
| BTC | `btc_1m`, `btc_5m`, `btc_15m`, `btc_1h`, `btc_4h`, `btc_24h` as `float8 NULL`; `btc_reaction_source text NULL`; `btc_reference_time timestamptz NULL`; `btc_reference_latency_minutes int4 NULL` |
| ETH | `eth_1m`, `eth_5m`, `eth_15m`, `eth_1h`, `eth_4h`, `eth_24h` as `float8 NULL`; `eth_reaction_source text NULL`; `eth_reference_time timestamptz NULL`; `eth_reference_latency_minutes int4 NULL` |
| SOL | `sol_1m`, `sol_5m`, `sol_15m`, `sol_1h`, `sol_4h`, `sol_24h` as `float8 NULL`; `sol_reaction_source text NULL`; `sol_reference_time timestamptz NULL`; `sol_reference_latency_minutes int4 NULL` |
| Database-managed | `search_vector tsvector GENERATED ALWAYS`, `created_at timestamptz`, `updated_at timestamptz` |

All columns not explicitly marked `NULL` above are `NOT NULL`, except
`search_vector`, which PostgreSQL reports as nullable in `information_schema`
while also reporting it as `GENERATED ALWAYS`.

Live indexes:

1. `events_pkey` — unique btree on `event_id`.
2. `events_slug_key` — unique btree on `slug`.
3. `ix_events_published_at` — btree on `published_at DESC`.
4. `ix_events_source` — btree on `source`.
5. `ix_events_primary_asset` — partial btree on non-null `primary_asset`.
6. `ix_events_category` — btree on `category`.
7. `ix_events_related_assets_gin` — GIN on `related_assets`.
8. `ix_events_search_vector_gin` — GIN on `search_vector`.

Checks constrain non-empty title/source/URL, supported asset values,
supported (possibly empty) `related_assets`, archive source, percent reaction units, and
non-negative reference latency.

## 4. Import result

The first write attempt exposed a nullable-timestamp serialization defect:
`pd.NaT` was emitted as `"NaT"` instead of PostgreSQL `\N`. PostgreSQL rejected
the staging COPY and the transaction rolled back; `public.events` remained at
zero rows. `copy_value()` was corrected and a regression assertion was added.

First successful import:

- elapsed wall time: **11.262 s**;
- merged rows: **7,878**;
- matched dataset rows: **7,878**;
- total table rows: **7,878**.

The source Parquet was not modified.

## 5. Idempotency

The importer was run a second time against the same Parquet:

- elapsed wall time: **10.932 s**;
- merged rows: **7,878**;
- matched dataset rows: **7,878**;
- total table rows after the second run: **7,878**;
- unique `event_id`: **7,878**;
- unique `slug`: **7,878**.

The staging COPY plus `ON CONFLICT (event_id) DO UPDATE` path is idempotent for
the current dataset.

## 6. Verification results

`database/checks/verify_events.sql` executed successfully against Supabase.

| Check | Live result |
|---|---:|
| Total events | 7,878 |
| Unique event IDs | 7,878 |
| Unique slugs | 7,878 |
| Missing titles | 0 |
| Missing source URLs | 0 |
| Missing publication timestamps | 0 |
| Null sentiment | 313 |
| Null importance | 313 |
| Duplicate URL groups / extra rows | 0 / 0 |
| BTC complete 1m–24h coverage | 7,285 |
| ETH complete 1m–24h coverage | 7,412 |
| SOL complete 1m–24h coverage | 101 |
| Minimum `published_at` | 2017-01-03 10:48:14 UTC |
| Maximum `published_at` | 2026-07-01 00:00:00 UTC |

All expected dataset-level values matched exactly.

## 7. Live full-text search

Search used the generated `search_vector`,
`websearch_to_tsquery('english', query)`, rank ordering, and a five-row limit.
Client times include the remote network round trip; PostgreSQL execution times
are recorded separately in the performance section.

### `ethereum etf`

- Matches: **107**; client query time: **53.572 ms**.
- Top titles:
  1. *Ethereum ETF Inflows Outpace Bitcoin ETFs for Fifth Straight Day* — 2025-08-15 — decrypt.
  2. *Bitcoin ETF Giant BlackRock Files to Launch Ethereum Staking ETF* — 2025-12-08 — decrypt.
  3. *BlackRock Forms New Trust Amid Early Uptake of Staking-Focused Ethereum ETFs* — 2025-11-20 — decrypt.
  4. *BlackRock Files With SEC to Include Staking in Ethereum ETF* — 2025-07-17 — decrypt.
  5. *Trump Media Files to Launch Truth Social Bitcoin and Ethereum ETF* — 2025-06-16 — decrypt.

### `sec ethereum`

- Matches: **90**; client query time: **46.622 ms**.
- Top titles:
  1. *Coinbase Releases Treasure Trove of SEC Docs on Ethereum, XRP and More* — 2025-05-07 — decrypt.
  2. *SEC Punts on BlackRock Ethereum ETF Staking, Franklin XRP and Solana Fund Decisions* — 2025-09-10 — decrypt.
  3. *SEC Halts Trading of Bitcoin, Ethereum Treasury Firm QMMM After 2,000% Stock Surge* — 2025-09-29 — decrypt.
  4. *SEC Exempts Liquid Stakers Like Ethereum’s Lido, Solana’s Jito From Securities Laws* — 2025-08-05 — decrypt.
  5. *BlackRock Files With SEC to Include Staking in Ethereum ETF* — 2025-07-17 — decrypt.

### `binance hack`

- Matches: **2**; client query time: **45.768 ms**.
- Results:
  1. *Users of Binance-owned Trust Wallet lose $7 million to hacked Chrome extension* — 2025-12-26 — coindesk.
  2. *Binance, Kraken Thwarted Social Engineering Attacks Similar to Coinbase Hack* — 2025-05-19 — coindesk.

### `blackrock bitcoin`

- Matches: **31**; client query time: **46.458 ms**.
- Top titles:
  1. *Bitcoin (BTC) price news: Whale dumps $1.29 billion of BlackRock's bitcoin ETF in a dark pool trade* — 2026-05-27 — coindesk.
  2. *Abu Dhabi Funds Boosted BlackRock Bitcoin ETF Exposure to $1 Billion by End of 2025: Filings* — 2026-02-17 — decrypt.
  3. *Public Keys: BlackRock Bitcoin Fee Frenzy, S&P Catchall and New York Stakes* — 2025-10-10 — decrypt.
  4. *JPMorgan to Allow BlackRock Bitcoin ETF Shares as Loan Collateral* — 2025-06-04 — decrypt.
  5. *Wisconsin Pension Fund Sold $300M BlackRock Bitcoin ETF Stake Amid Tariff Turmoil, New Filing Shows* — 2025-05-16 — decrypt.

## 8. Filter tests

| Filter | Matching rows |
|---|---:|
| `primary_asset = ETH` | 7,368 |
| `primary_asset = BTC` | 392 |
| `primary_asset = SOL` | 31 |
| Date `2023-01-01 <= published_at < 2026-01-01` | 4,324 |
| Source `coindesk` | 3,646 |
| Category `institutional_adoption` | 1,669 |
| `related_assets` contains ETH | 7,450 |
| `related_assets` contains BTC | 479 |
| `related_assets` contains SOL | 110 |
| Search `ethereum etf` + primary ETH + 2023–2025 | 87 |

All asset, date, source, category, array, and combined filters completed without
errors and returned rows satisfying their predicates.

## 9. Slug tests

Ten deterministic pseudo-random slugs were queried individually through
`WHERE slug = $1`. All ten returned exactly one row. The live UNIQUE constraint
and unique btree index are present.

## 10. RLS and grants

RLS is enabled on `public.events`. The sole policy is:

```sql
CREATE POLICY events_public_read_only
ON public.events
FOR SELECT
TO anon
USING (true);
```

Effective table privileges:

| Role | SELECT | INSERT | UPDATE | DELETE |
|---|---:|---:|---:|---:|
| `anon` | yes | no | no | no |
| `authenticated` | no | no | no | no |

`SET ROLE anon; SELECT count(*) FROM public.events` returned 7,878 rows. No
public write policy exists. Database-owner and service-role credentials must
remain server-only.

No custom bulk-download endpoint was created. However, any public row-level
SELECT API can potentially be enumerated through repeated pagination. Before a
commercial public launch, configure an appropriate API row cap/rate limit or
serve controlled search through a backend/RPC if dataset extraction is a
commercial concern.

## 11. Storage size

| Measurement | Bytes | MiB |
|---|---:|---:|
| `public.events` table | 15,482,880 | 14.77 |
| Events indexes | 8,413,184 | 8.02 |
| Table plus indexes/TOAST | 23,896,064 | 22.79 |
| Entire database | 34,434,195 | 32.84 |

The current Supabase Free plan advertises a 500 MB database-size allowance on
the [official pricing page](https://supabase.com/pricing). The whole database is
currently about 6.9% of 500 MB (decimal comparison), leaving ample MVP room.
Storage should still be monitored as new events and indexes are added.

## 12. Query performance

`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` results from the live database:

| Query | Planning | Execution |
|---|---:|---:|
| Full-text `ethereum etf` | 0.238 ms | 0.370 ms |
| Slug lookup | 0.223 ms | 0.040 ms |
| Latest 25 events | 0.123 ms | 0.051 ms |
| ETH asset filter, limit 25 | 0.091 ms | 0.279 ms |
| Search plus 2023–2025 range | 0.173 ms | 0.181 ms |

The slug query used an Index Scan. At 7,878 rows all five operations are well
below 1 ms of server execution, so no additional indexes are justified now.
Observed end-to-end search calls were roughly 46–54 ms because they include the
remote network round trip.

## 13. Smoke test

Twenty deterministic pseudo-random events were loaded independently from
Supabase and compared with the locally prepared import frame.

- Rows requested/returned: **20/20**.
- Fields compared per row: **46** (the 45 dataset fields plus deterministic
  `slug`).
- Total value comparisons: **920**.
- Mismatches: **0**.
- Checks covered IDs, titles, timestamps, sources, arrays, all BTC/ETH/SOL
  reaction fields, slugs, floats with tight tolerance, and NULL semantics.

## 14. Dataset integrity

SHA-256 after all database work:

```text
07DB9074069310BD2F8D4CA66AF44B6C76A8A0059A04B41DBCFFF0510B985988
```

It exactly matches the pre-import hash. The Parquet was not modified.

## 15. Problems found and resolution

1. Direct PostgreSQL resolved only to IPv6 and was unreachable from this
   workstation. Resolution: use the Supabase IPv4 Session pooler.
2. A database-password reset required a short propagation interval before the
   pooler accepted it. No write was attempted before read-only connectivity
   succeeded.
3. Nullable pandas `NaT` was not recognized by COPY serialization. PostgreSQL
   rejected the first staging COPY and rolled back. The importer now maps
   `pd.NaT` to `\N`; the regression suite passes.
4. Anonymous SELECT necessarily exposes rows through the Supabase data API.
   There is no one-shot CSV endpoint, but pagination controls/rate limiting are
   still recommended before public commercial launch.

## 16. Frontend readiness

**Database status: ready for controlled MVP frontend integration.** Schema,
import, idempotency, full-text search, filters, slug lookup, reaction values,
RLS, storage, and source-data fidelity all passed live verification.

Before unrestricted public launch, decide and enforce the intended pagination,
maximum-row, and rate-limit policy. If authenticated access is added later, it
requires a separate explicit RLS policy because `authenticated` currently has
no privileges.

## 17. Asset reclassification update (2026-08-23)

Migration `003_allow_empty_related_assets.sql` was applied after a live export
of classification fields. It preserves `related_assets NOT NULL` while allowing
an empty array when a crypto-relevant event contains no explicit BTC/ETH/SOL
evidence.

The controlled `--classification-only` update matched all 7,878 event IDs and
changed 2,993 rows. A second identical run changed 0 rows. It updates only
`primary_asset`, `related_assets`, and `updated_at`; slug, category, sentiment,
importance, source fields and market reactions are not part of the update.

| Check | Result |
|---|---:|
| Total / unique event IDs / unique slugs | 7,878 / 7,878 / 7,878 |
| Related BTC | 2,593 |
| Related ETH | 7,374 |
| Related SOL | 452 |
| Empty `related_assets` | 303 |
| SOL from SEC | 8 |
| Generic Coinbase filings in SOL | 0 |
| FTS matches for `ethereum ETF` | 107 |

RLS remains enabled, `anon` retains only `SELECT`, the read-only policy is
unchanged, and all eight indexes (including GIN FTS and `related_assets`) remain
present. Full verification is stored in
`reports/supabase_asset_reclassification_verification.json`.
