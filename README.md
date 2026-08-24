# Crypto Market Reaction Database — data foundation

Це підготовлена копія старого AI-бота для дослідження криптовалютних новин. Нове призначення репозиторію — бути джерелом даних і processing-коду для **Crypto Market Reaction Database**: пошуку історичних подій та перегляду реакції BTC, ETH і SOL після публікації.

Frontend MVP реалізовано окремо в `frontend/`: homepage, server-side full-text search, asset/date/source filters, pagination і event pages за slug. CSV export залишається майбутньою функцією.

## Головний локальний dataset

Найповніший знімок: `data/stage18b/canonical_inventory.parquet`.

- 8 039 рядків `event × asset`;
- 7 878 унікальних `canonical_event_id`;
- 6 851 запис основного старого news-корпусу (dataset A);
- діапазон дат: 2017-01-03 — 2026-07-01 UTC;
- 8 039 title і URL, 8 021 непорожній body;
- AI semantic fields, source metadata, asset, deduplication та split metadata.

Пов’язані розраховані реакції лежать у `data/stage18b/canonical_market.parquet`: 8 039 рядків, із них 7 947 мають повне market coverage. Детальні хвилинні event-window paths збережені у `data/stage18/price_paths/` (11 451 627 рядків).

Повний аудит форматів, сирих/оброблених даних і обмежень: [docs/REPOSITORY_AUDIT.md](docs/REPOSITORY_AUDIT.md).

## Website MVP export

Derived dataset для майбутнього PostgreSQL/Supabase import:

- `data/website/events_mvp.parquet` — canonical typed export;
- `data/website/events_mvp.csv` — review/import copy;
- [docs/WEBSITE_DATASET_REPORT.md](docs/WEBSITE_DATASET_REPORT.md) — methodology, provenance, coverage і quality checks.

Відтворити export без зміни master datasets:

```powershell
python -m scripts.processing.build_website_dataset
```

## PostgreSQL / Supabase database layer

Website-ready schema та idempotent importer підготовлені окремо від legacy research tables:

- `database/migrations/001_create_events.sql`;
- `database/migrations/002_enable_events_readonly_rls.sql`;
- `scripts/database/import_events.py`;
- `database/checks/verify_events.sql`;
- [docs/DATABASE_MVP_REPORT.md](docs/DATABASE_MVP_REPORT.md);
- [docs/SUPABASE_LIVE_IMPORT_REPORT.md](docs/SUPABASE_LIVE_IMPORT_REPORT.md).

Безпечна локальна перевірка без database write:

```powershell
python -m scripts.database.import_events --dry-run
```

## Структура

```text
eth_news_trading_bot/
├── data/                       # захищені raw та processed datasets
│   ├── raw/                    # офіційні Binance monthly 1m ZIP
│   ├── stage12..stage18b/      # версійовані processed datasets
│   └── archive/                # місце для майбутніх immutable snapshots
├── crawler/                    # збір і нормалізація новин
├── database/                   # SQLAlchemy schema, repositories, Alembic
├── historical_market_data/     # import/validation/coverage старих candles
├── market/                     # Binance client та базовий reaction calculator
├── analysis/                   # AI-analysis та частина research/audit логіки
├── ml/                         # legacy builders, потрібні частині data pipeline
├── scripts/                    # import, processing та legacy research entrypoints
├── reports/                    # збережені AI outputs, audits і research results
├── models/                     # збережені моделі та metadata (архівні результати)
├── docs/
├── frontend/                   # Next.js MVP для live Supabase events
└── website/                    # попередня документація/резерв
```

## Frontend MVP

Інструкції запуску, environment variables, security model і production notes:
[frontend/README.md](frontend/README.md).

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
npm run dev
```

## GitHub transfer

The repository is prepared for GitHub with Git LFS rules for Parquet, CSV,
JSONL, ZIP, and Joblib artifacts. The local Scrapy HTTP cache, virtual
environments, build output, logs, and environment files are intentionally not
versioned.

Before the first push:

```powershell
git lfs install
git add .
git status
git commit -m "Initial GitHub import"
git remote add origin <repository-url>
git push -u origin main
```

The frontend CI workflow runs lint, typecheck, unit tests, production build,
and client-bundle credential scanning without downloading the research LFS
archive. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

No open-source license is included yet. Add the license selected by the owner
before making the repository public; without one, reuse rights are not granted.

Поточна stage-based структура залишена навмисно: її насильне переміщення зламало б manifest paths, hashes і відтворюваність старих pipeline. Нові website/import компоненти слід додавати окремо, не переписуючи захищені артефакти.

## Дані, які не можна видаляти

Не видаляйте `data/`, `datasets/`, змістовні файли в `reports/`, `models/`, `patterns/` або `.scrapy/httpcache/`. У репозиторії немає локального SQLite/PostgreSQL dump, тому Parquet/CSV/JSONL залишаються фактичним локальним архівом навіть після імпорту website dataset у Supabase.

## PostgreSQL/Supabase status

Production Supabase `public.events` містить 9 073 унікальні події та slug: захищений 7 878-event Reaction V2 dataset і 1 195 історичних подій, доданих у режимі insert-new-only. Migration 006 та manifest-driven import застосовані; migration 008 підготовлена, але навмисно не застосована. Search, filters, slug lookup, RLS, server-only access і post-import identity checks пройшли перевірку.

Детальний checklist: [docs/POSTGRES_IMPORT_PREPARATION.md](docs/POSTGRES_IMPORT_PREPARATION.md).

## Відтворюване середовище

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` не можна додавати до Git. Старі PostgreSQL/Alembic та data-processing компоненти збережені для читання архіву й відтворення reaction data.

## Аудит очищення

Видалено лише порожні trading/CLI stubs і застарілий PID-файл. Історичні дані, AI outputs, market data та research results не видалялися. Деталі: [docs/CLEANUP_REPORT.md](docs/CLEANUP_REPORT.md).
