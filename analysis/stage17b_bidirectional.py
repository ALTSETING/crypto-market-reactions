"""Pure Stage 17B helpers for bidirectional LONG/SHORT discovery.

The helpers deliberately know nothing about the opened Stage 17 locked test.  A
caller supplies feature rows and returns from an allowed discovery split only.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score


SIGNALS = ("LONG", "SHORT")


def directional_target(returns: pd.Series, neutral_threshold: float) -> pd.Series:
    """Map percentage returns to UP/DOWN/NEUTRAL without treating neutral as correct."""
    values = pd.to_numeric(returns, errors="coerce")
    return pd.Series(
        np.select(
            [values > neutral_threshold, values < -neutral_threshold],
            ["UP", "DOWN"],
            default="NEUTRAL",
        ),
        index=returns.index,
        dtype="object",
    )


def signal_from_probabilities(
    probabilities: np.ndarray,
    classes: list[str],
    confidence_threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Produce LONG/SHORT/NO_SIGNAL using only learned UP/DOWN probabilities."""
    class_index = {name: position for position, name in enumerate(classes)}
    up = probabilities[:, class_index["UP"]] if "UP" in class_index else np.zeros(len(probabilities))
    down = probabilities[:, class_index["DOWN"]] if "DOWN" in class_index else np.zeros(len(probabilities))
    confidence = np.maximum(up, down)
    signal = np.where(up >= down, "LONG", "SHORT").astype(object)
    signal[confidence < confidence_threshold] = "NO_SIGNAL"
    return signal, confidence


def wilson_interval(correct: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    rate = correct / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return center - margin, center + margin


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def signal_metrics(rows: pd.DataFrame) -> dict[str, Any]:
    """Return explicit LONG, SHORT and combined metrics.

    Required columns are ``signal``, ``actual_direction``, ``future_return`` and
    ``event_id``.  A neutral target is always incorrect for LONG/SHORT.
    """
    total = len(rows)
    signals = rows[rows.signal.isin(SIGNALS)].copy()
    long_rows = signals[signals.signal.eq("LONG")]
    short_rows = signals[signals.signal.eq("SHORT")]
    long_correct = int(long_rows.actual_direction.eq("UP").sum())
    short_correct = int(short_rows.actual_direction.eq("DOWN").sum())
    correct = long_correct + short_correct
    signal_count = len(signals)
    predicted_direction = signals.signal.map({"LONG": "UP", "SHORT": "DOWN"})
    balanced = None
    if signal_count and signals.actual_direction.nunique() > 1:
        balanced = float(balanced_accuracy_score(signals.actual_direction, predicted_direction))
    low, high = wilson_interval(correct, signal_count)
    long_low, long_high = wilson_interval(long_correct, len(long_rows))
    short_low, short_high = wilson_interval(short_correct, len(short_rows))
    sign = signals.signal.map({"LONG": 1.0, "SHORT": -1.0})
    gross = sign * pd.to_numeric(signals.future_return, errors="coerce")
    long_gross = pd.to_numeric(long_rows.future_return, errors="coerce")
    short_gross = -pd.to_numeric(short_rows.future_return, errors="coerce")
    months = pd.to_datetime(signals.published_at, utc=True, errors="coerce").dt.strftime("%Y-%m")
    long_months = pd.to_datetime(long_rows.published_at, utc=True, errors="coerce").dt.strftime("%Y-%m")
    short_months = pd.to_datetime(short_rows.published_at, utc=True, errors="coerce").dt.strftime("%Y-%m")
    source_share = float(signals.source.value_counts(normalize=True, dropna=False).max()) if signal_count else None
    month_share = float(months.value_counts(normalize=True, dropna=False).max()) if signal_count else None
    return {
        "total_rows": total,
        "long_signals": len(long_rows),
        "long_correct": long_correct,
        "long_incorrect": len(long_rows) - long_correct,
        "long_accuracy": _safe_rate(long_correct, len(long_rows)),
        "long_wilson_low": long_low,
        "long_wilson_high": long_high,
        "long_gross_expectancy_percent": float(long_gross.mean()) if len(long_rows) else None,
        "long_source_max_share": float(long_rows.source.value_counts(normalize=True, dropna=False).max()) if len(long_rows) else None,
        "long_month_max_share": float(long_months.value_counts(normalize=True, dropna=False).max()) if len(long_rows) else None,
        "short_signals": len(short_rows),
        "short_correct": short_correct,
        "short_incorrect": len(short_rows) - short_correct,
        "short_accuracy": _safe_rate(short_correct, len(short_rows)),
        "short_wilson_low": short_low,
        "short_wilson_high": short_high,
        "short_gross_expectancy_percent": float(short_gross.mean()) if len(short_rows) else None,
        "short_source_max_share": float(short_rows.source.value_counts(normalize=True, dropna=False).max()) if len(short_rows) else None,
        "short_month_max_share": float(short_months.value_counts(normalize=True, dropna=False).max()) if len(short_rows) else None,
        "combined_signals": signal_count,
        "combined_correct": correct,
        "combined_incorrect": signal_count - correct,
        "combined_accuracy": _safe_rate(correct, signal_count),
        "balanced_accuracy": balanced,
        "coverage": _safe_rate(signal_count, total),
        "no_signal_count": total - signal_count,
        "dominant_direction_share": _safe_rate(max(len(long_rows), len(short_rows)), signal_count),
        "wilson_95_ci_low": low,
        "wilson_95_ci_high": high,
        "gross_expectancy_percent": float(gross.mean()) if signal_count else None,
        "source_max_share": source_share,
        "month_max_share": month_share,
    }


def baseline_metrics(rows: pd.DataFrame) -> dict[str, float | None]:
    """Evaluate simple directional baselines on exactly the candidate signal rows."""
    signals = rows[rows.signal.isin(SIGNALS)].copy()
    if signals.empty:
        return {
            "always_long": None,
            "always_short": None,
            "majority_direction": None,
            "previous_1m": None,
            "previous_5m": None,
            "btc_trend": None,
            "strongest_baseline": None,
        }
    actual = signals.actual_direction.to_numpy()

    def accuracy(prediction: np.ndarray) -> float:
        return float(np.mean(prediction == actual))

    up_count = int(np.sum(actual == "UP"))
    down_count = int(np.sum(actual == "DOWN"))
    majority = "UP" if up_count >= down_count else "DOWN"
    previous_1m = np.where(pd.to_numeric(signals.pre_return_1m, errors="coerce").fillna(0).to_numpy() >= 0, "UP", "DOWN")
    previous_5m = np.where(pd.to_numeric(signals.pre_return_5m, errors="coerce").fillna(0).to_numpy() >= 0, "UP", "DOWN")
    btc_trend = np.where(pd.to_numeric(signals.pre_btc_return_60m, errors="coerce").fillna(0).to_numpy() >= 0, "UP", "DOWN")
    result = {
        "always_long": accuracy(np.repeat("UP", len(signals))),
        "always_short": accuracy(np.repeat("DOWN", len(signals))),
        "majority_direction": accuracy(np.repeat(majority, len(signals))),
        "previous_1m": accuracy(previous_1m),
        "previous_5m": accuracy(previous_5m),
        "btc_trend": accuracy(btc_trend),
    }
    result["strongest_baseline"] = max(result.values())
    return result


def economic_metrics(rows: pd.DataFrame, round_trip_cost_percent: float = 0.20) -> dict[str, Any]:
    """Compute offline economics; funding is explicitly unavailable and set to zero."""
    signals = rows[rows.signal.isin(SIGNALS)].copy()
    if signals.empty:
        return {
            "signals": 0,
            "gross_expectancy_percent": None,
            "net_expectancy_percent": None,
            "profit_factor": None,
            "cumulative_return_percent": None,
            "maximum_drawdown_percent": None,
        }
    sign = signals.signal.map({"LONG": 1.0, "SHORT": -1.0}).to_numpy()
    gross = sign * pd.to_numeric(signals.future_return, errors="coerce").to_numpy()
    net = gross - round_trip_cost_percent
    cumulative = np.nancumsum(net)
    peaks = np.maximum.accumulate(np.r_[0.0, cumulative])[1:]
    drawdown = cumulative - peaks
    profit = float(np.nansum(net[net > 0]))
    loss = float(-np.nansum(net[net < 0]))
    return {
        "signals": len(signals),
        "gross_expectancy_percent": float(np.nanmean(gross)),
        "net_expectancy_percent": float(np.nanmean(net)),
        "profit_factor": profit / loss if loss > 0 else None,
        "cumulative_return_percent": float(np.nansum(net)),
        "maximum_drawdown_percent": float(np.nanmin(drawdown)) if len(drawdown) else None,
        "entry_fee_percent": 0.05,
        "exit_fee_percent": 0.05,
        "entry_slippage_percent": 0.05,
        "exit_slippage_percent": 0.05,
        "funding_percent": 0.0,
        "funding_available": False,
        "round_trip_cost_percent": round_trip_cost_percent,
    }


def canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def rejection_reasons(metrics: dict[str, Any], train_metrics: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if train_metrics.get("combined_signals", 0) < 30:
        reasons.append("train_signals_below_30")
    if metrics.get("combined_signals", 0) < 20:
        reasons.append("validation_predictions_below_20")
    if (metrics.get("coverage") or 0) < 0.20:
        reasons.append("coverage_below_20pct")
    if (metrics.get("dominant_direction_share") or 1) > 0.80:
        reasons.append("dominant_direction_above_80pct")
    if (metrics.get("combined_accuracy") or 0) <= 0.55:
        reasons.append("accuracy_not_above_55pct")
    if (metrics.get("combined_accuracy") or 0) <= (metrics.get("strongest_baseline") or 0):
        reasons.append("does_not_beat_strongest_baseline")
    if (metrics.get("gross_expectancy_percent") or 0) <= 0:
        reasons.append("nonpositive_validation_gross_expectancy")
    if (train_metrics.get("gross_expectancy_percent") or 0) <= 0:
        reasons.append("nonpositive_train_gross_expectancy")
    if (metrics.get("source_max_share") or 1) > 0.80:
        reasons.append("single_source_dependence")
    if (metrics.get("month_max_share") or 1) > 0.80:
        reasons.append("single_month_dependence")
    return reasons
