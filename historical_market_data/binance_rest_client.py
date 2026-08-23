from __future__ import annotations

import time
from datetime import datetime

import requests


REST_URL = "https://data-api.binance.vision/api/v3/klines"


class BinanceRestClient:
    def __init__(self, session: requests.Session | None = None, retries: int = 3):
        self.session, self.retries = session or requests.Session(), retries

    def fetch(self, symbol: str, start: datetime, end: datetime, limit: int = 1000) -> list[list]:
        if not 1 <= limit <= 1000: raise ValueError("REST limit must be between 1 and 1000")
        params = {"symbol": symbol, "interval": "1m", "startTime": int(start.timestamp() * 1000), "endTime": int(end.timestamp() * 1000), "limit": limit}
        for attempt in range(self.retries):
            response = self.session.get(REST_URL, params=params, timeout=(10, 30))
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(min(float(response.headers.get("Retry-After", 2 ** attempt)), 30)); continue
            response.raise_for_status(); return response.json()
        raise RuntimeError("REST retries exhausted")

    def iter_range(self, symbol: str, start: datetime, end: datetime):
        cursor = start
        while cursor <= end:
            rows = self.fetch(symbol, cursor, end, 1000)
            if not rows: break
            yield rows
            next_ms = int(rows[-1][0]) + 60_000
            next_cursor = datetime.fromtimestamp(next_ms / 1000, tz=start.tzinfo)
            if next_cursor <= cursor: raise RuntimeError("REST pagination did not advance")
            cursor = next_cursor

