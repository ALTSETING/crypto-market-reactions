"""Read-only event-level early reaction timing audit helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
)

from ml.stage11_dataset_builder import CandleGrid

RETURN_HORIZONS = (1, 2, 3, 5, 10, 15)
EXCURSION_HORIZONS = (1, 3, 5, 10, 15)
REACTION_HORIZONS = (1, 3, 5, 15)
THRESHOLDS = (0.10, 0.25, 0.50, 1.00)
CORE_CATEGORIES = {
    "regulation", "etf", "hack", "exchange", "protocol_upgrade",
    "market_commentary", "macro",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_stage12(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    manifest_path = root / "data" / "stage12" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes: dict[str, str] = {}
    for relative, expected in manifest["file_hashes_sha256"].items():
        actual = sha256(root / relative)
        if actual != expected:
            raise RuntimeError(f"Stage 12 hash mismatch: {relative}")
        hashes[relative] = actual
    if manifest["dataset_version"] != "stage12_eth_v1" or manifest["event_count"] != 6851:
        raise RuntimeError("Unexpected Stage 12 manifest identity")
    return manifest, hashes


def _ret(current: float, previous: float) -> float:
    return float((current / previous - 1.0) * 100.0)


def _window(grid: CandleGrid, baseline: int, start: int, end: int) -> tuple[int, int] | None:
    return grid.exact_window(baseline + start, baseline + end)


def _symbol_returns(prefix: str, grid: CandleGrid, baseline: int) -> dict[str, float] | None:
    span = _window(grid, baseline, -15, 15)
    base_index = grid.index(baseline)
    if span is None or base_index is None:
        return None
    base = float(grid.open[base_index])
    values: dict[str, float] = {}
    for horizon in RETURN_HORIZONS:
        before = grid.index(baseline - horizon)
        after = grid.index(baseline + horizon)
        assert before is not None and after is not None
        values[f"{prefix}_return_{horizon}m"] = _ret(float(grid.open[after]), base)
        values[f"pre_{prefix}_return_{horizon}m"] = _ret(base, float(grid.open[before]))
    return values


def _excursions(prefix: str, grid: CandleGrid, baseline: int) -> dict[str, float] | None:
    base_index = grid.index(baseline)
    history = _window(grid, baseline, -60, -1)
    if base_index is None or history is None or _window(grid, baseline, 0, 14) is None:
        return None
    base = float(grid.open[base_index])
    history_volume = grid.volume[history[0]:history[1] + 1]
    expected_per_minute = float(np.mean(history_volume))
    result: dict[str, float] = {}
    for horizon in EXCURSION_HORIZONS:
        end = base_index + horizon
        highs = grid.high[base_index:end]
        lows = grid.low[base_index:end]
        volumes = grid.volume[base_index:end]
        favorable = (highs / base - 1.0) * 100.0
        adverse = (lows / base - 1.0) * 100.0
        high_index, low_index = int(np.argmax(favorable)), int(np.argmin(adverse))
        max_favorable, max_adverse = float(favorable[high_index]), float(adverse[low_index])
        if abs(max_favorable) >= abs(max_adverse):
            time_to_max = high_index + 1
        else:
            time_to_max = low_index + 1
        result.update({
            f"{prefix}_max_favorable_excursion_{horizon}m": max_favorable,
            f"{prefix}_max_adverse_excursion_{horizon}m": max_adverse,
            f"{prefix}_max_absolute_excursion_{horizon}m": max(abs(max_favorable), abs(max_adverse)),
            f"{prefix}_high_low_range_{horizon}m": float((np.max(highs) - np.min(lows)) / base * 100.0),
            f"{prefix}_volume_shock_{horizon}m": float(np.sum(volumes) / (expected_per_minute * horizon)) if expected_per_minute else np.nan,
            f"{prefix}_time_to_max_move_{horizon}m": int(time_to_max),
        })
    return result


def build_early_record(row: Any, eth: CandleGrid, btc: CandleGrid) -> tuple[dict[str, Any] | None, str | None]:
    baseline = int(pd.Timestamp(row.baseline_time).timestamp() // 60)
    eth_returns = _symbol_returns("eth", eth, baseline)
    btc_returns = _symbol_returns("btc", btc, baseline)
    eth_excursions = _excursions("eth", eth, baseline)
    btc_excursions = _excursions("btc", btc, baseline)
    if eth_returns is None or btc_returns is None:
        return None, "missing_exact_return_window"
    if eth_excursions is None or btc_excursions is None:
        return None, "missing_exact_excursion_or_volume_history"
    beta = float(row.pre_eth_btc_rolling_beta)
    record: dict[str, Any] = {
        "dataset_version": "stage13a_eth_v1",
        "stage12_dataset_version": row.dataset_version,
        "event_key": row.event_key,
        "event_group_id": row.event_group_id,
        "news_id": int(row.news_id),
        "source": str(row.source),
        "published_at": pd.Timestamp(row.published_at),
        "baseline_time": pd.Timestamp(row.baseline_time),
        "split": str(row.split),
        "year": int(pd.Timestamp(row.published_at).year),
        "article_count_in_event": int(row.article_count_in_event),
        "second_article_delay_minutes": row.second_article_delay_minutes,
        "ai_direction": row.ai_direction,
        "ai_sentiment": float(row.ai_sentiment),
        "ai_category": row.ai_category,
        "category_group": row.category_group,
        "rolling_beta_pre_news": beta,
        "beta_fallback_used": int(row.pre_beta_fallback_used),
    }
    record.update(eth_returns)
    record.update(btc_returns)
    record.update(eth_excursions)
    record.update(btc_excursions)
    for horizon in RETURN_HORIZONS:
        eth_post, btc_post = record[f"eth_return_{horizon}m"], record[f"btc_return_{horizon}m"]
        eth_pre, btc_pre = record[f"pre_eth_return_{horizon}m"], record[f"pre_btc_return_{horizon}m"]
        record[f"eth_minus_btc_return_{horizon}m"] = eth_post - btc_post
        record[f"beta_adjusted_abnormal_return_{horizon}m"] = eth_post - beta * btc_post
        record[f"pre_eth_minus_btc_return_{horizon}m"] = eth_pre - btc_pre
        record[f"pre_beta_adjusted_abnormal_return_{horizon}m"] = eth_pre - beta * btc_pre
    for horizon in REACTION_HORIZONS:
        record[f"abs_pre_move_{horizon}m"] = abs(record[f"pre_eth_return_{horizon}m"])
        record[f"abs_post_move_{horizon}m"] = abs(record[f"eth_return_{horizon}m"])
    for threshold in THRESHOLDS:
        suffix = f"{int(threshold * 100):03d}"
        pre = record["abs_pre_move_5m"] >= threshold
        post = record["abs_post_move_5m"] >= threshold
        record[f"reaction_class_{suffix}"] = "both" if pre and post else "pre_reacted" if pre else "post_reacted" if post else "no_reaction"
        opposite = np.sign(record["pre_eth_return_5m"]) != np.sign(record["eth_return_5m"])
        weak_or_opposite = record["abs_post_move_5m"] < threshold or opposite
        record[f"late_publication_{suffix}"] = int(record["abs_pre_move_5m"] > record["abs_post_move_5m"] and pre and weak_or_opposite)
    return record, None


def direction_metrics(frame: pd.DataFrame, return_column: str, threshold: float = 0.10) -> dict[str, float | int]:
    predictions = frame.ai_direction.replace({"bullish": 1, "bearish": -1, "neutral": 0, "mixed": 0})
    actual = pd.Series(np.where(frame[return_column] > threshold, 1, np.where(frame[return_column] < -threshold, -1, 0)), index=frame.index)
    valid = predictions.notna() & frame[return_column].notna()
    predictions, actual = predictions[valid].astype(int), actual[valid].astype(int)
    sentiment = frame.loc[valid, "ai_sentiment"]
    bullish = predictions.eq(1)
    bearish = predictions.eq(-1)
    return {
        "count": int(valid.sum()),
        "accuracy": float(accuracy_score(actual, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(actual, predictions)),
        "mcc": float(matthews_corrcoef(actual, predictions)),
        "precision_macro": float(precision_score(actual, predictions, labels=[-1, 0, 1], average="macro", zero_division=0)),
        "recall_macro": float(recall_score(actual, predictions, labels=[-1, 0, 1], average="macro", zero_division=0)),
        "sentiment_spearman": float(sentiment.corr(frame.loc[valid, return_column], method="spearman")),
        "bullish_win_rate": float((frame.loc[valid].loc[bullish, return_column] > 0).mean()) if bullish.any() else np.nan,
        "bearish_win_rate": float((frame.loc[valid].loc[bearish, return_column] < 0).mean()) if bearish.any() else np.nan,
    }


def grouped_timing(frame: pd.DataFrame, dimensions: Iterable[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for dimension in dimensions:
        groups = [("all", frame)] if dimension == "overall" else frame.groupby(dimension, dropna=False)
        for value, group in groups:
            base = {
                "group_dimension": dimension,
                "group_value": str(value),
                "event_count": len(group),
                "median_abs_pre_move_1m": float(group.abs_pre_move_1m.median()),
                "median_abs_pre_move_3m": float(group.abs_pre_move_3m.median()),
                "median_abs_pre_move_5m": float(group.abs_pre_move_5m.median()),
                "median_abs_pre_move_15m": float(group.abs_pre_move_15m.median()),
                "median_abs_post_move_1m": float(group.abs_post_move_1m.median()),
                "median_abs_post_move_3m": float(group.abs_post_move_3m.median()),
                "median_abs_post_move_5m": float(group.abs_post_move_5m.median()),
                "median_abs_post_move_15m": float(group.abs_post_move_15m.median()),
            }
            for threshold in THRESHOLDS:
                suffix = f"{int(threshold * 100):03d}"
                base[f"late_publication_rate_{suffix}"] = float(group[f"late_publication_{suffix}"].mean())
                counts = group[f"reaction_class_{suffix}"].value_counts(normalize=True)
                for reaction in ("pre_reacted", "post_reacted", "both", "no_reaction"):
                    base[f"{reaction}_rate_{suffix}"] = float(counts.get(reaction, 0.0))
            rows.append(base)
    return pd.DataFrame(rows)


def earliest_horizon(group: pd.DataFrame, threshold: float = 0.10) -> str:
    for horizon in RETURN_HORIZONS:
        if float(group[f"beta_adjusted_abnormal_return_{horizon}m"].abs().median()) >= threshold:
            return f"{horizon}m"
    return "none_up_to_15m"
