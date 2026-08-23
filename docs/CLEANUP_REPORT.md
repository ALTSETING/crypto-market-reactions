# Cleanup report

Cleanup date: 2026-08-22.

## Removed

- Source files in `trading/`: three zero-byte trading modules and an `__init__` marker. No repository imports referenced this package and it contained no execution logic or data.
- `scripts/analyze_news.py`, `scripts/train_model.py`: zero-byte placeholders.
- `reports/stage8_finalizer.pid`: stale process ID file.

The environment blocked recursive filesystem deletion, so `.venv/`, `.pytest_cache/`, `__pycache__/` and `reports/pytest_*` were left in place. They are reproducible artifacts and remain cleanup candidates; none is treated as product data.

## Explicitly retained

- Every CSV, JSON, JSONL, Parquet, ZIP, model artifact and substantive report.
- `.scrapy/httpcache/` because cached pages may be the only raw recovery source for some articles.
- `logs/` as provenance, despite being normally disposable.
- Crawler, normalization, database, candle import and reaction calculation code.
- Legacy ML/research code that participates in dataset construction, canonicalization, price-path generation or reproducibility.

No historical dataset row was deleted or rewritten.

## Version-control note

No pre-cleanup commit could be created: the workspace-level `.git` directory was empty and Git reported that the folder was not a repository. The existing project was not silently reinitialized, because doing so would not provide a true pre-cleanup history.
