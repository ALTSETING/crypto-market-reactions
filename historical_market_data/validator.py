from __future__ import annotations

from historical_market_data.models import Candle


def validate_candle(candle: Candle, expected_symbol: str, expected_interval: str = "1m") -> list[str]:
    errors: list[str] = []
    if candle.symbol != expected_symbol: errors.append("symbol_mismatch")
    if candle.interval != expected_interval: errors.append("interval_mismatch")
    for name in ("open", "high", "low", "close"):
        if getattr(candle, name) <= 0: errors.append(f"{name}_not_positive")
    if candle.high < candle.open: errors.append("high_below_open")
    if candle.high < candle.close: errors.append("high_below_close")
    if candle.low > candle.open: errors.append("low_above_open")
    if candle.low > candle.close: errors.append("low_above_close")
    if candle.high < candle.low: errors.append("high_below_low")
    for name in ("volume", "quote_volume", "taker_buy_base_volume", "taker_buy_quote_volume"):
        if getattr(candle, name) < 0: errors.append(f"{name}_negative")
    if candle.trade_count < 0: errors.append("trade_count_negative")
    if candle.open_time.second or candle.open_time.microsecond: errors.append("open_time_not_minute_aligned")
    if candle.close_time <= candle.open_time: errors.append("close_time_not_after_open")
    duration_ms = (candle.close_time - candle.open_time).total_seconds() * 1000
    if not 59_999 <= duration_ms < 60_000: errors.append("close_time_not_1m")
    return errors

