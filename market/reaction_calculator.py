"""Pure market reaction calculations over one-minute candles."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

HORIZONS = {"return_5m": 5, "return_15m": 15, "return_30m": 30, "return_1h": 60, "return_4h": 240, "return_24h": 1440}

def baseline_time(published_at: datetime) -> datetime:
    """Return the next minute boundary, always at least one minute tick later."""
    if published_at.tzinfo is None: published_at = published_at.replace(tzinfo=timezone.utc)
    return published_at.replace(second=0, microsecond=0) + timedelta(minutes=1)

def return_percent(baseline: Decimal, future: Decimal) -> Decimal:
    if baseline == 0: raise ValueError("baseline price cannot be zero")
    return (future - baseline) / baseline * Decimal("100")

def calculate_reaction(published_at: datetime, candles: list[Any]) -> dict[str, Any] | None:
    """Calculate returns when an exact baseline candle is available."""
    target = baseline_time(published_at)
    by_time = {c.open_time: c for c in candles}
    baseline = by_time.get(target)
    if baseline is None: return None
    result: dict[str, Any] = {"baseline_time": target, "baseline_price": baseline.open}
    for field, minutes in HORIZONS.items():
        candle = by_time.get(target + timedelta(minutes=minutes))
        result[field] = return_percent(baseline.open, candle.open) if candle else None
    first_hour = [c for c in candles if target < c.open_time <= target + timedelta(hours=1)]
    result["max_return_1h"] = return_percent(baseline.open, max(c.high for c in first_hour)) if first_hour else None
    result["min_return_1h"] = return_percent(baseline.open, min(c.low for c in first_hour)) if first_hour else None
    if first_hour and baseline.volume:
        average_volume = sum((c.volume for c in first_hour), Decimal(0)) / len(first_hour)
        result["volume_change_1h"] = return_percent(baseline.volume, average_volume)
    else:
        result["volume_change_1h"] = None
    return result
