from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from market.reaction_calculator import baseline_time, calculate_reaction, return_percent

UTC = timezone.utc
def candle(at, open_price, high=None, low=None, volume="10"):
    price = Decimal(str(open_price))
    return SimpleNamespace(open_time=at, open=price, high=Decimal(str(high or open_price)), low=Decimal(str(low or open_price)), volume=Decimal(volume))

def test_baseline_is_next_minute_even_on_boundary():
    assert baseline_time(datetime(2024, 1, 1, 14, 35, 12, tzinfo=UTC)).minute == 36
    assert baseline_time(datetime(2024, 1, 1, 14, 35, 0, tzinfo=UTC)).minute == 36

def test_formula():
    assert return_percent(Decimal("100"), Decimal("105")) == Decimal("5")

def test_5m_and_1h_returns():
    published = datetime(2024, 1, 1, 14, 35, 12, tzinfo=UTC); base = baseline_time(published)
    rows = [candle(base, 100), candle(base + timedelta(minutes=5), 105), candle(base + timedelta(hours=1), 90)]
    result = calculate_reaction(published, rows)
    assert result and result["return_5m"] == Decimal("5") and result["return_1h"] == Decimal("-10")

def test_missing_baseline_or_future_candle():
    published = datetime(2024, 1, 1, 14, 35, 12, tzinfo=UTC); base = baseline_time(published)
    assert calculate_reaction(published, []) is None
    result = calculate_reaction(published, [candle(base, 100)])
    assert result and result["return_5m"] is None
