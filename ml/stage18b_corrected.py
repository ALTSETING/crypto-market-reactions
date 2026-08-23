"""Pure helpers for the corrected Stage 18B offline rebuild."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score

from ml.stage18_unified import semantic_score


SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {
    "stage9_eth_label_v1": {"dataset": "A", "prompt_version": "eth_label_v1", "unsigned": "zero_hundred", "signed": "minus_hundred_hundred"},
    "high_impact_semantic_v2_1": {"dataset": "B", "prompt_version": "high_impact_semantic_v2_1", "unsigned": "zero_hundred", "signed": "minus_hundred_hundred"},
    "archive_local_relevance_v1": {"dataset": "C", "prompt_version": None, "unsigned": "zero_hundred", "signed": "minus_hundred_hundred"},
    "known_missing_semantics_v1": {"dataset": "D", "prompt_version": None, "unsigned": "zero_hundred", "signed": "minus_hundred_hundred"},
}


def normalize_semantic_value(value: Any, schema_version: str, *, signed: bool = False) -> float:
    if schema_version not in SCHEMA_REGISTRY:
        raise ValueError(f"unknown semantic schema: {schema_version}")
    spec = SCHEMA_REGISTRY[schema_version]
    return semantic_score(value, spec["signed" if signed else "unsigned"])


def normalize_semantic_series(series: pd.Series, schema_version: str, *, signed: bool = False) -> pd.Series:
    return series.map(lambda value: normalize_semantic_value(value, schema_version, signed=signed))


def semantic_gate(frame: pd.DataFrame, columns: Iterable[str]) -> dict[str, int]:
    numeric = frame[list(columns)].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(numeric.to_numpy(float)) | numeric.isna().to_numpy()
    invalid = int((~finite).sum())
    out = 0
    for column in columns:
        values = numeric[column].dropna()
        lower = -1.0 if "valence_score" in column else 0.0
        out += int(((values < lower) | (values > 1.0)).sum())
    return {"semantic_out_of_range_count": out, "invalid_numeric_count": invalid,
            "infinite_values_count": invalid}


def probability_map(model: Any, probabilities: np.ndarray) -> pd.DataFrame:
    classes = [str(value) for value in model.named_steps["model"].classes_]
    required = {"DOWN", "NEUTRAL", "UP"}
    if not required.issubset(classes):
        raise ValueError(f"required classes absent: {sorted(required - set(classes))}")
    return pd.DataFrame({f"p_{label}": probabilities[:, classes.index(label)] for label in ("DOWN", "NEUTRAL", "UP")})


def signal_from_probabilities(probabilities: pd.DataFrame, threshold: float) -> pd.DataFrame:
    result = probabilities.copy()
    result["raw_class"] = result[["p_DOWN", "p_NEUTRAL", "p_UP"]].idxmax(axis=1).str.removeprefix("p_")
    result["directional_confidence"] = result[["p_DOWN", "p_UP"]].max(axis=1)
    result["predicted_direction"] = np.where(result.p_UP >= result.p_DOWN, "UP", "DOWN")
    result.loc[result.directional_confidence < threshold, "predicted_direction"] = "NO_SIGNAL"
    return result


def max_streak(values: Iterable[bool], target: bool) -> int:
    best = current = 0
    for value in values:
        current = current + 1 if bool(value) is target else 0
        best = max(best, current)
    return best


def full_performance(frame: pd.DataFrame, cost: float = 0.20) -> dict[str, Any]:
    part = frame[frame.signal.isin(["LONG", "SHORT"])].copy()
    if part.empty:
        return {"signals": 0}
    gross = pd.to_numeric(part.gross_return, errors="coerce").to_numpy(float)
    gross = gross[np.isfinite(gross)]
    net = gross - cost
    equity = np.cumsum(net)
    peaks = np.maximum.accumulate(np.r_[0.0, equity])[1:]
    losses = -net[net < 0].sum()
    gross_losses = -gross[gross < 0].sum()
    winners, losers = net[net > 0], net[net < 0]
    predicted = part["predicted_direction"] if "predicted_direction" in part else part["signal"].map({"LONG": "UP", "SHORT": "DOWN"})
    actual = part["actual_direction"] if "actual_direction" in part else part["target"]
    correct = predicted.eq(actual).to_numpy()
    directional = actual.isin(["UP", "DOWN"])
    balanced = (balanced_accuracy_score(actual.loc[directional], predicted.loc[directional])
                if directional.any() and actual.loc[directional].nunique() == 2 else math.nan)
    es_count = max(1, math.ceil(len(net) * .05))
    return {
        "signals": int(len(net)), "accuracy": float(correct.mean()), "balanced_accuracy": float(balanced),
        "total_gross_return": float(gross.sum()), "mean_gross_return": float(gross.mean()),
        "median_gross_return": float(np.median(gross)), "gross_win_rate": float((gross > 0).mean()),
        "gross_profit_factor": float(gross[gross > 0].sum() / gross_losses) if gross_losses else None,
        "total_net_return": float(net.sum()), "mean_net_return": float(net.mean()), "median_net_return": float(np.median(net)),
        "net_win_rate": float((net > 0).mean()), "net_profit_factor": float(net[net > 0].sum() / losses) if losses else None,
        "cumulative_net_return": float(equity[-1]), "maximum_drawdown": float((equity - peaks).min()),
        "recovery_factor": float(equity[-1] / abs((equity - peaks).min())) if (equity - peaks).min() < 0 else None,
        "standard_deviation": float(np.std(net, ddof=1)) if len(net) > 1 else 0.0,
        "downside_deviation": float(np.sqrt(np.mean(np.minimum(net, 0) ** 2))), "worst_trade": float(net.min()),
        "best_trade": float(net.max()), "average_winner": float(winners.mean()) if len(winners) else None,
        "average_loser": float(losers.mean()) if len(losers) else None,
        "payoff_ratio": float(winners.mean() / abs(losers.mean())) if len(winners) and len(losers) else None,
        "expected_shortfall_5pct": float(np.sort(net)[:es_count].mean()),
        "longest_losing_streak": max_streak(net < 0, True), "longest_winning_streak": max_streak(net > 0, True),
    }


def grouped_performance(frame: pd.DataFrame, dimensions: list[str], cost: float = .20) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, part in frame.groupby(dimensions, dropna=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        rows.append({**dict(zip(dimensions, keys)), **full_performance(part, cost)})
    return pd.DataFrame(rows)


def cluster_bootstrap(frame: pd.DataFrame, iterations: int, seed: int, baseline_accuracy: float) -> dict[str, Any]:
    part = frame[frame.signal.isin(["LONG", "SHORT"])].copy()
    clusters = [group.index.to_numpy() for _, group in part.groupby("event_id", sort=True)]
    rng = np.random.default_rng(seed)
    accuracy, expectancy, pf, cumulative, drawdown = [], [], [], [], []
    for _ in range(iterations):
        chosen = rng.integers(0, len(clusters), len(clusters))
        sample = part.loc[np.concatenate([clusters[i] for i in chosen])].reset_index(drop=True)
        metrics = full_performance(sample)
        accuracy.append(metrics["accuracy"]); expectancy.append(metrics["mean_net_return"])
        pf.append(metrics["net_profit_factor"] if metrics["net_profit_factor"] is not None else np.inf)
        cumulative.append(metrics["cumulative_net_return"]); drawdown.append(metrics["maximum_drawdown"])
    def summary(values: list[float]) -> dict[str, float]:
        array = np.asarray(values, float)
        finite = array[np.isfinite(array)]
        return {"mean": float(np.mean(finite)), "ci95_low": float(np.quantile(finite, .025)), "ci95_high": float(np.quantile(finite, .975))}
    return {"iterations": iterations, "cluster_count": len(clusters), "accuracy": summary(accuracy),
            "mean_net_expectancy": summary(expectancy), "profit_factor": summary(pf),
            "cumulative_net_return": summary(cumulative), "maximum_drawdown": summary(drawdown),
            "probability_net_expectancy_positive": float(np.mean(np.asarray(expectancy) > 0)),
            "probability_profit_factor_above_one": float(np.mean(np.asarray(pf) > 1)),
            "probability_accuracy_above_55pct": float(np.mean(np.asarray(accuracy) > .55)),
            "probability_beats_strongest_baseline": float(np.mean(np.asarray(accuracy) > baseline_accuracy))}


def event_block_permutation(frame: pd.DataFrame, iterations: int, seed: int) -> dict[str, Any]:
    part = frame[frame.signal.isin(["LONG", "SHORT"])].copy().reset_index(drop=True)
    event_order = part.event_id.drop_duplicates().tolist()
    event_positions = {event: np.flatnonzero(part.event_id.to_numpy() == event) for event in event_order}
    predictions = (part["predicted_direction"] if "predicted_direction" in part else part["signal"].map({"LONG": "UP", "SHORT": "DOWN"})).to_numpy()
    labels = (part["actual_direction"] if "actual_direction" in part else part["target"]).to_numpy()
    gross = part.gross_return.to_numpy(float)
    raw_returns = part.return_12h.to_numpy(float) if "return_12h" in part else gross.copy()
    observed_accuracy = float(np.mean(predictions == labels))
    observed_net = float(np.mean(gross - .20))
    observed_pf = full_performance(part)["net_profit_factor"] or 0.0
    observed_cumulative = float(np.sum(gross - .20))
    rng = np.random.default_rng(seed)
    null_accuracy = np.empty(iterations); null_net = np.empty(iterations); null_pf = np.empty(iterations); null_cum = np.empty(iterations)
    for iteration in range(iterations):
        shuffled_events = rng.permutation(event_order)
        perm_labels = labels.copy(); perm_raw = raw_returns.copy()
        for destination, source in zip(event_order, shuffled_events):
            dst, src = event_positions[destination], event_positions[source]
            # Event assets are not necessarily equally sized; preserve each destination block by cycling source values.
            perm_labels[dst] = np.resize(labels[src], len(dst)); perm_raw[dst] = np.resize(raw_returns[src], len(dst))
        null_accuracy[iteration] = np.mean(predictions == perm_labels)
        signed = np.where(predictions == "UP", perm_raw, -perm_raw)
        net = signed - .20; null_net[iteration] = net.mean(); null_cum[iteration] = net.sum()
        loss = -net[net < 0].sum(); null_pf[iteration] = net[net > 0].sum() / loss if loss else np.inf
    return {"iterations": iterations, "seed": seed, "method": "event-block frozen-pipeline association permutation",
            "accuracy_observed": observed_accuracy, "accuracy_pvalue": float((1 + np.sum(null_accuracy >= observed_accuracy)) / (iterations + 1)),
            "net_expectancy_observed": observed_net, "net_expectancy_pvalue": float((1 + np.sum(null_net >= observed_net)) / (iterations + 1)),
            "profit_factor_observed": observed_pf, "profit_factor_pvalue": float((1 + np.sum(null_pf >= observed_pf)) / (iterations + 1)),
            "cumulative_return_observed": observed_cumulative, "cumulative_return_pvalue": float((1 + np.sum(null_cum >= observed_cumulative)) / (iterations + 1))}


def file_tree_hash(paths: Iterable[Path], root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(set(paths)):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[str(path.relative_to(root))] = digest
    return result


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
