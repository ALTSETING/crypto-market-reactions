from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable


def detect_gaps(times: Iterable[datetime]) -> list[dict]:
    ordered = sorted(set(times))
    gaps = []
    for previous, current in zip(ordered, ordered[1:]):
        missing = int((current - previous).total_seconds() // 60) - 1
        if missing > 0:
            gaps.append({
                "gap_start": previous + timedelta(minutes=1), "gap_end": current - timedelta(minutes=1),
                "missing_minutes": missing, "previous_candle_at": previous, "next_candle_at": current,
            })
    return gaps


def classify_before_listing(timestamp: datetime, earliest: datetime) -> str:
    return "pre_listing" if timestamp < earliest else "market_available"

