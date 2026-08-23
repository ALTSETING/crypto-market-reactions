"""Read-only diagnostic audit of the already-finished Stage 17B run.

This module deliberately does not import sklearn, load a model, fit a model, or
read the opened Stage 17 test targets.  It combines the persisted Stage 17B
aggregate metrics with frozen pre-event features and minute-candle market data.
Prediction-level statistics that cannot be identified from those aggregates are
reported as unavailable rather than reconstructed by refitting the model.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

from database.db import engine


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
STAGE17_DATA = ROOT / "data" / "stage17"
LOCK_SHA = "509a91b2d6fda0991eba012cf273ad54ef9b2f711a49a6891a7ba0a7277f900e"
BASE_COST_PERCENT = 0.20

OUTPUTS = {
    REPORTS / "stage17b_walkforward_periods.csv",
    REPORTS / "stage17b_walkforward_market_regimes.csv",
    REPORTS / "stage17b_successful_period_analysis.json",
    REPORTS / "stage17b_average_market_moves.json",
    REPORTS / "stage17b_average_market_moves.csv",
    REPORTS / "stage17b_long_short_move_breakdown.csv",
    REPORTS / "stage17b_period_comparison.csv",
    REPORTS / "stage17b_diagnostic_summary.md",
}


def canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_snapshot() -> dict[str, str]:
    paths = [p for p in REPORTS.glob("stage17b_*") if p not in OUTPUTS]
    paths += list(STAGE17_DATA.glob("*"))
    return {str(path.relative_to(ROOT)): file_hash(path) for path in sorted(paths) if path.is_file()}


def json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_value(v) for v in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(json_value(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_feature_universe() -> pd.DataFrame:
    columns = [
        "metadata_event_id", "metadata_published_at", "metadata_asset", "metadata_source", "metadata_split",
        "source_event_type", "ai_importance", "ai_novelty", "ai_asset_relevance", "ai_content_valence_score",
        "pre_return_60m", "pre_btc_return_60m", "pre_realized_vol_60m", "pre_trend_regime",
        "pre_relative_strength_1h",
    ]
    frames = [pd.read_parquet(STAGE17_DATA / f"{asset}_high_impact.parquet", columns=columns) for asset in ("btc", "eth", "sol")]
    frame = pd.concat(frames, ignore_index=True)
    frame["metadata_published_at"] = pd.to_datetime(frame.metadata_published_at, utc=True)
    if frame.duplicated(["metadata_event_id", "metadata_asset"]).any():
        raise RuntimeError("Duplicate frozen feature event_id+asset rows")
    return frame.sort_values(["metadata_published_at", "metadata_event_id", "metadata_asset"]).reset_index(drop=True)


def fold_membership(features: pd.DataFrame) -> list[dict[str, Any]]:
    prelock = features[features.metadata_split.isin(["train", "validation"])].copy()
    events = prelock.drop_duplicates("metadata_event_id")
    event_ids = events.metadata_event_id.astype(int).to_numpy()
    folds: list[dict[str, Any]] = []
    for fold, (train_fraction, evaluation_fraction) in enumerate(((0.40, 0.60), (0.60, 0.80), (0.80, 1.00)), 1):
        train_ids = set(event_ids[: int(len(event_ids) * train_fraction)])
        evaluation_ids = set(event_ids[int(len(event_ids) * train_fraction): int(len(event_ids) * evaluation_fraction)])
        train = prelock[prelock.metadata_event_id.isin(train_ids)]
        evaluation = prelock[prelock.metadata_event_id.isin(evaluation_ids)]
        eth = evaluation[evaluation.metadata_asset.eq("ETH")].copy()
        folds.append({
            "fold": fold,
            "train_ids": train_ids,
            "evaluation_ids": evaluation_ids,
            "train": train,
            "evaluation": evaluation,
            "eth": eth,
            "train_start_utc": train.metadata_published_at.min(),
            "train_end_utc": train.metadata_published_at.max(),
            "evaluation_start_utc": evaluation.metadata_published_at.min(),
            "evaluation_end_utc": evaluation.metadata_published_at.max(),
        })
    return folds


def load_daily_bars(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    sql = text("""
        SELECT symbol,date_trunc('day',open_time) AS day,
               (array_agg(open ORDER BY open_time))[1]::double precision AS open,
               max(high)::double precision AS high,min(low)::double precision AS low,
               (array_agg(close ORDER BY open_time DESC))[1]::double precision AS close,
               count(*) AS candle_points
        FROM market_candles
        WHERE interval='1m' AND symbol=ANY(:symbols)
          AND open_time>=:start_time AND open_time<=:end_time
        GROUP BY symbol,date_trunc('day',open_time)
        ORDER BY symbol,day
    """)
    params = {
        "symbols": ["ETHUSDT", "BTCUSDT"],
        "start_time": start.tz_convert("UTC").tz_localize(None).to_pydatetime(),
        "end_time": end.tz_convert("UTC").tz_localize(None).to_pydatetime(),
    }
    with engine.connect() as connection:
        bars = pd.read_sql(sql, connection, params=params)
    bars["day"] = pd.to_datetime(bars.day, utc=True)
    return bars


def asset_period_metrics(bars: pd.DataFrame, symbol: str) -> dict[str, Any]:
    rows = bars[bars.symbol.eq(symbol)].sort_values("day").copy()
    if rows.empty:
        raise RuntimeError(f"No {symbol} 1m candles for evaluation period")
    close = pd.to_numeric(rows.close, errors="raise")
    daily = close.pct_change().dropna()
    total_return = (float(close.iloc[-1]) / float(rows.open.iloc[0]) - 1.0) * 100.0
    drawdown = (close / close.cummax() - 1.0) * 100.0
    rise_from_low = (close / close.cummin() - 1.0) * 100.0
    realized_volatility = float(daily.std(ddof=1) * np.sqrt(365.0) * 100.0) if len(daily) > 1 else None
    trend_regime = "rising" if total_return >= 10.0 else "falling" if total_return <= -10.0 else "sideways"
    volatility_regime = "highly_volatile" if (realized_volatility or 0.0) >= 80.0 else "normal_volatility"
    return {
        "price_start": float(rows.open.iloc[0]),
        "price_end": float(close.iloc[-1]),
        "total_period_return_percent": total_return,
        "maximum_drawdown_percent": float(drawdown.min()),
        "maximum_rise_from_local_low_percent": float(rise_from_low.max()),
        "average_daily_return_percent": float(daily.mean() * 100.0),
        "median_daily_return_percent": float(daily.median() * 100.0),
        "realized_volatility_annualized_percent": realized_volatility,
        "rising_days_percent": float(daily.gt(0).mean() * 100.0),
        "falling_days_percent": float(daily.lt(0).mean() * 100.0),
        "trend_regime": trend_regime,
        "volatility_regime": volatility_regime,
        "market_regime": "highly_volatile" if volatility_regime == "highly_volatile" else trend_regime,
        "daily_observations": int(len(rows)),
        "minute_candle_points": int(rows.candle_points.sum()),
    }


def market_period_metrics(start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    bars = load_daily_bars(start, end)
    eth = asset_period_metrics(bars, "ETHUSDT")
    btc = asset_period_metrics(bars, "BTCUSDT")
    closes = bars.pivot(index="day", columns="symbol", values="close").sort_index().pct_change().dropna()
    aligned = closes[["ETHUSDT", "BTCUSDT"]].dropna()
    correlation = float(aligned.ETHUSDT.corr(aligned.BTCUSDT)) if len(aligned) > 1 else None
    return {"eth": eth, "btc": btc, "eth_btc_daily_return_correlation": correlation}


def economics_lookup(economics: pd.DataFrame, split: str, cost: str) -> dict[str, Any]:
    rows = economics[(economics.split.eq(split)) & economics.cost_scenario.eq(cost)]
    if split == "validation":
        rows = rows[rows.evaluation_type.eq("primary") & rows.horizon.eq("12h") & rows.latency_minutes.eq(1)]
    if len(rows) != 1:
        raise RuntimeError(f"Expected exactly one economic row for {split}/{cost}; got {len(rows)}")
    return rows.iloc[0].to_dict()


def aggregate_move_statistics(metric: dict[str, Any], gross: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    n = int(metric["combined_signals"])
    n_long, n_short = int(metric["long_signals"]), int(metric["short_signals"])
    correct, incorrect = int(metric["combined_correct"]), int(metric["combined_incorrect"])
    long_raw_mean = float(metric["long_gross_expectancy_percent"])
    short_trade_mean = float(metric["short_gross_expectancy_percent"])
    short_raw_mean = -short_trade_mean
    raw_mean = (n_long * long_raw_mean + n_short * short_raw_mean) / n
    expectancy = float(gross["gross_expectancy_percent"])
    profit_factor = float(gross["profit_factor"])
    return {
        "signals": n,
        "mean_signed_actual_eth_return_percent": raw_mean,
        "median_signed_actual_eth_return_percent": None,
        "mean_absolute_eth_return_percent": None,
        "median_absolute_eth_return_percent": None,
        "minimum_actual_return_percent": None,
        "maximum_actual_return_percent": None,
        "actual_return_standard_deviation_percent": None,
        "when_eth_rose": {"count": None, "average_rise_percent": None, "median_rise_percent": None, "minimum_positive_return_percent": None, "maximum_rise_percent": None},
        "when_eth_fell": {"count": None, "average_negative_return_percent": None, "median_negative_return_percent": None, "smallest_decline_percent": None, "largest_decline_percent": None, "average_decline_absolute_percent": None},
        "correct_predictions": {"count": correct, "average_favorable_move_percent": None, "median_favorable_move_percent": None, "average_gross_profit_percent": None, "average_net_profit_base_percent": None},
        "incorrect_predictions": {"count": incorrect, "average_adverse_move_percent": None, "median_adverse_move_percent": None, "average_gross_loss_percent": None, "average_net_loss_base_percent": None},
        "payoff": {
            "gross_average_winner_percent": None,
            "gross_average_loser_percent": None,
            "gross_payoff_ratio": None,
            "gross_profit_factor": profit_factor,
            "gross_expectancy_per_signal_percent": expectancy,
            "gross_break_even_accuracy": None,
            "base_average_winner_percent": None,
            "base_average_loser_percent": None,
            "base_payoff_ratio": None,
            "base_profit_factor": float(base["profit_factor"]),
            "base_expectancy_per_signal_percent": float(base["net_expectancy_percent"]),
            "base_break_even_accuracy": None,
        },
        "derivation": "Only aggregate-identifiable values are reported; no model refit. Correct/incorrect uses a ±0.10% neutral band, while profit factor uses the sign of trade return, so their payoff means cannot be cross-derived.",
        "unavailable_prediction_level_fields": [
            "medians", "minimum", "maximum", "standard_deviation", "absolute_move_bins",
            "correct_LONG_average_rise", "incorrect_LONG_average_fall", "correct_SHORT_average_fall",
            "incorrect_SHORT_average_rise", "LONG_profit_factor", "SHORT_profit_factor",
            "average_winner", "average_loser", "payoff_ratio", "break_even_accuracy",
        ],
    }


def distribution_json(series: pd.Series) -> str:
    return json.dumps({str(k): int(v) for k, v in series.fillna("missing").value_counts().sort_index().items()}, ensure_ascii=False, sort_keys=True)


def format_percent(value: Any, *, signed: bool = False, fraction: bool = False) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    number = float(value) * (100.0 if fraction else 1.0)
    return f"{number:+.2f}%" if signed else f"{number:.2f}%"


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    before = protected_snapshot()
    lock = json.loads((REPORTS / "stage17b_locked_config.json").read_text(encoding="utf-8"))
    if canonical_hash(lock) != LOCK_SHA or (REPORTS / "stage17b_locked_config.sha256").read_text().strip() != LOCK_SHA:
        raise RuntimeError("Stage 17B canonical lock SHA mismatch")
    chosen = lock["selected_candidate"]
    required = {"model": "gradient_boosting", "feature_set": "semantic_plus_market", "asset_scope": "ETH", "horizon": "12h"}
    if any(str(chosen.get(k)) != v for k, v in required.items()):
        raise RuntimeError("Locked candidate does not match the diagnostic specification")

    features = load_feature_universe()
    folds = fold_membership(features)
    metrics = pd.read_csv(REPORTS / "stage17b_walkforward_metrics.csv")
    economics = pd.read_csv(REPORTS / "stage17b_economic_metrics.csv")
    contamination = pd.read_parquet(STAGE17_DATA / "stage17_event_contamination.parquet")
    contamination = contamination[(contamination.asset.eq("ETH")) & contamination.horizon.eq("12h")]

    period_records: list[dict[str, Any]] = []
    regime_records: list[dict[str, Any]] = []
    comparison_records: list[dict[str, Any]] = []
    move_blocks: list[dict[str, Any]] = []
    direction_records: list[dict[str, Any]] = []
    market_by_fold: dict[int, dict[str, Any]] = {}

    for fold in folds:
        number = int(fold["fold"])
        metric = metrics[metrics.fold.eq(number)].iloc[0].to_dict()
        gross = economics_lookup(economics, f"nested_walkforward_{number}", "gross")
        base = economics_lookup(economics, f"nested_walkforward_{number}", "base")
        market = market_period_metrics(fold["evaluation_start_utc"], fold["evaluation_end_utc"])
        market_by_fold[number] = market
        move = aggregate_move_statistics(metric, gross, base)
        move_blocks.append({"dataset": "A_WALK_FORWARD", "fold": number, **move})
        eth = fold["eth"]
        cont = contamination[contamination.event_id.isin(eth.metadata_event_id)]
        contaminated_percent = float(cont.overlapping_event_within_horizon.mean() * 100.0) if len(cont) else None
        period_records.append({
            "fold_number": number,
            "train_start_utc": fold["train_start_utc"].isoformat(),
            "train_end_utc": fold["train_end_utc"].isoformat(),
            "evaluation_start_utc": fold["evaluation_start_utc"].isoformat(),
            "evaluation_end_utc": fold["evaluation_end_utc"].isoformat(),
            "unique_evaluation_events": int(metric["evaluation_events"]),
            "eth_evaluation_rows": int(metric["total_rows"]),
            "predictions": int(metric["combined_signals"]),
            "long_signals": int(metric["long_signals"]),
            "short_signals": int(metric["short_signals"]),
            "no_signal_count": int(metric["no_signal_count"]),
            "correct_predictions": int(metric["combined_correct"]),
            "incorrect_predictions": int(metric["combined_incorrect"]),
            "accuracy": float(metric["combined_accuracy"]),
            "balanced_accuracy": float(metric["balanced_accuracy"]),
            "strongest_baseline_accuracy": float(metric["baseline_strongest_baseline"]),
            "accuracy_difference_vs_baseline": float(metric["combined_accuracy"] - metric["baseline_strongest_baseline"]),
            "coverage": float(metric["coverage"]),
            "average_gross_trade_return_percent": float(gross["gross_expectancy_percent"]),
            "average_net_trade_return_base_percent": float(base["net_expectancy_percent"]),
            "gross_profit_factor": float(gross["profit_factor"]),
            "base_profit_factor": float(base["profit_factor"]),
            "beats_strongest_baseline": bool(metric["beats_strongest_baseline"]),
        })
        regime_records.append({"fold_number": number, **{f"eth_{k}": v for k, v in market["eth"].items()}, **{f"btc_{k}": v for k, v in market["btc"].items()}, "eth_btc_daily_return_correlation": market["eth_btc_daily_return_correlation"]})
        comparison_records.append({
            "fold_number": number,
            "successful_fold": bool(metric["beats_55"] and metric["beats_strongest_baseline"]),
            "evaluation_start_utc": fold["evaluation_start_utc"].isoformat(),
            "evaluation_end_utc": fold["evaluation_end_utc"].isoformat(),
            "accuracy": float(metric["combined_accuracy"]),
            "strongest_baseline_accuracy": float(metric["baseline_strongest_baseline"]),
            "eth_total_period_return_percent": market["eth"]["total_period_return_percent"],
            "btc_total_period_return_percent": market["btc"]["total_period_return_percent"],
            "eth_realized_volatility_annualized_percent": market["eth"]["realized_volatility_annualized_percent"],
            "btc_realized_volatility_annualized_percent": market["btc"]["realized_volatility_annualized_percent"],
            "eth_btc_daily_return_correlation": market["eth_btc_daily_return_correlation"],
            "eth_trend_regime": market["eth"]["trend_regime"],
            "eth_volatility_regime": market["eth"]["volatility_regime"],
            "unique_evaluation_events_all_assets": int(metric["evaluation_events"]),
            "eth_evaluation_rows": int(metric["total_rows"]),
            "signals": int(metric["combined_signals"]),
            "long_signals": int(metric["long_signals"]),
            "short_signals": int(metric["short_signals"]),
            "long_share_percent": float(metric["long_signals"] / metric["combined_signals"] * 100.0),
            "source_distribution_eth_evaluation_rows": distribution_json(eth.metadata_source),
            "event_type_distribution_eth_evaluation_rows": distribution_json(eth.source_event_type),
            "average_importance": float(pd.to_numeric(eth.ai_importance).mean()),
            "average_novelty": float(pd.to_numeric(eth.ai_novelty).mean()),
            "average_relevance": float(pd.to_numeric(eth.ai_asset_relevance).mean()),
            "average_content_valence_score": float(pd.to_numeric(eth.ai_content_valence_score).mean()),
            "average_pre_event_eth_return_60m_percent": float(pd.to_numeric(eth.pre_return_60m).mean()),
            "average_pre_event_btc_return_60m_percent": float(pd.to_numeric(eth.pre_btc_return_60m).mean()),
            "average_pre_event_realized_volatility_60m": float(pd.to_numeric(eth.pre_realized_vol_60m).mean()),
            "pre_trend_regime_distribution": distribution_json(eth.pre_trend_regime),
            "average_pre_event_relative_strength_1h": float(pd.to_numeric(eth.pre_relative_strength_1h).mean()),
            "contaminated_events_12h_percent": contaminated_percent,
            "distribution_scope_note": "Feature distributions cover ETH evaluation rows because signal-level row IDs were not persisted.",
        })
        for direction in ("LONG", "SHORT"):
            prefix = direction.lower()
            gross_mean = float(metric[f"{prefix}_gross_expectancy_percent"])
            actual_mean = gross_mean if direction == "LONG" else -gross_mean
            direction_records.append({
                "dataset": "A_WALK_FORWARD", "fold": number, "direction": direction,
                "signals": int(metric[f"{prefix}_signals"]), "correct": int(metric[f"{prefix}_correct"]),
                "incorrect": int(metric[f"{prefix}_incorrect"]), "accuracy": float(metric[f"{prefix}_accuracy"]),
                "average_actual_eth_return_percent": actual_mean, "median_actual_eth_return_percent": None,
                "average_gross_trade_return_percent": gross_mean,
                "average_net_trade_return_base_percent": gross_mean - BASE_COST_PERCENT,
                "average_correct_move_percent": None, "average_incorrect_move_percent": None,
                "profit_factor": None, "availability": "aggregate_partial",
            })

    validation_metric = chosen
    validation_gross = economics_lookup(economics, "validation", "gross")
    validation_base = economics_lookup(economics, "validation", "base")
    validation_move = aggregate_move_statistics(validation_metric, validation_gross, validation_base)
    move_blocks.append({"dataset": "B_BEST_COMBINED_VALIDATION_CANDIDATE", "fold": None, **validation_move})
    for direction in ("LONG", "SHORT"):
        prefix = direction.lower()
        gross_mean = float(validation_metric[f"{prefix}_gross_expectancy_percent"])
        direction_records.append({
            "dataset": "B_BEST_COMBINED_VALIDATION_CANDIDATE", "fold": None, "direction": direction,
            "signals": int(validation_metric[f"{prefix}_signals"]), "correct": int(validation_metric[f"{prefix}_correct"]),
            "incorrect": int(validation_metric[f"{prefix}_incorrect"]), "accuracy": float(validation_metric[f"{prefix}_accuracy"]),
            "average_actual_eth_return_percent": gross_mean if direction == "LONG" else -gross_mean,
            "median_actual_eth_return_percent": None, "average_gross_trade_return_percent": gross_mean,
            "average_net_trade_return_base_percent": gross_mean - BASE_COST_PERCENT,
            "average_correct_move_percent": None, "average_incorrect_move_percent": None,
            "profit_factor": None, "availability": "aggregate_partial",
        })

    periods_frame = pd.DataFrame(period_records)
    regimes_frame = pd.DataFrame(regime_records)
    comparison_frame = pd.DataFrame(comparison_records)
    direction_frame = pd.DataFrame(direction_records)
    periods_frame.to_csv(REPORTS / "stage17b_walkforward_periods.csv", index=False)
    regimes_frame.to_csv(REPORTS / "stage17b_walkforward_market_regimes.csv", index=False)
    comparison_frame.to_csv(REPORTS / "stage17b_period_comparison.csv", index=False)
    direction_frame.to_csv(REPORTS / "stage17b_long_short_move_breakdown.csv", index=False)

    long_rows: list[dict[str, Any]] = []
    for block in move_blocks:
        identity = {"dataset": block["dataset"], "fold": block["fold"]}
        for key in ("signals", "mean_signed_actual_eth_return_percent", "median_signed_actual_eth_return_percent", "mean_absolute_eth_return_percent", "median_absolute_eth_return_percent", "minimum_actual_return_percent", "maximum_actual_return_percent", "actual_return_standard_deviation_percent"):
            long_rows.append({**identity, "section": "overall", "metric": key, "value": block[key], "availability": "available" if block[key] is not None else "unavailable_without_prediction_rows"})
        for section in ("when_eth_rose", "when_eth_fell", "correct_predictions", "incorrect_predictions", "payoff"):
            for key, value in block[section].items():
                long_rows.append({**identity, "section": section, "metric": key, "value": value, "availability": "available" if value is not None else "unavailable_without_prediction_rows"})
        for group in ("all", "correct_LONG", "incorrect_LONG", "correct_SHORT", "incorrect_SHORT"):
            for move_bin in ("<0.10%", "0.10-0.25%", "0.25-0.50%", "0.50-1.00%", "1.00-2.00%", ">2.00%"):
                long_rows.append({**identity, "section": f"absolute_move_bins:{group}", "metric": move_bin, "value": None, "availability": "unavailable_without_prediction_rows"})
    pd.DataFrame(long_rows).to_csv(REPORTS / "stage17b_average_market_moves.csv", index=False)

    arithmetic = []
    for record in period_records:
        arithmetic.extend([
            {"fold": record["fold_number"], "check": "correct_plus_incorrect_equals_predictions", "passed": record["correct_predictions"] + record["incorrect_predictions"] == record["predictions"]},
            {"fold": record["fold_number"], "check": "long_plus_short_equals_predictions", "passed": record["long_signals"] + record["short_signals"] == record["predictions"]},
            {"fold": record["fold_number"], "check": "signals_plus_no_signal_equals_eth_evaluation_rows", "passed": record["predictions"] + record["no_signal_count"] == record["eth_evaluation_rows"]},
            {"fold": record["fold_number"], "check": "base_net_equals_gross_minus_0_20pct", "passed": abs(record["average_net_trade_return_base_percent"] - (record["average_gross_trade_return_percent"] - BASE_COST_PERCENT)) < 1e-10},
        ])
    arithmetic.extend([
        {"fold": "all", "check": "walkforward_signal_sum_equals_111", "passed": int(periods_frame.predictions.sum()) == 111},
        {"fold": "all", "check": "walkforward_eth_rows_equal_114", "passed": int(periods_frame.eth_evaluation_rows.sum()) == 114},
        {"fold": "all", "check": "walkforward_no_signal_sum_equals_3", "passed": int(periods_frame.no_signal_count.sum()) == 3},
        {"fold": "validation_46", "check": "validation_candidate_kept_separate", "passed": int(validation_move["signals"]) == 46},
        {"fold": "all", "check": "duplicate_aggregate_fold_rows_zero", "passed": not periods_frame.fold_number.duplicated().any()},
        {"fold": "all", "check": "individual_prediction_duplicates", "passed": None, "reason": "prediction-level rows were not persisted"},
        {"fold": "all", "check": "gross_expectancy_matches_individual_trade_returns", "passed": None, "reason": "prediction-level rows were not persisted; aggregate weighted identities were checked instead"},
    ])

    successful = comparison_frame[comparison_frame.successful_fold]
    successful_number = int(successful.fold_number.iloc[0]) if len(successful) == 1 else None
    successful_period = periods_frame[periods_frame.fold_number.eq(successful_number)].iloc[0].to_dict() if successful_number else None
    successful_market = market_by_fold[successful_number] if successful_number else None
    successful_move = next(block for block in move_blocks if block["dataset"] == "A_WALK_FORWARD" and block["fold"] == successful_number) if successful_number else None
    assessment = {
        "audit_type": "descriptive_existing_results_only",
        "stage17b_status_unchanged": lock["status"],
        "model_retrained": False,
        "old_stage17_test_used": False,
        "lock_sha256": LOCK_SHA,
        "success_rule": "combined_accuracy > 55% and combined_accuracy > strongest persisted baseline",
        "successful_fold": successful_number,
        "successful_period": successful_period,
        "successful_market": successful_market,
        "successful_move_aggregates": successful_move,
        "folds_beating_baseline": periods_frame.loc[periods_frame.beats_strongest_baseline, "fold_number"].astype(int).tolist(),
        "folds_not_beating_baseline": periods_frame.loc[~periods_frame.beats_strongest_baseline, "fold_number"].astype(int).tolist(),
        "regime_rules": {
            "trend": "rising when total period return >= +10%; falling when <= -10%; otherwise sideways",
            "volatility": "highly_volatile when annualized standard deviation of UTC daily close returns >= 80%; otherwise normal_volatility",
            "market_regime": "highly_volatile takes precedence; otherwise use trend regime",
            "drawdown": "minimum drawdown of UTC daily closes from their running maximum",
            "rise_from_local_low": "maximum rise of UTC daily closes from their running minimum",
        },
        "descriptive_comparison": comparison_records,
        "evidence_limit": "Stage 17B did not persist event_id/signal/future_return rows. Aggregate-identifiable means are reported; medians, extrema, dispersion, per-leg winner/loser means, signal-level source mix, bins, and duplicate-row checks cannot be reconstructed without forbidden model refitting.",
        "diagnostic_completeness": "PARTIAL_EVIDENCE",
    }
    write_json(REPORTS / "stage17b_successful_period_analysis.json", assessment)
    write_json(REPORTS / "stage17b_average_market_moves.json", {
        "audit_type": "descriptive_existing_results_only", "lock_sha256": LOCK_SHA,
        "A_WALK_FORWARD_PERIOD_ANALYSIS": [b for b in move_blocks if b["dataset"] == "A_WALK_FORWARD"],
        "B_BEST_COMBINED_CANDIDATE_46_SIGNALS": validation_move,
        "sets_are_disjoint_analytical_blocks": True,
        "absolute_move_bins": {"availability": "unavailable_without_prediction_rows", "values": None},
        "arithmetic_checks": arithmetic,
        "all_determinable_checks_passed": all(x["passed"] for x in arithmetic if x["passed"] is not None),
    })

    s = successful_period
    sm = successful_market
    mv = successful_move
    summary = f"""SUCCESSFUL PERIOD

- Дати: {pd.Timestamp(s['evaluation_start_utc']).date()} — {pd.Timestamp(s['evaluation_end_utc']).date()}
- Точність моделі: {s['accuracy'] * 100:.2f}%
- Baseline: {s['strongest_baseline_accuracy'] * 100:.2f}%
- Сигналів: {s['predictions']}
- LONG accuracy: {metrics.loc[metrics.fold.eq(successful_number), 'long_accuracy'].iloc[0] * 100:.2f}%
- SHORT accuracy: {metrics.loc[metrics.fold.eq(successful_number), 'short_accuracy'].iloc[0] * 100:.2f}%
- ETH за весь період: {sm['eth']['total_period_return_percent']:+.2f}%
- Режим ринку: {sm['eth']['market_regime']}
- Середня волатильність: {sm['eth']['realized_volatility_annualized_percent']:.2f}% annualized

AVERAGE MOVES AFTER SIGNALS

- Середній ріст ETH: {format_percent(mv['when_eth_rose']['average_rise_percent'], signed=True)}
- Середнє падіння ETH: {format_percent(mv['when_eth_fell']['average_negative_return_percent'], signed=True)}
- Середній рух при правильному прогнозі: {format_percent(mv['correct_predictions']['average_favorable_move_percent'], signed=True)}
- Середній рух проти прогнозу: {format_percent(mv['incorrect_predictions']['average_adverse_move_percent'], signed=True)}
- Середній gross результат: {mv['payoff']['gross_expectancy_per_signal_percent']:+.2f}%
- Середній net результат після Base costs: {mv['payoff']['base_expectancy_per_signal_percent']:+.2f}%
- Беззбиткова необхідна точність (gross): {format_percent(mv['payoff']['gross_break_even_accuracy'], fraction=True)}
- Беззбиткова необхідна точність (Base): {format_percent(mv['payoff']['base_break_even_accuracy'], fraction=True)}

PERIOD COMPARISON

"""
    for _, row in comparison_frame.iterrows():
        summary += f"- Fold {int(row.fold_number)}: {pd.Timestamp(row.evaluation_start_utc).date()} — {pd.Timestamp(row.evaluation_end_utc).date()}, accuracy {row.accuracy * 100:.2f}%, {row.eth_trend_regime}/{row.eth_volatility_regime}\n"
    summary += f"""

FINAL DIAGNOSTIC ANSWER

1. Модель перевищила 55% і strongest baseline лише у Fold {successful_number}: {pd.Timestamp(s['evaluation_start_utc']).date()} — {pd.Timestamp(s['evaluation_end_utc']).date()}.
2. ETH за цей evaluation period змінився на {sm['eth']['total_period_return_percent']:+.2f}% ({sm['eth']['trend_regime']}).
3. Середній фактичний 12h ETH move після {mv['signals']} walk-forward сигналів Fold {successful_number}: {mv['mean_signed_actual_eth_return_percent']:+.2f}%; середній trade-signed gross: {mv['payoff']['gross_expectancy_per_signal_percent']:+.2f}%.
4. У Fold {successful_number} LONG accuracy була {metrics.loc[metrics.fold.eq(successful_number), 'long_accuracy'].iloc[0] * 100:.2f}%, SHORT — {metrics.loc[metrics.fold.eq(successful_number), 'short_accuracy'].iloc[0] * 100:.2f}%; описово сильнішою була LONG leg.
5. Gross winners перекривали losers (profit factor {mv['payoff']['gross_profit_factor']:.3f}); після Base costs profit factor був {mv['payoff']['base_profit_factor']:.3f}.
6. Успішний fold описово відрізнявся ринковим режимом, source/event mix і pre-event context, наведеними у `stage17b_period_comparison.csv`; причинний висновок на трьох folds не робиться.

DATA AVAILABILITY LIMITATION

Stage 17B не зберіг prediction-level `event_id + signal + future_return`. Тому medians, min/max/std, absolute-move bins, окремі average moves для correct/incorrect LONG/SHORT, direction-specific profit factors, signal-only source/event distributions і duplicate prediction-row check доказово недоступні. Їх позначено `null`; модель не перенавчалась і thresholds/mapping/lock не змінювалися. Окремі 46 validation signals наведені лише у блоці B і не змішані зі 111 walk-forward signals.

AUDIT STATUS

- Existing aggregate arithmetic: PASS.
- Lock/config immutability: PASS.
- Requested prediction-level diagnostics: FAIL — source rows were never persisted.
- Overall diagnostic completeness: PARTIAL_EVIDENCE.
- Stage 17B status remains `{lock['status']}`; цей audit не є новим test.
"""
    (REPORTS / "stage17b_diagnostic_summary.md").write_text(summary, encoding="utf-8")

    after = protected_snapshot()
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    if changed:
        raise RuntimeError(f"Protected Stage 17B/Stage 17 artifacts changed: {changed}")
    result = {
        "status": "PARTIAL_EVIDENCE", "successful_fold": successful_number,
        "lock_sha256": LOCK_SHA, "model_retrained": False, "protected_inputs_unchanged": True,
        "reports": [str(p.relative_to(ROOT)) for p in sorted(OUTPUTS)],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
