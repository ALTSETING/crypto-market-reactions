import pandas as pd
import pytest

from market_intelligence.datasets.feature_registry import assert_no_post_news_features
from market_intelligence.futures.futures_feature_builder import build_futures_features


def test_leakage_guard_rejects_post_news_fields():
    with pytest.raises(RuntimeError):
        assert_no_post_news_features(["pre_return_5m", "return_5m"])


def test_leakage_guard_accepts_pre_news_fields():
    assert_no_post_news_features(["pre_return_5m", "pre_funding_current", "pre_primary_source_found"])


def test_stale_oi_is_not_carried_forward():
    event = pd.DataFrame({"event_key": ["e"], "baseline_time": [pd.Timestamp("2024-01-01 01:00Z")]})
    oi = pd.DataFrame({"symbol": ["ETHUSDT"], "timestamp": [pd.Timestamp("2024-01-01 00:00Z")], "open_interest": [10], "open_interest_value": [20]})
    result = build_futures_features(event, pd.DataFrame(), oi, pd.DataFrame(), pd.DataFrame())
    assert pd.isna(result.iloc[0].pre_oi_current)
