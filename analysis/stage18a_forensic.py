"""Pure helpers for Stage 18A.  No estimator fitting is permitted here."""
from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score


def probability_columns(classes: Iterable[Any]) -> dict[str, int]:
    values = [str(value) for value in classes]
    required = {"UP", "DOWN", "NEUTRAL"}
    if set(values) != required:
        raise ValueError(f"unexpected model classes: {values}")
    return {value: values.index(value) for value in required}


def replay_signals(probabilities: np.ndarray, classes: Iterable[Any], threshold: float = .4) -> pd.DataFrame:
    mapping = probability_columns(classes)
    up, down, neutral = (probabilities[:, mapping[name]] for name in ("UP", "DOWN", "NEUTRAL"))
    raw_index = probabilities.argmax(axis=1)
    values = np.asarray([str(value) for value in classes], dtype=object)
    directional = np.where(up >= down, "UP", "DOWN").astype(object)
    confidence = np.maximum(up, down)
    filtered = directional.copy(); filtered[confidence < threshold] = "NO_SIGNAL"
    return pd.DataFrame({"p_LONG": up, "p_SHORT": down, "p_NEUTRAL": neutral,
                         "raw_argmax_index": raw_index, "raw_argmax_class": values[raw_index],
                         "directional_winner": directional, "directional_confidence": confidence,
                         "winning_probability": probabilities.max(axis=1),
                         "second_probability": np.partition(probabilities, -2, axis=1)[:, -2],
                         "probability_margin": probabilities.max(axis=1)-np.partition(probabilities, -2, axis=1)[:, -2],
                         "after_confidence": filtered})


def target_from_percent(raw_return_percent: Any, threshold_percent: float = .10) -> str:
    value = float(raw_return_percent)
    return "UP" if value > threshold_percent else "DOWN" if value < -threshold_percent else "NEUTRAL"


def raw_return_percent(entry_open: float, exit_open: float) -> float:
    return (float(exit_open) / float(entry_open) - 1.0) * 100.0


def trade_return(raw_return: float, signal: str) -> float:
    if signal == "LONG": return float(raw_return)
    if signal == "SHORT": return -float(raw_return)
    return math.nan


def net_trade_return(raw_return: float, signal: str, cost_percent: float = .20) -> float:
    gross = trade_return(raw_return, signal)
    return gross - cost_percent if np.isfinite(gross) else math.nan


def signal_metrics(actual: Iterable[str], signals: Iterable[str], raw_returns: Iterable[float], cost: float = .20) -> dict[str, Any]:
    actual = np.asarray(list(actual), dtype=object); signals = np.asarray(list(signals), dtype=object)
    raw = np.asarray(list(raw_returns), dtype=float); predicted = np.where(signals == "LONG", "UP", "DOWN")
    valid = np.isin(signals, ["LONG", "SHORT"]); actual, predicted, raw, signals = actual[valid], predicted[valid], raw[valid], signals[valid]
    if not len(actual): return {"predictions":0,"accuracy":None,"balanced_accuracy":None,"net_expectancy":None,"profit_factor":None,"maximum_drawdown":None}
    accuracy = float(np.mean(actual == predicted))
    directional = np.isin(actual, ["UP", "DOWN"])
    balanced = float(balanced_accuracy_score(actual[directional], predicted[directional])) if directional.any() and len(set(actual[directional])) == 2 else None
    gross = np.where(signals == "LONG", raw, -raw); net = gross - cost
    profit, loss = net[net > 0].sum(), -net[net < 0].sum(); equity = np.cumsum(net); peaks = np.maximum.accumulate(np.r_[0.,equity])[1:]
    return {"predictions":int(len(actual)),"accuracy":accuracy,"balanced_accuracy":balanced,"gross_expectancy":float(gross.mean()),
            "net_expectancy":float(net.mean()),"profit_factor":float(profit/loss) if loss>0 else None,
            "cumulative_net_return":float(net.sum()),"maximum_drawdown":float((equity-peaks).min()),
            "long_count":int((signals=="LONG").sum()),"short_count":int((signals=="SHORT").sum()),
            "short_rate":float((signals=="SHORT").mean())}


def array_hash(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256(); digest.update(str(array.dtype).encode()); digest.update(str(array.shape).encode()); digest.update(array.tobytes())
    return digest.hexdigest()


def distribution(values: pd.Series) -> dict[str, float | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty: return {key:None for key in ("mean","median","p10","p25","p75","p90","min","max")}
    return {"mean":float(numeric.mean()),"median":float(numeric.median()),"p10":float(numeric.quantile(.1)),
            "p25":float(numeric.quantile(.25)),"p75":float(numeric.quantile(.75)),"p90":float(numeric.quantile(.9)),
            "min":float(numeric.min()),"max":float(numeric.max())}
