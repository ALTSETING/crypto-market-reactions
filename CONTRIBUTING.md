# Contributing

## Setup

Install Git LFS before cloning or adding historical dataset files:

```powershell
git lfs install
git clone <repository-url>
cd eth_news_trading_bot
```

For Python/data tooling:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

For the website:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
npm run dev
```

Never commit either environment file.

## Required checks

Before any commit, scan the exact files Git can see:

```powershell
python scripts/check_repository_ready.py
```

Python/data changes should run the relevant tests, or the full suite when they
touch shared code:

```powershell
python -m pytest -q
```

Frontend changes must pass:

```powershell
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
npm run security:bundle
```

The Chrome smoke test additionally requires a running production frontend and
Google Chrome at its standard Windows installation path:

```powershell
npm run start
npm run smoke:browser
```

## Data and migrations

- Do not rewrite protected historical datasets as part of unrelated changes.
- Parquet, CSV, JSONL, ZIP, and Joblib artifacts are tracked with Git LFS.
- Add database changes as a new numbered SQL migration; never rewrite a
  migration already applied to a shared database.
- Preserve RLS and public read-only access unless a reviewed security design
  explicitly replaces them.
