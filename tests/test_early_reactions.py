import numpy as np
import pandas as pd

from market_intelligence.timing.early_reaction_calculator import calculate_latency_record
from market_intelligence.timing.publication_delay_analyzer import is_late, reaction_class
from ml.stage11_dataset_builder import CandleGrid


def _grid(symbol, slope):
    minutes = np.arange(900, 1201, dtype=np.int64)
    price = 100 + slope * np.arange(len(minutes))
    return CandleGrid(symbol, minutes, price, price * 1.001, price * .999, np.full(len(minutes), 10.0))


def test_early_returns_and_beta_adjustment():
    row = calculate_latency_record(1, pd.Timestamp(1000 * 60, unit="s", tz="UTC"), 1.0, _grid("ETH", .2), _grid("BTC", .1), 0)
    assert row is not None and np.isclose(row["abnormal_return_5m"], row["return_5m"] - ((100 + .1 * 105) / (100 + .1 * 100) - 1) * 100)


def test_latency_moves_the_baseline():
    eth, btc = _grid("ETH", .2), _grid("BTC", .1)
    zero = calculate_latency_record(1, pd.Timestamp(1000 * 60, unit="s", tz="UTC"), 1, eth, btc, 0)
    delayed = calculate_latency_record(1, pd.Timestamp(1000 * 60, unit="s", tz="UTC"), 1, eth, btc, 3)
    assert zero["baseline_time"] == delayed["baseline_time"] and zero["return_5m"] != delayed["return_5m"]


def test_publication_delay_classes():
    assert reaction_class(.2, .05, .1) == "reacted_before_article"
    assert reaction_class(.2, .3, .1) == "reacted_both"
    assert is_late(.2, .05, .1) is True
