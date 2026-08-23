from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Candle:
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int
    taker_buy_base_volume: Decimal
    taker_buy_quote_volume: Decimal
    source_type: str
    source_file: str
    source_sha256: str
    timestamp_precision: str


@dataclass
class ManifestRecord:
    symbol: str
    interval: str
    year: int
    month: int
    source_url: str
    local_path: str = ""
    downloaded_at_utc: str | None = None
    expected_checksum: str | None = None
    actual_checksum: str | None = None
    file_size: int | None = None
    row_count: int | None = None
    first_open_time: str | None = None
    last_open_time: str | None = None
    timestamp_precision: str | None = None
    status: str = "discovered"
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

