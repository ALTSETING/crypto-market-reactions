# Asset classification correction report

Date: 2026-08-23  
Scope: all 7,878 website events and live Supabase `public.events`

## 1. Root cause

The local high-impact detector treated general crypto vocabulary as a market-wide
asset assignment. When it found terms such as `cryptocurrency` or `digital
assets` without a concrete coin, it returned BTC, ETH and SOL. The SEC adapter
also injected issuer descriptors into its synthetic EDGAR metadata body. A
generic Coinbase filing therefore acquired three low-relevance event/asset rows,
and the website builder copied those rows directly into `related_assets`.

The frontend was not defective: its `related_assets @>` filter correctly exposed
the contaminated data.

## 2. New classification logic

- General crypto terms contribute to crypto relevance but never create an asset.
- BTC requires Bitcoin/BTC evidence with token boundaries.
- ETH requires Ethereum/ETH/Ether evidence with token boundaries.
- SOL requires Solana, `$SOL`, uppercase `SOL`, or a contextual `sol` phrase.
- Labelled company/source/issuer metadata and prior relevance-score fragments are
  removed before evidence detection.
- `Solana Beach`, including footnote-separated forms such as `Solana 2 Beach`, is
  treated as a geographic phrase rather than blockchain evidence.
- An explicit title mention is sufficient.
- A body-only mention requires existing semantic relevance of at least 0.05;
  known metadata-only scores of 0.02–0.03 do not qualify.
- Multiple explicitly evidenced assets are retained in deterministic BTC, ETH,
  SOL order.
- A general crypto event may have `related_assets = []` and `primary_asset = NULL`.
- Synthetic SEC filing bodies no longer include issuer descriptors as content;
  the descriptor remains only in raw metadata.

## 3. Baseline and backup

The baseline was recorded before changes in
`docs/ASSET_RECLASSIFICATION_BASELINE.md`.

| Artifact | SHA-256 |
|---|---|
| Old Parquet | `07db9074069310bd2f8d4ca66af44b6c76a8a0059a04b41dbcfff0510b985988` |
| Old Parquet backup | `07db9074069310bd2f8d4ca66af44b6c76a8a0059a04b41dbcfff0510b985988` |
| New Parquet | `78cc72f91bbd3cfba595ff843486d2e8b82e4ea10a31f68666ce613c6d8ec833` |
| Live classification Parquet backup | `b8102973a72a7f4ee1d50f126a50149a1416f4c710ce097a7894653c2b2bb1e3` |
| Live classification CSV backup | `ca7edf155db741e1ffc4c67ca94f9e215eb4f43aeb1272dcfdc802d4be905dfd` |

The old/new Parquet comparison found zero differences outside
`primary_asset` and `related_assets`. Event IDs, titles, timestamps, URLs,
semantic labels and every market-reaction field are unchanged.

## 4. Before/after metrics

| Metric | Before | After | Difference |
|---|---:|---:|---:|
| Total events | 7,878 | 7,878 | 0 |
| Related BTC | 479 | 2,593 | +2,114 |
| Related ETH | 7,450 | 7,374 | -76 |
| Related SOL | 110 | 452 | +342 net |
| SOL from SEC | 83 | 8 | -75 |
| Generic Coinbase filings in SOL | 74 | 0 | -74 |
| BTC + ETH + SOL assignments | 74 | 141 | +67 |
| Empty `related_assets` | 0 | 303 | +303 |
| Changed `related_assets` rows | — | 2,993 | — |
| Changed `primary_asset` rows | — | 229 | — |

Of the original 110 SOL assignments, 35 were retained and 75 false positives
were removed: 74 generic Coinbase filings plus one `Solana Beach` mortgage
document. The corrected title evidence added 417 previously missed SOL events
from CoinDesk, Decrypt and Cointelegraph, producing the final total of 452.

The historical values 101 and 110 measured different properties: 110 events
were classified as SOL, while 101 had complete SOL reaction coverage. Reaction
data was intentionally not modified; complete SOL coverage remains 101 after
classification expands to 452 events.

## 5. Tests and dry-runs

- New regression suite reproduced the old bug with 3 failures before the fix.
- Focused post-fix checks: 27 passed after the final geographic-context case was
  added.
- Full Python suite: 367 passed, 22 third-party deprecation warnings.
- Importer dry-run: 7,878 rows, 7,878 unique event IDs and slugs.
- Live comparison dry-run: 2,993 predicted changed rows; 0 slug/category/
  sentiment/sentiment-score/importance mismatches.
- First classification-only update: 2,993 changed rows.
- Second classification-only update: 0 changed rows (idempotency confirmed).
- Frontend: ESLint PASS, TypeScript PASS, 9 Vitest tests PASS, production build
  PASS, client-bundle security scan PASS.

## 6. Supabase verification

- Target project ref verified before write.
- Total / unique event IDs / unique slugs: 7,878 / 7,878 / 7,878.
- Live classification matches the new local Parquet for all 7,878 rows.
- RLS remains enabled.
- `anon` retains only `SELECT`; `authenticated` and `PUBLIC` have no table grant.
- The sole public policy remains `events_public_read_only` for anon SELECT.
- All eight expected indexes remain present.
- `search_vector` remains `GENERATED ALWAYS`; `ethereum ETF` returns 107 rows.
- Live API filters return BTC 2,593; ETH 7,374; SOL 452; SOL+SEC 8.
- SOL + generic Coinbase filing search returns 0.
- SOL page 2 returns 20 rows; pagination total is 23 pages at 20/page.
- The original Coinbase filing slug still resolves with HTTP 200; only its
  incorrect asset classification changed.

Machine-readable verification:
`reports/supabase_asset_reclassification_verification.json`.

## 7. SOL review

- Full 452-row review CSV: `reports/sol_asset_review.csv`.
- Manual 20-event review across SEC, Solana GitHub, CoinDesk, Decrypt and
  Cointelegraph: `reports/SOL_ASSET_MANUAL_REVIEW.md`.
- Manual review found the `Solana Beach` false positive; it was fixed and the
  complete dataset was rebuilt before the final 20/20 PASS review.

## 8. Import and schema safety

Migration `003_allow_empty_related_assets.sql` removes only the obsolete
non-empty-array requirement; the supported-value subset CHECK remains.

The new `--classification-only` importer mode:

1. requires the live table to contain exactly the same 7,878 unique event IDs
   and slugs;
2. stages all classifications in a transaction;
3. requires every staged event ID to match;
4. updates only `primary_asset`, `related_assets`, and `updated_at`;
5. verifies counts and uniqueness before commit;
6. updates only rows whose classification is actually different.

`pd.NaT` continues to serialize as PostgreSQL NULL through the existing COPY
guard.

## 9. Changed files and generated artifacts

Core logic and schema:

- `high_impact_sources/parsers/crypto_relevance_detector.py`
- `high_impact_sources/sources/sec_source.py`
- `scripts/processing/build_website_dataset.py`
- `scripts/database/import_events.py`
- `database/migrations/001_create_events.sql`
- `database/migrations/003_allow_empty_related_assets.sql`

Tests and operational checks:

- `tests/test_high_impact_asset_classification_regression.py`
- `tests/test_high_impact_relevance.py`
- `tests/test_website_asset_classification.py`
- `tests/test_import_events.py`
- `scripts/processing/review_sol_classification.py`
- `scripts/database/backup_event_classification.py`
- `scripts/database/apply_sql_migration.py`
- `scripts/database/verify_asset_reclassification.py`

Generated data/reports and documentation:

- `data/website/events_mvp.parquet`
- `data/website/events_mvp.csv`
- `data/website/backups/events_mvp.pre_asset_reclassification_20260823.parquet`
- `data/website/backups/supabase_events_classification_pre_20260823.{parquet,csv}`
- `reports/sol_asset_review.csv`
- `reports/SOL_ASSET_MANUAL_REVIEW.md`
- `reports/supabase_asset_reclassification_verification.json`
- `docs/ASSET_RECLASSIFICATION_BASELINE.md`
- `docs/ASSET_RECLASSIFICATION_REPORT.md`
- `docs/WEBSITE_DATASET_REPORT.md`
- `docs/DATABASE_MVP_REPORT.md`
- `docs/SUPABASE_LIVE_IMPORT_REPORT.md`
- `database/README.md`

## 10. Known limitations

- The classifier is deterministic lexical evidence plus an existing semantic
  relevance gate for body-only mentions; it is not full document-level entity
  linking.
- 303 general crypto events intentionally have no supported related asset.
- Some older SEC events retain generic titles such as `Document`; the eight SEC
  events still assigned to SOL have explicit body evidence and were separately
  reviewed.
- Newly discovered title-level SOL assignments from dataset A may have a blank
  historical SOL relevance score because that old semantic run emitted only an
  ETH row. Their title is the assignment evidence recorded in the review CSV.
- Classification does not synthesize missing SOL reaction values. The 101-event
  complete SOL reaction set remains unchanged.

## 11. Completion statement

All 7,878 events were reclassified without deletion or duplication. The new
Parquet and Supabase contain the same classifications, generic Coinbase filings
without explicit Solana evidence no longer appear in the SOL filter, security
and search contracts remain intact, and total events remain exactly 7,878.
