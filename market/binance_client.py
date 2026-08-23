"""Resilient Binance REST client for historical klines."""
from collections.abc import Iterator
from datetime import datetime, timezone
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.config import settings

def _milliseconds(value: datetime) -> int:
    if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)

class BinanceClient:
    def __init__(self, base_url: str = settings.binance_base_url, timeout: int = 30):
        self.base_url = base_url.rstrip("/"); self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(total=5, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def iter_klines(self, symbol: str, interval: str, start_date: datetime, end_date: datetime) -> Iterator[list[list]]:
        """Yield chronologically ordered batches of at most 1000 raw klines."""
        cursor, end_ms = _milliseconds(start_date), _milliseconds(end_date)
        while cursor < end_ms:
            response = self.session.get(f"{self.base_url}/api/v3/klines", params={"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": end_ms - 1, "limit": 1000}, timeout=self.timeout)
            response.raise_for_status()
            batch = response.json()
            if not batch: break
            yield batch
            next_cursor = int(batch[-1][0]) + 1
            if next_cursor <= cursor: break
            cursor = next_cursor
            time.sleep(0.1)
