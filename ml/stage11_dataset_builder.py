"""Leakage-safe Stage 11 event dataset and market-context builder."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

MODEL = "gpt-5-mini-2025-08-07"
PROMPT_VERSION = "eth_label_v1"
HORIZONS = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "24h": 1440}
BETA_WINDOWS = {"1d": 1440, "3d": 4320, "7d": 10080, "14d": 20160}
VOL_WINDOWS = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}
NEUTRAL_BANDS = {"010": .10, "025": .25, "050": .50, "100": 1.00}
STRONG_BANDS = {"025": .25, "050": .50, "100": 1.00, "200": 2.00}


@dataclass(frozen=True)
class CandleGrid:
    symbol: str
    minute: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray

    def index(self, minute: int) -> int | None:
        position = int(np.searchsorted(self.minute, minute))
        return position if position < len(self.minute) and int(self.minute[position]) == minute else None

    def exact_window(self, start_minute: int, end_minute: int) -> tuple[int, int] | None:
        start, end = self.index(start_minute), self.index(end_minute)
        if start is None or end is None or end < start:
            return None
        expected = end_minute - start_minute + 1
        if end - start + 1 != expected or int(self.minute[end]) - int(self.minute[start]) + 1 != expected:
            return None
        return start, end


def load_analysis_rows(session: Session) -> pd.DataFrame:
    query = text("""
        SELECT an.news_id,n.event_group_id,n.source,n.title,n.body,n.published_at,
               n.time_confidence,
               an.sentiment,an.importance,an.novelty,an.credibility,
               an.expected_direction AS direction,an.category,
               an.impact_duration AS ai_horizon,an.confidence,
               an.asset_relevance AS eth_relevance,
               r.baseline_time,r.return_5m,r.return_15m,r.return_30m,
               r.return_1h,r.return_4h,r.return_24h
        FROM news_analysis an
        JOIN news_articles n ON n.id=an.news_id
        JOIN news_assets ea ON ea.news_id=n.id AND (ea.asset='ETH' OR ea.symbol='ETHUSDT')
        LEFT JOIN news_market_reactions r ON r.news_id=n.id AND r.symbol='ETHUSDT'
        WHERE an.asset_focus='ETH' AND an.model_name=:model
          AND an.prompt_version=:prompt AND an.status='success'
        ORDER BY n.published_at,n.id
    """)
    frame = pd.read_sql(query, session.connection(), params={"model": MODEL, "prompt": PROMPT_VERSION})
    frame["published_at"] = pd.to_datetime(frame.published_at, utc=True)
    frame["baseline_time"] = pd.to_datetime(frame.baseline_time, utc=True)
    for column in ["time_confidence", "sentiment", "importance", "novelty", "credibility", "confidence", "eth_relevance", *[f"return_{key}" for key in HORIZONS]]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def select_earliest_events(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = frame.copy()
    data["event_key"] = data.event_group_id.where(data.event_group_id.notna(), data.news_id.map(lambda value: f"news-{value}"))
    counts = data.groupby("event_key").size().rename("article_count_in_event")
    ordered = data.sort_values(
        ["event_key", "published_at", "time_confidence", "news_id"],
        ascending=[True, True, False, True], kind="mergesort",
    )
    selected = ordered.drop_duplicates("event_key", keep="first").copy()
    selected = selected.join(counts, on="event_key")
    selected["selected_reason"] = np.where(
        selected.event_group_id.isna(), "synthetic_news_id_key",
        np.where(selected.article_count_in_event == 1, "only_article", "earliest_then_time_confidence_then_news_id"),
    )
    selection = selected[["event_key", "event_group_id", "news_id", "source", "published_at", "time_confidence", "article_count_in_event", "selected_reason"]].sort_values(["published_at", "news_id"])
    return selected.sort_values(["published_at", "news_id"]).reset_index(drop=True), selection.reset_index(drop=True)


def load_candle_grid(session: Session, symbol: str) -> CandleGrid:
    query = text("""
        SELECT (extract(epoch FROM open_time)/60)::bigint AS minute,
               open::double precision AS open,high::double precision AS high,
               low::double precision AS low,volume::double precision AS volume
        FROM market_candles
        WHERE symbol=:symbol AND interval='1m'
        ORDER BY open_time
    """)
    frame = pd.read_sql(query, session.connection(), params={"symbol": symbol})
    return CandleGrid(symbol, frame.minute.to_numpy(np.int64), frame.open.to_numpy(float), frame.high.to_numpy(float), frame.low.to_numpy(float), frame.volume.to_numpy(float))


def _return(current: float, previous: float) -> float:
    return (current / previous - 1.0) * 100.0 if previous and np.isfinite(previous) else np.nan


def _log_returns(prices: np.ndarray, step: int = 1) -> np.ndarray:
    if len(prices) <= step:
        return np.array([], dtype=float)
    left, right = prices[:-step:step], prices[step::step]
    valid = np.isfinite(left) & np.isfinite(right) & (left > 0) & (right > 0)
    return np.log(right[valid] / left[valid])


def _beta(eth_prices: np.ndarray, btc_prices: np.ndarray, step: int = 5, minimum: int = 100) -> float | None:
    eth_returns, btc_returns = _log_returns(eth_prices, step), _log_returns(btc_prices, step)
    count = min(len(eth_returns), len(btc_returns))
    if count < minimum:
        return None
    eth_returns, btc_returns = eth_returns[-count:], btc_returns[-count:]
    variance = float(np.var(btc_returns, ddof=1))
    return float(np.cov(eth_returns, btc_returns, ddof=1)[0, 1] / variance) if variance > 1e-16 else None


def _correlation(eth_prices: np.ndarray, btc_prices: np.ndarray, step: int = 5) -> float | None:
    a, b = _log_returns(eth_prices, step), _log_returns(btc_prices, step)
    count = min(len(a), len(b))
    if count < 20 or np.std(a[-count:]) == 0 or np.std(b[-count:]) == 0:
        return None
    return float(np.corrcoef(a[-count:], b[-count:])[0, 1])


def _ema(values: np.ndarray, span: int) -> float:
    alpha = 2.0 / (span + 1.0)
    result = float(values[0])
    for value in values[1:]:
        result = alpha * float(value) + (1 - alpha) * result
    return result


def _symbol_pre_features(prefix: str, grid: CandleGrid, cutoff: int) -> dict[str, Any] | None:
    current_index = grid.index(cutoff)
    if current_index is None or current_index < 20160:
        return None
    current_price = grid.open[current_index]
    result: dict[str, Any] = {}
    for label, minutes in HORIZONS.items():
        past = grid.index(cutoff - minutes)
        result[f"pre_{prefix}_return_{label}"] = _return(current_price, grid.open[past]) if past is not None else np.nan
    for label, minutes in VOL_WINDOWS.items():
        prices = grid.open[current_index - minutes:current_index + 1]
        returns = _log_returns(prices) * 100
        result[f"pre_{prefix}_realized_vol_{label}"] = float(np.sqrt(np.sum(returns**2))) if len(returns) == minutes else np.nan
        result[f"pre_{prefix}_return_std_{label}"] = float(np.std(returns, ddof=1)) if len(returns) > 1 else np.nan
        result[f"pre_{prefix}_volume_{label}"] = float(np.sum(grid.volume[current_index - minutes:current_index]))
    completed_volume = grid.volume[current_index - 1]
    history = grid.volume[current_index - 61:current_index - 1]
    result[f"pre_{prefix}_volume_vs_avg60"] = float(completed_volume / np.mean(history)) if np.mean(history) else np.nan
    result[f"pre_{prefix}_volume_z60"] = float((completed_volume - np.mean(history)) / np.std(history, ddof=1)) if np.std(history, ddof=1) else 0.0
    for window in [20, 50, 200]:
        prices = grid.open[current_index - window + 1:current_index + 1]
        sma = float(np.mean(prices)); ema = _ema(prices, window)
        result[f"pre_{prefix}_price_vs_sma{window}"] = _return(current_price, sma)
        result[f"pre_{prefix}_price_vs_ema{window}"] = _return(current_price, ema)
    recent = grid.open[current_index - 19:current_index + 1]
    previous = grid.open[current_index - 39:current_index - 19]
    result[f"pre_{prefix}_sma20_slope"] = _return(float(np.mean(recent)), float(np.mean(previous))) / 20.0
    return result


def _future_targets(prefix: str, grid: CandleGrid, baseline: int) -> dict[str, Any] | None:
    baseline_index = grid.index(baseline)
    if baseline_index is None or grid.index(baseline + 1440) is None:
        return None
    baseline_price = grid.open[baseline_index]
    result: dict[str, Any] = {}
    for label, minutes in HORIZONS.items():
        future_index = grid.index(baseline + minutes)
        result[f"target_{prefix}_return_{label}"] = _return(grid.open[future_index], baseline_price) if future_index is not None else np.nan
    for label, minutes in VOL_WINDOWS.items():
        end = grid.index(baseline + minutes)
        prices = grid.open[baseline_index:end + 1]
        returns = _log_returns(prices) * 100
        highs = grid.high[baseline_index:end]; lows = grid.low[baseline_index:end]
        result[f"future_{prefix}_return_std_{label}"] = float(np.std(returns, ddof=1)) if len(returns) > 1 else np.nan
        result[f"future_{prefix}_realized_vol_{label}"] = float(np.sqrt(np.sum(returns**2)))
        result[f"future_{prefix}_high_low_range_{label}"] = float((np.max(highs) - np.min(lows)) / baseline_price * 100)
        result[f"future_{prefix}_atr_like_{label}"] = float(np.mean(highs - lows) / baseline_price * 100)
    return result


def build_event_record(row: Any, eth: CandleGrid, btc: CandleGrid) -> tuple[dict[str, Any] | None, str | None]:
    published = pd.Timestamp(row.published_at)
    cutoff = int(published.floor("min").timestamp() // 60)
    baseline = cutoff + 1
    if cutoff > int(min(eth.minute[-1], btc.minute[-1])):
        return None, "published_after_candle_coverage"
    if cutoff < int(max(eth.minute[0], btc.minute[0])):
        return None, "published_before_candle_coverage"
    if cutoff - 20160 < int(max(eth.minute[0], btc.minute[0])):
        return None, "insufficient_14d_pre_news_history"
    eth_pre, btc_pre = _symbol_pre_features("eth", eth, cutoff), _symbol_pre_features("btc", btc, cutoff)
    eth_future, btc_future = _future_targets("eth", eth, baseline), _future_targets("btc", btc, baseline)
    if eth_pre is None or btc_pre is None:
        return None, "insufficient_pre_news_candles_or_gap"
    if eth_future is None or btc_future is None:
        return None, "insufficient_future_candles_or_gap"
    cutoff_eth, cutoff_btc = eth.index(cutoff), btc.index(cutoff)
    assert cutoff_eth is not None and cutoff_btc is not None
    beta_values: dict[str, float | None] = {}
    for label, minutes in BETA_WINDOWS.items():
        beta_values[label] = _beta(
            eth.open[cutoff_eth - minutes:cutoff_eth + 1],
            btc.open[cutoff_btc - minutes:cutoff_btc + 1], minimum=max(20, minutes // 10),
        )
    beta = beta_values["7d"]
    fallback = beta is None or not np.isfinite(beta)
    beta = 1.0 if fallback else float(beta)
    record: dict[str, Any] = {
        "metadata_event_key": row.event_key, "metadata_event_group_id": row.event_group_id,
        "metadata_news_id": int(row.news_id), "metadata_source": row.source,
        "metadata_published_at": published, "metadata_time_confidence": float(row.time_confidence),
        "metadata_article_count_in_event": int(row.article_count_in_event),
        "metadata_feature_cutoff": pd.to_datetime(cutoff * 60, unit="s", utc=True),
        "metadata_target_baseline": pd.to_datetime(baseline * 60, unit="s", utc=True),
        "metadata_hour_utc": published.hour, "metadata_day_of_week": published.dayofweek,
        "metadata_weekend": int(published.dayofweek >= 5), "metadata_month": published.month,
        "metadata_us_session": int(13 <= published.hour < 22), "metadata_eu_session": int(7 <= published.hour < 16),
        "metadata_asia_session": int(0 <= published.hour < 9),
        "metadata_seconds_from_candle_boundary": int(published.second),
        "pre_beta_1d": beta_values["1d"], "pre_beta_3d": beta_values["3d"],
        "pre_beta_7d": beta_values["7d"], "pre_beta_14d": beta_values["14d"],
        "pre_beta_pre_news": beta, "metadata_beta_window": "7d_5m_returns",
        "metadata_beta_fallback_used": int(fallback),
        "ai9_sentiment": float(row.sentiment), "ai9_importance": float(row.importance),
        "ai9_novelty": float(row.novelty), "ai9_credibility": float(row.credibility),
        "ai9_confidence": float(row.confidence), "ai9_eth_relevance": float(row.eth_relevance),
        "ai9_direction": row.direction, "ai9_category": row.category,
        "ai9_horizon": row.ai_horizon,
    }
    record.update(eth_pre); record.update(btc_pre)
    for label in HORIZONS:
        record[f"pre_eth_btc_relative_return_{label}"] = record[f"pre_eth_return_{label}"] - record[f"pre_btc_return_{label}"]
    record["pre_eth_btc_correlation_7d"] = _correlation(
        eth.open[cutoff_eth - BETA_WINDOWS["7d"]:cutoff_eth + 1],
        btc.open[cutoff_btc - BETA_WINDOWS["7d"]:cutoff_btc + 1],
    )
    for label in HORIZONS:
        eth_return, btc_return = eth_future[f"target_eth_return_{label}"], btc_future[f"target_btc_return_{label}"]
        market_adjusted = eth_return - btc_return
        abnormal = eth_return - beta * btc_return
        record[f"target_eth_return_{label}"] = eth_return
        record[f"target_btc_return_{label}"] = btc_return
        record[f"target_market_adjusted_return_{label}"] = market_adjusted
        record[f"target_abnormal_return_{label}"] = abnormal
        record[f"target_abs_abnormal_return_{label}"] = abs(abnormal)
        for suffix, band in NEUTRAL_BANDS.items():
            record[f"target_abnormal_direction_{label}_band_{suffix}"] = "positive" if abnormal > band else "negative" if abnormal < -band else "neutral"
        for suffix, band in STRONG_BANDS.items():
            record[f"target_strong_abnormal_{label}_{suffix}"] = int(abs(abnormal) > band)
    for label in VOL_WINDOWS:
        for metric in ["return_std", "realized_vol", "high_low_range", "atr_like"]:
            record[f"target_future_{metric}_{label}"] = eth_future[f"future_eth_{metric}_{label}"]
        minutes = VOL_WINDOWS[label]
        base_index = eth.index(baseline); cutoff_index = eth.index(cutoff)
        assert base_index is not None and cutoff_index is not None
        future_volume = float(np.mean(eth.volume[base_index:base_index + minutes]))
        previous_volume = float(np.mean(eth.volume[cutoff_index - minutes:cutoff_index]))
        ratio = future_volume / previous_volume if previous_volume else np.nan
        record[f"target_volume_ratio_{label}"] = ratio
        record[f"target_log_volume_ratio_{label}"] = float(np.log(ratio)) if ratio > 0 else np.nan
    base_index = eth.index(baseline); end_index = eth.index(baseline + 1440)
    assert base_index is not None and end_index is not None
    highs, lows = eth.high[base_index:end_index], eth.low[base_index:end_index]
    favorable = (highs / eth.open[base_index] - 1) * 100
    adverse = (lows / eth.open[base_index] - 1) * 100
    absolute = np.maximum(np.abs(favorable), np.abs(adverse))
    record["target_max_favorable_excursion_24h"] = float(np.max(favorable))
    record["target_max_adverse_excursion_24h"] = float(np.min(adverse))
    record["target_max_absolute_excursion_24h"] = float(np.max(absolute))
    record["target_minutes_to_max_absolute_24h"] = int(np.argmax(absolute))
    return record, None


def chronological_splits(frame: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    order = frame.sort_values(["metadata_published_at", "metadata_news_id"]).index
    count = len(order); train_end = int(count * .60); validation_end = int(count * .80)
    labels = pd.Series(index=frame.index, dtype="object")
    labels.loc[order[:train_end]] = "train"; labels.loc[order[train_end:validation_end]] = "validation"; labels.loc[order[validation_end:]] = "test"
    def boundary(name: str) -> dict[str, Any]:
        values = frame.loc[labels == name, "metadata_published_at"]
        return {"count": len(values), "start": values.min().isoformat(), "end": values.max().isoformat()}
    folds=[]
    chunks=np.array_split(order,5)
    for fold in range(1,4):
        train_indices=np.concatenate(chunks[:fold+1]); test_indices=chunks[fold+1]
        folds.append({"fold":fold,"train_news_ids":frame.loc[train_indices,"metadata_news_id"].astype(int).tolist(),"test_news_ids":frame.loc[test_indices,"metadata_news_id"].astype(int).tolist(),
                      "train_end":frame.loc[train_indices,"metadata_published_at"].max().isoformat(),"test_start":frame.loc[test_indices,"metadata_published_at"].min().isoformat()})
    return labels, {"method":"chronological_60_20_20","train":boundary("train"),"validation":boundary("validation"),"test":boundary("test"),"walk_forward_folds":folds}


def finalize_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    data = frame.copy()
    split, _ = chronological_splits(data); train = data.loc[split == "train"]
    threshold = float(train.pre_eth_realized_vol_1h.median())
    data["pre_high_volatility_regime"] = (data.pre_eth_realized_vol_1h > threshold).astype(int)
    data["pre_market_regime"] = np.where(
        (data.pre_eth_price_vs_sma200 > 0) & (data.pre_eth_return_4h > .5), "bullish",
        np.where((data.pre_eth_price_vs_sma200 < 0) & (data.pre_eth_return_4h < -.5), "bearish", "range"),
    )
    categorical = ["metadata_source", "ai9_direction", "ai9_category", "ai9_horizon", "pre_market_regime"]
    data = pd.get_dummies(data, columns=categorical, prefix=categorical, dtype=int)
    feature_columns = sorted(column for column in data if column.startswith(("pre_", "ai9_", "metadata_")) and column not in {
        "metadata_event_key", "metadata_event_group_id", "metadata_news_id", "metadata_published_at", "metadata_feature_cutoff", "metadata_target_baseline", "metadata_beta_window",
    } and pd.api.types.is_numeric_dtype(data[column]))
    target_columns = sorted(column for column in data if column.startswith("target_"))
    if any(column.startswith(("target_", "future_")) for column in feature_columns):
        raise ValueError("Target leakage detected in Stage 11 feature list")
    return data, feature_columns, target_columns


def build_dataset_a(session: Session, reports_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    source = load_analysis_rows(session); selected, selection = select_earliest_events(source)
    selection.to_csv(reports_dir / "stage11_eth_event_selection.csv", index=False, encoding="utf-8-sig")
    eth, btc = load_candle_grid(session, "ETHUSDT"), load_candle_grid(session, "BTCUSDT")
    records=[]; missing=[]
    for row in selected.itertuples(index=False):
        record, reason = build_event_record(row, eth, btc)
        if record is None:
            missing.append({"news_id":int(row.news_id),"event_key":row.event_key,"published_at":row.published_at.isoformat(),"reason":reason})
        else:
            records.append(record)
    raw = pd.DataFrame(records).sort_values(["metadata_published_at", "metadata_news_id"]).reset_index(drop=True)
    dataset, features, targets = finalize_features(raw)
    split, splits = chronological_splits(dataset); dataset["metadata_split"] = split
    splits["missing_events"] = missing; splits["event_selection_count"] = len(selection); splits["dataset_count"] = len(dataset)
    dataset.to_parquet(reports_dir / "stage11_eth_dataset_a.parquet", index=False)
    dataset.head(200).to_csv(reports_dir / "stage11_eth_dataset_a_sample.csv", index=False, encoding="utf-8-sig")
    abnormal_columns = [column for column in dataset if column.startswith(("target_eth_return_", "target_btc_return_", "target_market_adjusted_return_", "target_abnormal_return_"))]
    dataset[["metadata_event_key", "metadata_news_id", "metadata_published_at", "pre_beta_pre_news", "metadata_beta_window", "metadata_beta_fallback_used", *abnormal_columns]].to_parquet(reports_dir / "stage11_eth_abnormal_returns.parquet", index=False)
    market_columns = [column for column in features if column.startswith(("pre_", "metadata_"))]
    dataset[["metadata_event_key", "metadata_news_id", "metadata_published_at", *market_columns]].to_parquet(reports_dir / "stage11_eth_market_features.parquet", index=False)
    schema={"rows":len(dataset),"event_selection_rows":len(selection),"features":features,"targets":targets,"metadata":[column for column in dataset if column.startswith("metadata_") and column not in features],"feature_rule":"only pre_*, ai9_*, and numeric metadata_*; no target/future columns","missing_events":missing}
    (reports_dir / "stage11_eth_dataset_schema.json").write_text(json.dumps(schema,indent=2,ensure_ascii=False),encoding="utf-8")
    pd.DataFrame([{"column":column,"group":"market" if column.startswith(("pre_","metadata_")) else "stage9_ai","dtype":str(dataset[column].dtype)} for column in features]).to_csv(reports_dir / "stage11_eth_feature_list.csv",index=False,encoding="utf-8-sig")
    (reports_dir / "stage11_eth_splits.json").write_text(json.dumps(splits,indent=2,ensure_ascii=False),encoding="utf-8")
    return dataset, {"source_rows":len(source),"event_rows":len(selection),"dataset_rows":len(dataset),"features":len(features),"targets":len(targets),"beta_fallbacks":int(dataset.metadata_beta_fallback_used.sum()),"missing_events":missing}
