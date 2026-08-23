"""Leakage-safe utilities for Stage 14 offline signal research."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


SEED = 20260719
COSTS = {
    "low": {"fee_bps": 2, "slippage_bps": 2, "latency_minutes": 1},
    "base": {"fee_bps": 5, "slippage_bps": 5, "latency_minutes": 1},
    "stress": {"fee_bps": 10, "slippage_bps": 15, "latency_minutes": 2},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_hashes(root: Path, hashes: dict[str, str]) -> list[dict]:
    return [{"path": relative, "expected": expected, "actual": sha256(root / relative) if (root / relative).exists() else None,
             "match": (root / relative).exists() and sha256(root / relative) == expected} for relative, expected in hashes.items()]


def bootstrap_mean(values: Iterable[float], repeats: int = 1000, seed: int = SEED) -> tuple[float, float]:
    values = np.asarray(list(values), float)
    if not len(values):
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    means = np.mean(values[rng.integers(0, len(values), (repeats, len(values)))], axis=1)
    return float(np.quantile(means, .025)), float(np.quantile(means, .975))


def ranking_tables(frame: pd.DataFrame, target: str, prediction: str, split_label: str):
    ordered = frame.sort_values(prediction, ascending=False).copy()
    overall = float(ordered[target].mean())
    groups = [("top_1pct", .01, "top"), ("top_5pct", .05, "top"), ("top_10pct", .10, "top"),
              ("top_20pct", .20, "top"), ("remaining_80pct", .80, "remaining"), ("bottom_20pct", .20, "bottom")]
    top_rows = []
    for name, fraction, kind in groups:
        count = max(1, int(np.ceil(len(ordered) * fraction)))
        part = ordered.head(count) if kind == "top" else ordered.tail(count) if kind == "bottom" else ordered.iloc[int(np.ceil(len(ordered) * .20)):]
        low, high = bootstrap_mean(part[target])
        top_rows.append({"split": split_label, "target": target, "group": name, "count": len(part), "actual_mean": part[target].mean(),
                         "actual_median": part[target].median(), "actual_p75": part[target].quantile(.75), "actual_p90": part[target].quantile(.90),
                         "lift_vs_overall": part[target].mean() / overall if overall else np.nan, "mean_ci_low": low, "mean_ci_high": high,
                         "spearman_within_group": spearmanr(part[prediction], part[target]).statistic if len(part) > 2 else np.nan})
    ordered["prediction_decile"] = pd.qcut(ordered[prediction].rank(method="first"), 10, labels=False) + 1
    deciles = ordered.groupby("prediction_decile").agg(count=(target, "size"), prediction_mean=(prediction, "mean"), actual_mean=(target, "mean"),
                                                        actual_median=(target, "median"), actual_p75=(target, lambda x: x.quantile(.75)), actual_p90=(target, lambda x: x.quantile(.90))).reset_index()
    monotonic = spearmanr(deciles.prediction_decile, deciles.actual_mean).statistic
    deciles.insert(0, "target", target); deciles.insert(0, "split", split_label); deciles["decile_monotonicity_spearman"] = monotonic
    return pd.DataFrame(top_rows), deciles


def directional_signals(frame: pd.DataFrame) -> pd.DataFrame:
    signals = pd.DataFrame(index=frame.index)
    for horizon in ("5m", "15m", "1h"):
        signals[f"eth_momentum_{horizon}"] = np.sign(frame[f"pre_eth_return_{horizon}"]).astype(int)
    adjusted = frame.pre_eth_return_15m - frame.pre_eth_btc_rolling_beta * frame.pre_btc_return_15m
    signals["btc_adjusted_momentum"] = np.sign(adjusted).astype(int)
    trend_agree = np.sign(frame.pre_eth_distance_sma50) == np.sign(frame.pre_eth_sma50_slope)
    signals["trend"] = np.where(trend_agree, np.sign(frame.pre_eth_distance_sma50), 0).astype(int)
    breakout_strength = frame.pre_eth_return_15m.abs() / frame.pre_eth_realized_vol_15m.replace(0, np.nan)
    signals["breakout"] = np.where(breakout_strength >= 1, np.sign(frame.pre_eth_return_15m), 0).astype(int)
    rng = np.random.default_rng(SEED)
    signals["random_fixed_seed"] = rng.choice([-1, 1], len(frame))
    return signals


def apply_non_overlap(frame: pd.DataFrame, signal: pd.Series, holding_minutes: int) -> pd.Series:
    keep = pd.Series(False, index=frame.index)
    ordered = frame.assign(_signal=signal.reindex(frame.index).fillna(0).to_numpy()).sort_values("entry_time")
    next_available = np.iinfo(np.int64).min
    holding_ns = holding_minutes * 60 * 1_000_000_000
    for index, timestamp, value in zip(ordered.index, ordered.entry_time.astype("int64"), ordered._signal):
        if value and timestamp >= next_available:
            keep.at[index] = True
            next_available = timestamp + holding_ns
    return keep


def pnl_metrics(frame: pd.DataFrame, pnl: pd.Series, size: pd.Series | None = None) -> dict[str, float]:
    values = pnl.dropna().to_numpy(float)
    if not len(values):
        return {key: np.nan for key in ("trade_count", "cumulative_return", "mean_return", "win_rate", "profit_factor", "max_drawdown", "volatility", "sharpe_like", "downside_deviation", "average_exposure")}
    equity = np.cumsum(values); peak = np.maximum.accumulate(np.r_[0, equity])[1:]; drawdown = equity - peak
    losses = -values[values < 0].sum(); downside = values[values < 0]
    return {"trade_count": int(len(values)), "cumulative_return": float(values.sum()), "mean_return": float(values.mean()), "win_rate": float(np.mean(values > 0)),
            "profit_factor": float(values[values > 0].sum() / losses) if losses else np.inf, "max_drawdown": float(drawdown.min()), "volatility": float(values.std(ddof=1)) if len(values) > 1 else 0,
            "sharpe_like": float(values.mean() / values.std(ddof=1) * np.sqrt(len(values))) if len(values) > 1 and values.std(ddof=1) else 0,
            "downside_deviation": float(np.sqrt(np.mean(downside ** 2))) if len(downside) else 0, "average_exposure": float(size.loc[pnl.dropna().index].mean()) if size is not None else 1.0}


def simulate(frame: pd.DataFrame, signal: pd.Series, holding: int, cost_bps: float, *, overlap: bool, size: pd.Series | None = None) -> tuple[pd.Series, dict]:
    active = signal.ne(0) & frame[f"execution_return_{holding}m"].notna()
    if not overlap:
        active &= apply_non_overlap(frame, signal.where(active, 0), holding)
    position_size = pd.Series(1.0, index=frame.index) if size is None else size
    active &= position_size.gt(0)
    gross = signal * frame[f"execution_return_{holding}m"] * position_size
    pnl = (gross - cost_bps / 100 * position_size).where(active)
    return pnl, pnl_metrics(frame, pnl, position_size)


def benjamini_hochberg(pvalues: Iterable[float]) -> np.ndarray:
    values = np.asarray(list(pvalues), float); order = np.argsort(values); adjusted = np.empty(len(values)); running = 1.0
    for rank_index in range(len(values) - 1, -1, -1):
        original = order[rank_index]; running = min(running, values[original] * len(values) / (rank_index + 1)); adjusted[original] = running
    return adjusted


def permutation_difference(a: Iterable[float], b: Iterable[float], repeats=1000, seed=SEED):
    a, b = np.asarray(list(a), float), np.asarray(list(b), float)
    observed = float(np.mean(a) - np.mean(b)); pooled = np.r_[a, b]; rng = np.random.default_rng(seed); count = 0
    for _ in range(repeats):
        shuffled = rng.permutation(pooled); diff = shuffled[:len(a)].mean() - shuffled[len(a):].mean(); count += abs(diff) >= abs(observed)
    return observed, (count + 1) / (repeats + 1)
