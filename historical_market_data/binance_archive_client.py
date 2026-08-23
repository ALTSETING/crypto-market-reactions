from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from historical_market_data.checksum import parse_checksum, verify_checksum


BASE_URL = "https://data.binance.vision/data/spot"


class BinanceArchiveClient:
    def __init__(self, timeout: tuple[int, int] = (10, 120), retries: int = 3, session: requests.Session | None = None):
        self.timeout, self.retries = timeout, retries
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "eth-news-stage16c/1.0"})

    @staticmethod
    def monthly_url(symbol: str, interval: str, year: int, month: int) -> str:
        name = f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
        return f"{BASE_URL}/monthly/klines/{symbol}/{interval}/{name}"

    @staticmethod
    def daily_url(symbol: str, interval: str, day: datetime) -> str:
        name = f"{symbol}-{interval}-{day:%Y-%m-%d}.zip"
        return f"{BASE_URL}/daily/klines/{symbol}/{interval}/{name}"

    def _request(self, method: str, url: str, *, stream: bool = False) -> requests.Response | None:
        for attempt in range(self.retries):
            try:
                response = self.session.request(method, url, timeout=self.timeout, stream=stream)
                if response.status_code == 404:
                    response.close(); return None
                if response.status_code == 429 or response.status_code >= 500:
                    wait = float(response.headers.get("Retry-After", 2 ** attempt)); response.close(); time.sleep(min(wait, 30)); continue
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt + 1 == self.retries: raise
                time.sleep(2 ** attempt)
        return None

    def exists(self, url: str) -> bool:
        response = self._request("HEAD", url)
        if response is None: return False
        response.close(); return True

    def download_verified(self, url: str, destination: Path) -> dict:
        checksum_response = self._request("GET", url + ".CHECKSUM")
        if checksum_response is None: raise FileNotFoundError(url + ".CHECKSUM")
        expected = parse_checksum(checksum_response.text); checksum_response.close()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            valid, actual = verify_checksum(destination, expected)
            if valid:
                return {"expected": expected, "actual": actual, "size": destination.stat().st_size, "downloaded": False}
            destination.unlink()
        for attempt in range(self.retries):
            temp = destination.with_suffix(destination.suffix + ".part")
            response = self._request("GET", url, stream=True)
            if response is None: raise FileNotFoundError(url)
            with temp.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk: handle.write(chunk)
            response.close()
            valid, actual = verify_checksum(temp, expected)
            if valid:
                temp.replace(destination)
                return {"expected": expected, "actual": actual, "size": destination.stat().st_size, "downloaded": True, "downloaded_at_utc": datetime.now(timezone.utc).isoformat()}
            temp.unlink(missing_ok=True)
            if attempt + 1 < self.retries: time.sleep(2 ** attempt)
        raise ValueError(f"checksum mismatch after {self.retries} downloads: {url}")

