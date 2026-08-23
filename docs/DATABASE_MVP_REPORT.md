# PostgreSQL / Supabase MVP database report

## Scope and source contract

The database layer is built for `data/website/events_mvp.parquet` without changing that file or any master dataset. The source has 7,878 rows, 7,878 unique `event_id` values and 45 columns.

Observed source types:

- strings: Arrow `large_string`;
- reactions and AI scores: Arrow `double`;
- `published_at` and per-asset reference times: `timestamp[us, tz=UTC]`;
- per-asset latency: nullable Arrow `int64`;
- `related_assets`: non-NULL JSON array string such as `["BTC","ETH"]` or `[]` for a general crypto event without explicit supported-asset evidence.

The PostgreSQL table has **49 columns**: 45 mapped source fields, `slug`, generated `search_vector`, `created_at` and `updated_at`.

## Final schema and Parquet mapping

| Parquet column | PostgreSQL column | PostgreSQL type | Nullable |
|---|---|---|---|
| `event_id` | `event_id` | `text PRIMARY KEY` | No |
| — | `slug` | `text UNIQUE` | No |
| `title` | `title` | `text` | No |
| `published_at` | `published_at` | `timestamptz` | No |
| `source` | `source` | `text` | No |
| `source_url` | `source_url` | `text` | No |
| `primary_asset` | `primary_asset` | `text`, BTC/ETH/SOL check | Yes, 87 |
| `related_assets` | `related_assets` | `text[]` | No |
| `category` | `category` | `text` | No |
| `sentiment` | `sentiment` | `text` | Yes, 313 |
| `sentiment_score` | `sentiment_score` | `double precision` | Yes, 313 |
| `importance` | `importance` | `double precision` | Yes, 313 |
| `ai_schema_version` | `ai_schema_version` | `text` | No |
| `ai_prompt_version` | `ai_prompt_version` | `text` | Yes, 313 |
| `ai_original_scale` | `ai_original_scale` | `text` | No |
| `archive_dataset_source` | `archive_dataset_source` | `text`, A/B/C check | No |
| `archive_member_id` | `archive_member_id` | `text` | No |
| `reaction_methodology` | `reaction_methodology` | `text` | No |
| `reaction_value_unit` | `reaction_value_unit` | `text`, `percent` check | No |
| `btc_1m` | `btc_1m` | `double precision` | Yes |
| `btc_5m` | `btc_5m` | `double precision` | Yes |
| `btc_15m` | `btc_15m` | `double precision` | Yes |
| `btc_1h` | `btc_1h` | `double precision` | Yes |
| `btc_4h` | `btc_4h` | `double precision` | Yes |
| `btc_24h` | `btc_24h` | `double precision` | Yes |
| `btc_reaction_source` | `btc_reaction_source` | `text` | Yes, 548 |
| `btc_reference_time` | `btc_reference_time` | `timestamptz` | Yes, 548 |
| `btc_reference_latency_minutes` | same | `integer` | Yes, 548 |
| `eth_1m` | `eth_1m` | `double precision` | Yes |
| `eth_5m` | `eth_5m` | `double precision` | Yes |
| `eth_15m` | `eth_15m` | `double precision` | Yes |
| `eth_1h` | `eth_1h` | `double precision` | Yes |
| `eth_4h` | `eth_4h` | `double precision` | Yes |
| `eth_24h` | `eth_24h` | `double precision` | Yes |
| `eth_reaction_source` | `eth_reaction_source` | `text` | Yes, 428 |
| `eth_reference_time` | `eth_reference_time` | `timestamptz` | Yes, 428 |
| `eth_reference_latency_minutes` | same | `integer` | Yes, 428 |
| `sol_1m` | `sol_1m` | `double precision` | Yes |
| `sol_5m` | `sol_5m` | `double precision` | Yes |
| `sol_15m` | `sol_15m` | `double precision` | Yes |
| `sol_1h` | `sol_1h` | `double precision` | Yes |
| `sol_4h` | `sol_4h` | `double precision` | Yes |
| `sol_24h` | `sol_24h` | `double precision` | Yes |
| `sol_reaction_source` | `sol_reaction_source` | `text` | Yes, 7,768 |
| `sol_reference_time` | `sol_reference_time` | `timestamptz` | Yes, 7,768 |
| `sol_reference_latency_minutes` | same | `integer` | Yes, 7,768 |
| — | `search_vector` | stored generated `tsvector` | No |
| — | `created_at` | `timestamptz DEFAULT now()` | No |
| — | `updated_at` | `timestamptz DEFAULT now()` | No |

Reaction values use `double precision` because the source is IEEE-754 double and these values are analytical percentage returns, not currency ledger amounts. Keeping them as ordinary columns makes filtering and CSV projection straightforward. SOL fields intentionally allow NULL.

## Search implementation

The table has a stored generated `search_vector`:

- title: English dictionary, weight A;
- source: simple dictionary, weight B;
- category: English dictionary, weight B.

A GIN index supports `search_vector @@ websearch_to_tsquery('english', query)`. This covers the expected phrase/term searches without embeddings. Filters on source, category, primary asset, related assets and dates use separate indexes and can be combined with the full-text predicate.

## Index set

Eight index structures are created:

1. primary-key B-tree on `event_id`;
2. unique B-tree on `slug`;
3. descending B-tree on `published_at`;
4. B-tree on `source`;
5. partial B-tree on non-NULL `primary_asset`;
6. B-tree on `category`;
7. GIN on `related_assets`;
8. GIN on `search_vector`.

Individual reaction indexes are intentionally omitted until a real query requires reaction-range filtering.

## Slug strategy

Format:

```text
<ascii-title-slug>-<publication-year>-<first-8-stable-event-token>
```

Example:

```text
sec-approves-ethereum-etf-2024-a81f2c12
```

The suffix is always present. This prevents current collisions and, unlike suffixing only current duplicates, keeps URLs stable when a future event with the same title/year is added. Slugs are lowercase ASCII, limited to 180 characters, deterministic, validated unique before connecting, and protected by a database UNIQUE constraint. They never depend on an auto-increment ID.

## Import and upsert strategy

`scripts/database/import_events.py` performs:

1. exact Parquet column/order and Arrow-type validation;
2. row-count, unique-ID, required-field, timestamp, finite-return and latency validation;
3. JSON parsing of `related_assets` into PostgreSQL arrays;
4. deterministic slug generation;
5. batches of 1,000 rows through PostgreSQL `COPY` into a temporary table;
6. `ON CONFLICT (event_id) DO UPDATE` into `public.events`;
7. a post-import match count for all 7,878 source IDs.

SQL NULL is used for pandas/Parquet NULL and NaN. Numeric zero remains a real zero. `created_at` is preserved on re-import; `updated_at` is refreshed. A repeated import cannot double the dataset.

## Supabase security

For a public site, enable RLS on `public.events`, add one SELECT-only policy for `anon`/`authenticated`, and explicitly revoke INSERT/UPDATE/DELETE/TRUNCATE from those roles. Run imports only from a trusted server or migration environment using a non-browser credential. Never expose `DATABASE_URL` or the service-role key.

RLS statements are documented in `database/README.md` rather than included in the portable migration because ordinary PostgreSQL installations do not have Supabase's `anon` and `authenticated` roles.

## Expected size

The source is approximately 2.17 MB compressed Parquet and 6.25 MB CSV. For 7,878 rows, a practical PostgreSQL estimate is roughly **15–30 MB total** for heap, TOAST data, generated tsvectors and the eight indexes. Actual size depends on PostgreSQL version and text compression. Verify after import with:

```sql
SELECT pg_size_pretty(pg_total_relation_size('public.events'));
```

## Validation status

- Importer dry-run: PASS.
- Exact source rows: 7,878.
- Unique generated slugs: 7,878.
- Importer tests: 5 passed.
- Local PostgreSQL runtime migration/import: not executed. No `psql` client was available and TCP port `localhost:5432` was closed.
- No external service was installed or started.

## Production risks and recommendations

- Dataset A and B/C retain different documented reaction latency methodologies. Preserve the metadata in API/CSV responses where reproducibility matters.
- SOL coverage is only 101 complete events; no NOT NULL constraint is placed on SOL reactions.
- After explicit-evidence reclassification, 316 events have no unambiguous primary asset; `related_assets` remains authoritative and may be empty.
- Sentiment, sentiment score, importance and AI prompt version have 313 NULL values.
- Generated English full-text search is appropriate for the current mostly English titles. Add a separate configuration only if multilingual content becomes material.
- The standalone SQL migration is for a fresh website table. If a table named `public.events` already exists with a different definition, inspect it before applying; `CREATE TABLE IF NOT EXISTS` does not reconcile schema drift.
- Run `ANALYZE public.events` after the first production import and inspect real query plans before adding more indexes.

## Commands for a future Supabase project

```powershell
# 1. Put the Supabase direct/session PostgreSQL URL in local .env.
Copy-Item .env.example .env

# 2. Validate locally without a database write.
python -m scripts.database.import_events --dry-run

# 3. Apply the schema with a PostgreSQL client.
psql $env:DATABASE_URL -v ON_ERROR_STOP=1 -f database/migrations/001_create_events.sql

# 4. Import/upsert all events.
python -m scripts.database.import_events

# 5. Verify counts, coverage and example queries.
psql $env:DATABASE_URL -v ON_ERROR_STOP=1 -f database/checks/verify_events.sql

# 6. Enable the reviewed Supabase RLS policy from database/README.md.
# 7. Update planner statistics.
psql $env:DATABASE_URL -c "ANALYZE public.events;"
```
