from __future__ import annotations

import json
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sklearn.metrics import balanced_accuracy_score, matthews_corrcoef, precision_score, recall_score

SEED = 20260719
OPERATORS = {
    "gte": lambda series, value: series >= value,
    "gt": lambda series, value: series > value,
    "lte": lambda series, value: series <= value,
    "lt": lambda series, value: series < value,
    "eq": lambda series, value: series == value,
    "in": lambda series, value: series.isin(value),
    "not_in": lambda series, value: ~series.isin(value),
}


def load_rules(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_rules(path: Path, rules: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")


def condition_mask(frame: pd.DataFrame, conditions: dict[str, dict[str, Any]]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for feature, operations in conditions.items():
        if feature not in frame:
            raise KeyError(feature)
        for operator, value in operations.items():
            if operator not in OPERATORS:
                raise ValueError(f"Unsupported operator: {operator}")
            mask &= OPERATORS[operator](frame[feature], value).fillna(False)
    return mask


def canonical_conditions(conditions: dict[str, dict[str, Any]]) -> str:
    return json.dumps(conditions, sort_keys=True, separators=(",", ":"))


def merge_duplicate_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {}
    for rule in rules:
        key = (rule["direction"], rule["target_horizon"], canonical_conditions(rule["conditions"]))
        unique.setdefault(key, rule)
    return list(unique.values())


def wilson_interval(wins: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total == 0:
        return np.nan, np.nan
    p = wins / total; denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z / denominator * sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return center - margin, center + margin


def bh_adjust(pvalues) -> np.ndarray:
    values = np.asarray(pvalues, float); order = np.argsort(values); adjusted = np.empty(len(values)); running = 1.0
    for i in range(len(values) - 1, -1, -1):
        index = order[i]; running = min(running, values[index] * len(values) / (i + 1)); adjusted[index] = running
    return adjusted


def target_column(horizon: str) -> str:
    return f"target_abnormal_return_{horizon}"


def evaluate_rule(frame: pd.DataFrame, rule: dict[str, Any], *, split: str, execution_column: str | None = None, round_trip_cost_pct: float = 0.0, bootstrap_repeats: int = 500) -> tuple[dict[str, Any], pd.DataFrame]:
    full_mask = condition_mask(frame, rule["conditions"]); matched = frame.loc[full_mask].copy()
    target = target_column(rule["target_horizon"]); sign = 1 if rule["direction"] == "bullish" else -1
    actual = sign * matched[target].astype(float); wins = actual > 0
    gross = sign * (matched[execution_column].astype(float) if execution_column else matched[target].astype(float))
    net = gross - round_trip_cost_pct
    low, high = wilson_interval(int(wins.sum()), len(wins))
    rng = np.random.default_rng(SEED)
    if len(wins):
        boot = wins.to_numpy()[rng.integers(0, len(wins), (bootstrap_repeats, len(wins)))].mean(axis=1); boot_low, boot_high = np.quantile(boot, [.025, .975])
    else:
        boot_low = boot_high = np.nan
    losses = -net[net < 0].sum(); equity = net.cumsum(); peak = np.maximum.accumulate(np.r_[0, equity.to_numpy()])[1:] if len(equity) else np.array([])
    actual_all = (sign * frame[target].astype(float) > 0).astype(int); predicted_all = full_mask.astype(int)
    metrics = {"rule_id": rule["rule_id"], "version": rule.get("version", "1"), "split": split, "direction": rule["direction"], "horizon": rule["target_horizon"], "complexity": len(rule["conditions"]),
               "n": len(matched), "wins": int(wins.sum()), "losses": int((~wins).sum()), "win_rate": float(wins.mean()) if len(wins) else np.nan, "wilson_low": low, "wilson_high": high,
               "balanced_accuracy": float(balanced_accuracy_score(actual_all, predicted_all)), "precision": float(precision_score(actual_all, predicted_all, zero_division=0)), "recall": float(recall_score(actual_all, predicted_all, zero_division=0)), "mcc": float(matthews_corrcoef(actual_all, predicted_all)),
               "bootstrap_win_rate_low": float(boot_low), "bootstrap_win_rate_high": float(boot_high), "p_vs_50": float(binomtest(int(wins.sum()), len(wins), .5, alternative="greater").pvalue) if len(wins) else 1.0,
               "mean_return": float(gross.mean()) if len(gross) else np.nan, "median_return": float(gross.median()) if len(gross) else np.nan, "mean_net_return": float(net.mean()) if len(net) else np.nan,
               "net_win_rate": float((net > 0).mean()) if len(net) else np.nan, "profit_factor": float(net[net > 0].sum() / losses) if losses else (float("inf") if len(net) and (net > 0).any() else np.nan),
               "max_drawdown": float((equity.to_numpy() - peak).min()) if len(equity) else np.nan, "source_count": int(matched.metadata_source.nunique()) if len(matched) else 0,
               "month_count": int(pd.to_datetime(matched.published_at, utc=True).dt.strftime("%Y-%m").nunique()) if len(matched) else 0}
    matched["rule_id"] = rule["rule_id"]; matched["rule_direction"] = rule["direction"]; matched["rule_horizon"] = rule["target_horizon"]; matched["gross_rule_return"] = gross; matched["net_rule_return"] = net
    return metrics, matched


def reject_reason(metrics: dict[str, Any], minimum_sample=30) -> str | None:
    if metrics["complexity"] > 4: return "complexity_gt_4"
    if metrics["n"] < minimum_sample: return "low_sample"
    if metrics["win_rate"] < .55: return "win_rate_below_55pct"
    if metrics["mean_net_return"] <= 0: return "nonpositive_net_expectancy"
    if metrics["profit_factor"] <= 1: return "profit_factor_le_1"
    if metrics["source_count"] < 2: return "single_source"
    if metrics["month_count"] < 2: return "single_month"
    return None
