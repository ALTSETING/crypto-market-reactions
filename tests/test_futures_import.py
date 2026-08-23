from datetime import datetime, timezone

import pandas as pd

from market_intelligence.futures.binance_futures_client import BinanceFuturesClient
from market_intelligence.futures.futures_feature_builder import build_futures_features
from market_intelligence.futures.importers import _dt, import_taker


def test_binance_timestamp_conversion_is_utc():
    value = _dt(1_700_000_000_000)
    assert value.tzinfo == timezone.utc and int(value.timestamp()) == 1_700_000_000


def test_binance_parameters_use_milliseconds(monkeypatch):
    client = BinanceFuturesClient()
    captured = {}
    monkeypatch.setattr(client, "get", lambda path, params: captured.update(path=path, params=params) or [])
    client.funding("ETHUSDT", datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 2, tzinfo=timezone.utc))
    assert captured["path"] == "/fapi/v1/fundingRate" and captured["params"]["endTime"] > captured["params"]["startTime"]


def test_futures_merge_never_uses_future_observation():
    events = pd.DataFrame({"event_key": ["a"], "baseline_time": [pd.Timestamp("2024-01-01 00:05", tz="UTC")]})
    funding = pd.DataFrame({"symbol": ["ETHUSDT", "ETHUSDT"], "funding_time": pd.to_datetime(["2024-01-01 00:00Z", "2024-01-01 00:10Z"]), "funding_rate": [.001, .999], "mark_price": [1, 2]})
    empty = pd.DataFrame()
    result = build_futures_features(events, funding, empty, empty, empty)
    assert result.iloc[0].pre_funding_current == .001


def test_resume_filters_binance_point_older_than_requested_cursor(monkeypatch):
    class Session:
        def scalar(self, _query):
            return datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    class Client:
        def taker(self, *args, **kwargs):
            return [{"timestamp": 1_704_067_200_000, "buySellRatio": "1"}]
    seen = []
    monkeypatch.setattr("market_intelligence.futures.importers._upsert", lambda _s, _t, rows, _k: seen.extend(rows) or 0)
    assert import_taker(Session(), Client(), "ETHUSDT", datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 1, 0, 10, tzinfo=timezone.utc), True) == 0
    assert seen == []
