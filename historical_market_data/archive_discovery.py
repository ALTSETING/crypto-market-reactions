from __future__ import annotations

import calendar
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Iterable

from historical_market_data.binance_archive_client import BinanceArchiveClient
from historical_market_data.models import ManifestRecord


def month_range(start: date, end: date) -> list[tuple[int, int]]:
    cursor = date(start.year, start.month, 1)
    stop = date(end.year, end.month, 1)
    result = []
    while cursor <= stop:
        result.append((cursor.year, cursor.month))
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return result


def month_minutes(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1] * 1440


def discover_archives(symbols: Iterable[str], interval: str, start: date, end: date, client: BinanceArchiveClient | None = None, workers: int = 3) -> list[ManifestRecord]:
    client = client or BinanceArchiveClient()
    tasks = []
    for symbol in symbols:
        for year, month in month_range(start, end):
            tasks.append((symbol, year, month, client.monthly_url(symbol, interval, year, month)))
    records: list[ManifestRecord] = []
    with ThreadPoolExecutor(max_workers=min(3, workers)) as pool:
        futures = {pool.submit(client.exists, url): (symbol, year, month, url) for symbol, year, month, url in tasks}
        for future in as_completed(futures):
            symbol, year, month, url = futures[future]
            try:
                available = future.result()
                records.append(ManifestRecord(symbol, interval, year, month, url, status="discovered" if available else "unavailable", error_message=None if available else "HTTP 404"))
            except Exception as exc:
                records.append(ManifestRecord(symbol, interval, year, month, url, status="failed", error_message=str(exc)))
    return sorted(records, key=lambda item: (item.symbol, item.year, item.month))

