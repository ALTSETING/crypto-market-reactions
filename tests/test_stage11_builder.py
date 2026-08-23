from types import SimpleNamespace

import numpy as np
import pandas as pd

from ml.stage11_dataset_builder import CandleGrid, build_event_record, chronological_splits, select_earliest_events


def grid(symbol: str, change: float = .00001) -> CandleGrid:
    minute = np.arange(30000, dtype=np.int64)
    prices = 100 * np.exp(change * minute)
    return CandleGrid(symbol, minute, prices, prices * 1.001, prices * .999, np.full(30000, 10.0))


def event_row(minute: int = 22000):
    return SimpleNamespace(
        published_at=pd.Timestamp(minute * 60 + 30, unit="s", tz="UTC"),
        event_key="event-1", event_group_id="event-1", news_id=1, source="coindesk",
        time_confidence=.95, article_count_in_event=2, sentiment=10, importance=50,
        novelty=40, credibility=80, direction="bullish", category="etf",
        ai_horizon="hours", confidence=70, eth_relevance=90,
    )


def test_event_selection_uses_time_confidence_then_news_id_for_tie():
    time = pd.Timestamp("2024-01-01", tz="UTC")
    frame = pd.DataFrame([
        {"event_group_id":"g", "news_id":2, "published_at":time, "time_confidence":.8, "source":"a"},
        {"event_group_id":"g", "news_id":3, "published_at":time, "time_confidence":.9, "source":"b"},
        {"event_group_id":None, "news_id":4, "published_at":time, "time_confidence":.5, "source":"c"},
    ])
    selected, report = select_earliest_events(frame)
    assert selected.news_id.tolist() == [3, 4]
    assert report.loc[report.news_id == 4, "event_key"].iat[0] == "news-4"
    repeated, repeated_report = select_earliest_events(frame)
    pd.testing.assert_frame_equal(selected.reset_index(drop=True), repeated.reset_index(drop=True))
    pd.testing.assert_frame_equal(report.reset_index(drop=True), repeated_report.reset_index(drop=True))


def test_abnormal_return_and_beta_use_only_pre_news_prices():
    eth, btc = grid("ETH", .00002), grid("BTC", .00001)
    record, reason = build_event_record(event_row(), eth, btc)
    assert reason is None and record is not None
    expected = record["target_eth_return_1h"] - record["pre_beta_pre_news"] * record["target_btc_return_1h"]
    assert abs(record["target_abnormal_return_1h"] - expected) < 1e-12
    beta_before = record["pre_beta_pre_news"]
    changed = CandleGrid("ETH", eth.minute, eth.open.copy(), eth.high.copy(), eth.low.copy(), eth.volume.copy())
    cutoff = int(event_row().published_at.floor("min").timestamp() // 60)
    changed.open[cutoff + 1:] *= 3
    changed.high[cutoff + 1:] *= 3
    changed.low[cutoff + 1:] *= 3
    changed_record, _ = build_event_record(event_row(), changed, btc)
    assert changed_record["pre_beta_pre_news"] == beta_before
    assert changed_record["pre_eth_return_1h"] == record["pre_eth_return_1h"]


def test_btc_gap_is_documented():
    eth, btc = grid("ETH"), grid("BTC")
    missing = 22001 + 1440
    keep = btc.minute != missing
    btc_gap = CandleGrid("BTC", btc.minute[keep], btc.open[keep], btc.high[keep], btc.low[keep], btc.volume[keep])
    record, reason = build_event_record(event_row(), eth, btc_gap)
    assert record is None
    assert reason == "insufficient_future_candles_or_gap"


def test_chronological_split_and_walkforward_do_not_overlap():
    frame = pd.DataFrame({
        "metadata_news_id": range(10),
        "metadata_published_at": pd.date_range("2024-01-01", periods=10, tz="UTC"),
    })
    labels, report = chronological_splits(frame)
    assert labels.tolist() == ["train"] * 6 + ["validation"] * 2 + ["test"] * 2
    assert len(report["walk_forward_folds"]) == 3
    for fold in report["walk_forward_folds"]:
        assert not set(fold["train_news_ids"]) & set(fold["test_news_ids"])
