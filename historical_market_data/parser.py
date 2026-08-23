from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import TextIOWrapper
from pathlib import Path
from typing import Iterator
from zipfile import BadZipFile, ZipFile

from historical_market_data.models import Candle


MIN_TS = datetime(2017, 1, 1, tzinfo=timezone.utc)
MAX_TS = datetime(2030, 1, 1, tzinfo=timezone.utc)


def normalize_timestamp(raw: str | int) -> tuple[datetime, str]:
    value = int(raw)
    precision = "microseconds" if abs(value) >= 100_000_000_000_000 else "milliseconds"
    divisor = 1_000_000 if precision == "microseconds" else 1_000
    result = datetime.fromtimestamp(value / divisor, tz=timezone.utc)
    if not MIN_TS <= result < MAX_TS:
        raise ValueError(f"timestamp outside allowed calendar range: {value}")
    return result, precision


def parse_row(row: list[str], symbol: str, interval: str, source_type: str, source_file: str, source_sha256: str) -> Candle:
    if len(row) < 12:
        raise ValueError(f"expected 12 columns, got {len(row)}")
    try:
        opened, precision = normalize_timestamp(row[0])
        closed, close_precision = normalize_timestamp(row[6])
        if close_precision != precision:
            raise ValueError("open/close timestamp precision mismatch")
        return Candle(
            symbol=symbol, interval=interval, open_time=opened, close_time=closed,
            open=Decimal(row[1]), high=Decimal(row[2]), low=Decimal(row[3]), close=Decimal(row[4]),
            volume=Decimal(row[5]), quote_volume=Decimal(row[7]), trade_count=int(row[8]),
            taker_buy_base_volume=Decimal(row[9]), taker_buy_quote_volume=Decimal(row[10]),
            source_type=source_type, source_file=source_file, source_sha256=source_sha256,
            timestamp_precision=precision,
        )
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ValueError(str(exc)) from exc


def iter_zip_rows(path: Path, symbol: str, interval: str, source_type: str, source_sha256: str) -> Iterator[tuple[int, list[str], Candle | None, str | None]]:
    try:
        archive = ZipFile(path)
    except BadZipFile as exc:
        raise ValueError(f"corrupted ZIP: {path.name}") from exc
    with archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV member, got {len(names)}")
        with archive.open(names[0]) as binary, TextIOWrapper(binary, encoding="utf-8", newline="") as text:
            for number, row in enumerate(csv.reader(text), 1):
                if number == 1 and row and not row[0].strip().lstrip("-").isdigit():
                    continue
                try:
                    yield number, row, parse_row(row, symbol, interval, source_type, path.name, source_sha256), None
                except ValueError as exc:
                    yield number, row, None, str(exc)


def raw_row_hash(row: list[str]) -> str:
    return sha256(",".join(row).encode("utf-8")).hexdigest()

