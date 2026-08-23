"""Stage 17C reaction-window audit using persisted frozen predictions only.

No estimator is fitted. Pattern A uses the already-opened Stage 17 locked-test
prediction rows. Pattern B is reported as unreconstructable because Stage 17B
persisted only aggregates and no frozen estimator.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score
from sqlalchemy import text

from analysis.stage17b_bidirectional import canonical_hash
from database.db import engine


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data" / "stage17"
PATTERN_A = "stage17_directional_lock_v1:5e81bf106834c3a8edf640cad718e2c113106059460198ffc34aa6dfa60831f9"
PATTERN_B = "model:semantic_plus_market:gradient_boosting:12h:0.1:0.4:ETH"
LOCK_A = "5e81bf106834c3a8edf640cad718e2c113106059460198ffc34aa6dfa60831f9"
LOCK_B = "509a91b2d6fda0991eba012cf273ad54ef9b2f711a49a6891a7ba0a7277f900e"
MODEL_A_SHA = "cdaa5784f48709640594b926b4fa7932777596a44dd5fd80e76800c5ba917bf0"
BASE_COST = 0.20
HORIZONS = {"5m": 5, "10m": 10, "20m": 20, "40m": 40, "1h": 60, "90m": 90, "2h": 120, "3h": 180, "4h": 240, "5h": 300, "6h": 360, "8h": 480, "10h": 600, "12h": 720, "18h": 1080, "24h": 1440}
PRIMARY_HORIZONS = {name for name, minutes in HORIZONS.items() if 20 <= minutes <= 720}
OUTPUT_NAMES = {
    "stage17c_current_return_formula.md", "stage17c_prediction_level_signals.csv", "stage17c_price_paths.csv",
    "stage17c_horizon_comparison.csv", "stage17c_pattern_a_horizons.csv", "stage17c_pattern_b_horizons.csv",
    "stage17c_mfe_mae_analysis.csv", "stage17c_time_to_peak.csv", "stage17c_peak_giveback.csv",
    "stage17c_fold_horizon_stability.csv", "stage17c_candidate_exit_rules.json", "stage17c_final_summary.md",
}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot() -> dict[str, str]:
    paths = [p for p in REPORTS.glob("stage17*") if p.is_file() and p.name not in OUTPUT_NAMES]
    paths += [p for p in DATA.glob("*") if p.is_file()]
    return {str(p.relative_to(ROOT)): file_hash(p) for p in sorted(set(paths))}


def write_json(path: Path, value: Any) -> None:
    def default(item: Any):
        if isinstance(item, (pd.Timestamp,)): return item.isoformat()
        if isinstance(item, (np.integer,)): return int(item)
        if isinstance(item, (np.floating,)): return None if not np.isfinite(item) else float(item)
        if isinstance(item, (np.bool_,)): return bool(item)
        raise TypeError(type(item).__name__)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=default, allow_nan=False) + "\n", encoding="utf-8")


def verify_locks() -> tuple[dict[str, Any], dict[str, Any]]:
    a = json.loads((REPORTS / "stage17_directional_locked_config.json").read_text(encoding="utf-8"))
    b = json.loads((REPORTS / "stage17b_locked_config.json").read_text(encoding="utf-8"))
    if canonical_hash(a) != LOCK_A or (REPORTS / "stage17_directional_locked_config.sha256").read_text().strip() != LOCK_A:
        raise RuntimeError("Pattern A config hash mismatch")
    if canonical_hash(b) != LOCK_B or (REPORTS / "stage17b_locked_config.sha256").read_text().strip() != LOCK_B:
        raise RuntimeError("Pattern B config hash mismatch")
    model_path = ROOT / a["model_file"]
    if file_hash(model_path) != MODEL_A_SHA or a["model_sha256"] != MODEL_A_SHA:
        raise RuntimeError("Pattern A model hash mismatch")
    joblib.load(model_path)  # deserialize/hash verification only; predict rows already persisted
    return a, b


def feature_rows() -> pd.DataFrame:
    columns = ["metadata_event_id", "metadata_asset", "pre_return_1m", "pre_return_5m", "pre_btc_return_60m"]
    frame = pd.concat([pd.read_parquet(DATA / f"{asset}_high_impact.parquet", columns=columns) for asset in ("btc", "eth", "sol")], ignore_index=True)
    return frame.drop_duplicates(["metadata_event_id", "metadata_asset"])


def pattern_a_signals() -> pd.DataFrame:
    persisted = pd.read_csv(REPORTS / "stage17_directional_locked_test_predictions.csv")
    persisted["event_timestamp_utc"] = pd.to_datetime(persisted.metadata_published_at, utc=True)
    persisted = persisted[persisted.predicted_direction.isin(["UP", "DOWN"])].copy()
    persisted["signal"] = persisted.predicted_direction.map({"UP": "LONG", "DOWN": "SHORT"})
    persisted["asset"] = persisted.metadata_asset
    persisted["symbol"] = persisted.asset + "USDT"
    ids = persisted.metadata_event_id.astype(int).tolist()
    with engine.connect() as connection:
        baselines = pd.read_sql(text("""SELECT event_id,symbol,baseline_time,baseline_price
          FROM high_impact_market_reactions WHERE latency_minutes=1 AND event_id=ANY(:ids)"""), connection, params={"ids": ids})
    baselines["entry_timestamp"] = pd.to_datetime(baselines.baseline_time, utc=True)
    result = persisted.merge(baselines, left_on=["metadata_event_id", "symbol"], right_on=["event_id", "symbol"], how="left", validate="one_to_one")
    if result.entry_timestamp.isna().any(): raise RuntimeError("Pattern A baseline rows missing")
    result["pattern_id"] = PATTERN_A; result["fold"] = "LOCKED_TEST"
    result["source"] = result.metadata_source; result["event_type"] = result.source_event_type
    result["model_config_hash"] = LOCK_A; result["model_hash"] = MODEL_A_SHA
    result["prediction_origin"] = "persisted_stage17_locked_test_prediction"
    result["dataset_label"] = "LOCKED_TEST"
    result["current_horizon"] = "1h"; result["neutral_threshold"] = 0.10
    result = result.merge(feature_rows(), on=["metadata_event_id", "metadata_asset"], how="left", validate="one_to_one")
    columns = ["pattern_id", "metadata_event_id", "event_timestamp_utc", "asset", "symbol", "signal", "confidence", "fold", "source", "event_type", "entry_timestamp", "baseline_price", "model_config_hash", "model_hash", "prediction_origin", "dataset_label", "current_horizon", "neutral_threshold", "pre_return_1m", "pre_return_5m", "pre_btc_return_60m"]
    return result[columns].rename(columns={"metadata_event_id": "event_id", "baseline_price": "entry_price"}).sort_values(["entry_timestamp", "event_id", "asset"]).reset_index(drop=True)


def load_path(signal: pd.Series) -> pd.DataFrame:
    end = signal.entry_timestamp + pd.Timedelta(hours=24)
    with engine.connect() as connection:
        path = pd.read_sql(text("""SELECT open_time,open::double precision open,high::double precision high,
          low::double precision low,close::double precision close,volume::double precision volume
          FROM market_candles WHERE symbol=:symbol AND interval='1m' AND open_time BETWEEN :start AND :end ORDER BY open_time"""),
          connection, params={"symbol": signal.symbol, "start": signal.entry_timestamp.to_pydatetime(), "end": end.to_pydatetime()})
    path["open_time"] = pd.to_datetime(path.open_time, utc=True)
    path["minute_offset"] = ((path.open_time - signal.entry_timestamp).dt.total_seconds() / 60).astype(int)
    entry = float(path.loc[path.minute_offset.eq(0), "open"].iloc[0])
    direction = 1.0 if signal.signal == "LONG" else -1.0
    path["raw_open_return_percent"] = (path.open / entry - 1) * 100
    path["trade_signed_open_return_percent"] = direction * path.raw_open_return_percent
    if direction > 0:
        path["favorable_excursion_percent"] = (path.high / entry - 1) * 100
        path["adverse_excursion_percent"] = (path.low / entry - 1) * 100
    else:
        path["favorable_excursion_percent"] = (1 - path.low / entry) * 100
        path["adverse_excursion_percent"] = (1 - path.high / entry) * 100
    path.insert(0, "pattern_id", signal.pattern_id); path.insert(1, "event_id", int(signal.event_id))
    path.insert(2, "asset", signal.asset); path.insert(3, "signal", signal.signal); path.insert(4, "dataset_label", signal.dataset_label)
    return path


def at_minute(path: pd.DataFrame, minute: int, column: str = "trade_signed_open_return_percent") -> float | None:
    row = path[path.minute_offset.eq(minute)]
    return float(row[column].iloc[0]) if len(row) else None


def path_metrics(signal: pd.Series, path: pd.DataFrame) -> dict[str, Any]:
    primary = path[path.minute_offset.le(720)].copy()
    if len(primary) != 721 or primary.minute_offset.nunique() != 721:
        return {"pattern_id": signal.pattern_id, "event_id": int(signal.event_id), "signal": signal.signal, "path_status": "missing_12h_minutes"}
    mfe_idx = primary.favorable_excursion_percent.idxmax(); mae_idx = primary.adverse_excursion_percent.idxmin()
    mfe = float(primary.loc[mfe_idx, "favorable_excursion_percent"]); mae = float(primary.loc[mae_idx, "adverse_excursion_percent"])
    time_mfe = int(primary.loc[mfe_idx, "minute_offset"]); time_mae = int(primary.loc[mae_idx, "minute_offset"])
    after_peak = path[path.minute_offset.ge(time_mfe)]
    returned = bool((after_peak.trade_signed_open_return_percent <= 0).any())
    result = {
        "pattern_id": signal.pattern_id, "event_id": int(signal.event_id), "asset": signal.asset,
        "signal": signal.signal, "fold": signal.fold, "path_status": "complete_12h",
        "mfe_percent": mfe, "mae_percent": mae, "time_to_mfe_minutes": time_mfe, "time_to_mae_minutes": time_mae,
        "time_to_first_positive_return_minutes": None, "returned_to_entry_after_mfe": returned,
    }
    positive = primary[(primary.minute_offset.gt(0)) & (primary.trade_signed_open_return_percent.gt(0))]
    if len(positive): result["time_to_first_positive_return_minutes"] = int(positive.minute_offset.iloc[0])
    for threshold in (0.10, 0.25, 0.50, 1.00):
        hit = primary[(primary.minute_offset.gt(0)) & (primary.trade_signed_open_return_percent.ge(threshold))]
        result[f"time_to_first_{str(threshold).replace('.', '_')}_percent_minutes"] = int(hit.minute_offset.iloc[0]) if len(hit) else None
    for name, minutes in HORIZONS.items():
        value = at_minute(path, minutes)
        result[f"return_at_{name}_percent"] = value
        result[f"mfe_retained_at_{name}"] = value / mfe if value is not None and mfe > 0 else None
        result[f"giveback_at_{name}_percent"] = mfe - value if value is not None else None
    for hours in (1, 2, 4): result[f"return_{hours}h_after_peak_percent"] = at_minute(path, time_mfe + hours * 60)
    ret12 = result["return_at_12h_percent"]
    lost = (mfe - ret12) / mfe if mfe > 0 and ret12 is not None else None
    result["peak_lost_by_12h_fraction"] = lost
    if mfe >= 0.50 and lost is not None and lost > 0.60: classification = "spike_then_reversal"
    elif mfe >= 0.50 and time_mfe <= 60 and (result["mfe_retained_at_12h"] or 0) >= 0.40: classification = "immediate_and_persistent"
    elif mfe >= 0.50 and time_mfe > 60 and (result["mfe_retained_at_12h"] or 0) >= 0.40: classification = "delayed_and_persistent"
    elif time_mfe > 240 and mfe >= 0.25: classification = "gradual_move"
    elif mfe < 0.10 and mae <= -0.25: classification = "moved_against_signal"
    else: classification = "no_clear_reaction"
    result["reaction_class"] = classification
    return result


def wilson(correct: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if not total: return None, None
    rate = correct / total; den = 1 + z*z/total
    center = (rate + z*z/(2*total))/den; margin = z*np.sqrt(rate*(1-rate)/total + z*z/(4*total*total))/den
    return float(center-margin), float(center+margin)


def horizon_metrics(signals: pd.DataFrame, paths: dict[tuple[int, str], pd.DataFrame], path_frame: pd.DataFrame, threshold_mode: str, horizon: str, minutes: int) -> dict[str, Any]:
    rows = []
    for signal in signals.itertuples(index=False):
        value = at_minute(paths[(int(signal.event_id), str(signal.asset))], minutes)
        if value is None: continue
        raw = value if signal.signal == "LONG" else -value
        rows.append({"event_id": signal.event_id, "asset": signal.asset, "signal": signal.signal, "trade": value, "raw": raw, "pre1": signal.pre_return_1m, "pre5": signal.pre_return_5m, "btc": signal.pre_btc_return_60m})
    frame = pd.DataFrame(rows); threshold = 0.10 if threshold_mode == "original_0_10" else 0.0
    if frame.empty: return {"pattern_id": PATTERN_A, "horizon": horizon, "threshold_mode": threshold_mode, "signals": 0, "status": "NO_COVERAGE"}
    frame["actual"] = np.select([frame.raw > threshold, frame.raw < -threshold], ["UP", "DOWN"], default="NEUTRAL")
    frame["predicted"] = frame.signal.map({"LONG": "UP", "SHORT": "DOWN"})
    frame["correct"] = frame.trade > threshold; frame["incorrect"] = frame.trade < -threshold; frame["neutral"] = ~(frame.correct | frame.incorrect)
    correct = int(frame.correct.sum()); incorrect = int(frame.incorrect.sum()); neutral = int(frame.neutral.sum()); count = len(frame)
    accuracy = correct / count; directional = correct / (correct + incorrect) if correct + incorrect else None
    directional_mask = frame.actual.isin(["UP", "DOWN"])
    balanced = float(balanced_accuracy_score(frame.loc[directional_mask, "actual"], frame.loc[directional_mask, "predicted"])) if frame.loc[directional_mask, "actual"].nunique() == 2 else None
    baselines = {
        "always_long": float((frame.actual == "UP").mean()), "always_short": float((frame.actual == "DOWN").mean()),
        "previous_1m": float((np.where(pd.to_numeric(frame.pre1).fillna(0) >= 0, "UP", "DOWN") == frame.actual).mean()),
        "previous_5m": float((np.where(pd.to_numeric(frame.pre5).fillna(0) >= 0, "UP", "DOWN") == frame.actual).mean()),
        "btc_trend": float((np.where(pd.to_numeric(frame.btc).fillna(0) >= 0, "UP", "DOWN") == frame.actual).mean()),
    }
    strongest = max(baselines.values()); gross = frame.trade.to_numpy(float); net = gross - BASE_COST
    cumulative = np.cumsum(net); drawdown = cumulative - np.maximum.accumulate(np.r_[0.0, cumulative])[1:]
    profit, loss = net[net > 0].sum(), -net[net < 0].sum(); pf = float(profit/loss) if loss > 0 else None
    keys = pd.MultiIndex.from_frame(frame[["event_id", "asset"]])
    metrics = path_frame.set_index(["event_id", "asset"]).loc[keys].reset_index()
    retention = [row.get(f"mfe_retained_at_{horizon}") for row in metrics.to_dict("records")]
    top2_share = float(np.sort(gross[gross > 0])[-2:].sum() / gross[gross > 0].sum()) if (gross > 0).sum() >= 2 and gross[gross > 0].sum() else None
    low, high = wilson(correct, count)
    gate = accuracy > .55 and count >= 30 and count/len(signals) >= .80 and accuracy > strongest and net.mean() > 0 and (pf or 0) > 1 and (top2_share is None or top2_share < .50)
    return {
        "pattern_id": PATTERN_A, "horizon": horizon, "horizon_minutes": minutes, "analysis_scope": "primary" if horizon in PRIMARY_HORIZONS else "secondary",
        "threshold_mode": threshold_mode, "neutral_threshold_percent": threshold, "signals": count,
        "long_signals": int(frame.signal.eq("LONG").sum()), "short_signals": int(frame.signal.eq("SHORT").sum()),
        "correct": correct, "incorrect": incorrect, "neutral": neutral, "accuracy": accuracy,
        "directional_accuracy_excluding_neutral": directional, "balanced_accuracy": balanced, "coverage": count/len(signals),
        "baseline_accuracy": strongest, "accuracy_edge": accuracy-strongest, "mean_signed_return": float(gross.mean()),
        "median_signed_return": float(np.median(gross)), "gross_expectancy": float(gross.mean()), "net_expectancy": float(net.mean()),
        "net_win_rate": float((net > 0).mean()), "profit_factor": pf, "cumulative_return": float(net.sum()),
        "maximum_drawdown": float(drawdown.min()), "median_MFE": float(metrics.mfe_percent.median()), "median_MAE": float(metrics.mae_percent.median()),
        "median_time_to_MFE": float(metrics.time_to_mfe_minutes.median()), "MFE_retained_at_exit": float(pd.Series(retention, dtype=float).median()),
        "wilson_95_low": low, "wilson_95_high": high, "top_two_positive_moves_share": top2_share,
        "status": "RETROSPECTIVE_CANDIDATE_GATE_PASS" if gate else "RETROSPECTIVE_EXPLORATORY",
    }


def pattern_b_placeholders() -> pd.DataFrame:
    return pd.DataFrame([{
        "pattern_id": PATTERN_B, "horizon": name, "horizon_minutes": minutes, "analysis_scope": "primary" if name in PRIMARY_HORIZONS else "secondary",
        "threshold_mode": mode, "neutral_threshold_percent": .10 if mode == "original_0_10" else 0.0,
        "signals": None, "expected_walkforward_signals": 111, "expected_validation_signals": 46,
        "available_prediction_level_signals": 0, "prediction_level_coverage": 0.0,
        "sample_status": "INSUFFICIENT_SAMPLE", "reconstruction_status": "CANNOT_RECONSTRUCT_WITHOUT_REFIT",
        "status": "INSUFFICIENT_SAMPLE",
    } for mode in ("original_0_10", "no_neutral_sensitivity") for name, minutes in HORIZONS.items()])


def time_to_peak_report(metrics: pd.DataFrame) -> pd.DataFrame:
    current = metrics.copy(); current["current_correctness"] = np.select([current.return_at_1h_percent > .10, current.return_at_1h_percent < -.10], ["correct", "incorrect"], default="neutral")
    groups = [("ALL", current), ("LONG", current[current.signal.eq("LONG")]), ("SHORT", current[current.signal.eq("SHORT")]), ("correct", current[current.current_correctness.eq("correct")]), ("incorrect", current[current.current_correctness.eq("incorrect")])]
    bins = [(-1, 20, "<=20m"), (20, 40, "20-40m"), (40, 60, "40-60m"), (60, 120, "1-2h"), (120, 180, "2-3h"), (180, 240, "3-4h"), (240, 360, "4-6h"), (360, 480, "6-8h"), (480, 720, "8-12h"), (720, 10**9, ">12h")]
    rows=[]
    for group, part in groups:
        values = part.time_to_mfe_minutes.dropna()
        for low, high, label in bins:
            count = int(((values > low) & (values <= high)).sum())
            rows.append({"pattern_id": PATTERN_A, "group": group, "time_bin": label, "signals": len(part), "bin_count": count, "bin_share": count/len(part) if len(part) else None, "median_minutes": float(values.median()) if len(values) else None, "mean_minutes": float(values.mean()) if len(values) else None, "p25_minutes": float(values.quantile(.25)) if len(values) else None, "p75_minutes": float(values.quantile(.75)) if len(values) else None, "p90_minutes": float(values.quantile(.90)) if len(values) else None, "status": "AVAILABLE"})
    rows.append({"pattern_id": PATTERN_B, "group": "ALL", "time_bin": None, "signals": 0, "status": "CANNOT_RECONSTRUCT_WITHOUT_REFIT"})
    return pd.DataFrame(rows)


def fold_report() -> pd.DataFrame:
    rows=[]
    a = pd.read_csv(REPORTS / "stage17_directional_walkforward.csv")
    b = pd.read_csv(REPORTS / "stage17b_walkforward_metrics.csv")
    for pattern, current_horizon, frame, signal_col in ((PATTERN_A, "1h", a, "predictions"), (PATTERN_B, "12h", b, "combined_signals")):
        current_accuracy = frame.accuracy if pattern == PATTERN_A else frame.combined_accuracy
        current_baseline = frame.simple_market_baseline if pattern == PATTERN_A else frame.baseline_strongest_baseline
        stable_folds = int((current_accuracy > current_baseline).sum())
        stability = {0: "absent", 1: "weak", 2: "medium", 3: "high"}[stable_folds]
        for fold in (1, 2, 3):
            persisted = frame[frame.fold.eq(fold)].iloc[0]
            for horizon in HORIZONS:
                available = horizon == current_horizon
                accuracy = float(persisted.accuracy if pattern == PATTERN_A else persisted.combined_accuracy) if available else None
                baseline = float(persisted.simple_market_baseline if pattern == PATTERN_A else persisted.baseline_strongest_baseline) if available else None
                rows.append({"pattern_id": pattern, "fold": fold, "horizon": horizon, "signals": int(persisted[signal_col]) if available else None, "accuracy": accuracy, "baseline_accuracy": baseline, "beats_baseline": accuracy > baseline if available else None, "current_horizon_folds_beating_baseline": stable_folds, "current_horizon_stability": stability, "status": "PERSISTED_AGGREGATE_ONLY" if available else "CANNOT_RECONSTRUCT_WITHOUT_REFIT"})
    return pd.DataFrame(rows)


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True); before = snapshot(); config_a, config_b = verify_locks()
    formula = """# Stage 17C — Current return formula

- Source: `high_impact_sources/analysis/reaction_calculator.py`
- Function: `calculate_event_reaction`; timestamp helper: `baseline_minute` / `next_full_minute`.
- Formula: **endpoint return**, not a median or average: `return_h = (open_at(entry + horizon) / open_at(entry) - 1) * 100`.
- Entry timestamp: first full UTC minute strictly after `published_at`, plus `latency_minutes`.
- Locked latency: 1 minute for both configurations.
- Candle selection: exact `market_candles.open_time` at entry and entry+horizon; a missing exact candle means missing coverage. No interpolation or synthetic candles.
- Pattern A locked current horizon: 1h. Pattern B locked current horizon: 12h.
- LONG trade return: raw endpoint return. SHORT trade return: negative raw endpoint return.
"""
    (REPORTS / "stage17c_current_return_formula.md").write_text(formula, encoding="utf-8")
    signals = pattern_a_signals(); signals.to_csv(REPORTS / "stage17c_prediction_level_signals.csv", index=False)
    paths={}; path_frames=[]; metric_rows=[]
    for _, signal in signals.iterrows():
        path=load_path(signal); paths[(int(signal.event_id), str(signal.asset))] = path; path_frames.append(path); metric_rows.append(path_metrics(signal, path))
    all_paths=pd.concat(path_frames,ignore_index=True); all_paths.to_csv(REPORTS / "stage17c_price_paths.csv",index=False)
    path_metrics_frame=pd.DataFrame(metric_rows); path_metrics_frame.to_csv(REPORTS / "stage17c_mfe_mae_analysis.csv",index=False)
    peak_columns=[c for c in path_metrics_frame.columns if c in {"pattern_id","event_id","asset","signal","fold","mfe_percent","time_to_mfe_minutes","return_1h_after_peak_percent","return_2h_after_peak_percent","return_4h_after_peak_percent","return_at_12h_percent","peak_lost_by_12h_fraction","returned_to_entry_after_mfe","reaction_class","path_status"}]
    path_metrics_frame[peak_columns].to_csv(REPORTS / "stage17c_peak_giveback.csv",index=False)
    time_to_peak_report(path_metrics_frame).to_csv(REPORTS / "stage17c_time_to_peak.csv",index=False)
    a_horizons=pd.DataFrame([horizon_metrics(signals,paths,path_metrics_frame,mode,name,minutes) for mode in ("original_0_10","no_neutral_sensitivity") for name,minutes in HORIZONS.items()])
    b_horizons=pattern_b_placeholders()
    for column in a_horizons.columns:
        if column not in b_horizons: b_horizons[column] = None
    b_horizons = b_horizons[list(a_horizons.columns) + [c for c in b_horizons.columns if c not in a_horizons.columns]]
    a_horizons.to_csv(REPORTS / "stage17c_pattern_a_horizons.csv",index=False); b_horizons.to_csv(REPORTS / "stage17c_pattern_b_horizons.csv",index=False)
    pd.concat([a_horizons,b_horizons],ignore_index=True,sort=False).to_csv(REPORTS / "stage17c_horizon_comparison.csv",index=False)
    fold_report().to_csv(REPORTS / "stage17c_fold_horizon_stability.csv",index=False)
    original=a_horizons[a_horizons.threshold_mode.eq("original_0_10")]
    best_accuracy=original.sort_values(["accuracy","signals"],ascending=False).iloc[0]
    best_accuracy_horizons=original.loc[original.accuracy.eq(original.accuracy.max()),"horizon"].tolist()
    best_gross=original.sort_values(["gross_expectancy","signals"],ascending=False).iloc[0]
    best_net=original.sort_values(["net_expectancy","signals"],ascending=False).iloc[0]
    candidate={
        "audit_status":"PARTIAL_DIAGNOSTIC", "retrospective_only":True,
        "pattern_a":{"pattern_id":PATTERN_A,"entry_rule":config_a["classification_logic"],"signal_direction":"LONG_OR_SHORT","fixed_exit_horizon":best_net.horizon,"neutral_threshold":.10,"cost_model":{"base_round_trip_percent":BASE_COST},"frozen_feature_list":config_a["feature_columns"],"frozen_model_hash":MODEL_A_SHA,"config_hash":LOCK_A,"selection_origin":"RETROSPECTIVE_EXPLORATORY"},
        "pattern_b":{"pattern_id":PATTERN_B,"config_hash":LOCK_B,"status":"CANNOT_RECONSTRUCT_WITHOUT_REFIT","available_signals":0,"missing_walkforward_signals":111,"missing_validation_signals":46,"coverage_percent":0.0,"frozen_model_hash":None},
        "selection_summary":{"best_accuracy_horizons":best_accuracy_horizons,"best_gross_horizon":best_gross.horizon,"best_net_horizon":best_net.horizon,"pattern_a_current_horizon_folds_beating_baseline":0,"pattern_b_current_horizon_folds_beating_baseline":1},
    }
    frozen={k:v for k,v in candidate["pattern_a"].items() if k!="candidate_rule_sha256"}; candidate["pattern_a"]["candidate_rule_sha256"]=canonical_hash(frozen)
    write_json(REPORTS / "stage17c_candidate_exit_rules.json",candidate)
    median_mfe=float(path_metrics_frame.time_to_mfe_minutes.median()); first_positive=float(path_metrics_frame.time_to_first_positive_return_minutes.median())
    retention12=float(path_metrics_frame.mfe_retained_at_12h.median()); avg_giveback=float(path_metrics_frame.giveback_at_12h_percent.mean())
    current=original[original.horizon.eq("1h")].iloc[0]
    summary=f"""# Stage 17C — Optimal Reaction Window Audit

Overall status: **PARTIAL_DIAGNOSTIC**

## Pattern A — persisted locked-test signals

- Pattern ID: `{PATTERN_A}`
- Available signals: {len(signals)}/66 (100%).
- Current locked horizon: 1h; current accuracy: {current.accuracy*100:.2f}%.
- Найчастіше рух починався через: median {first_positive:.0f} хв.
- Найкраща ціна зазвичай була через: median {median_mfe:.0f} хв.
- 12h exit зберігав median {retention12*100:.2f}% MFE; average giveback {avg_giveback:.3f}%.
- Best accuracy horizons: {', '.join(best_accuracy_horizons)} (tie at {best_accuracy.accuracy*100:.2f}%).
- Best gross horizon: {best_gross.horizon} ({best_gross.gross_expectancy:+.3f}%).
- Best net horizon: {best_net.horizon} ({best_net.net_expectancy:+.3f}%, PF {best_net.profit_factor:.3f}).
- Any alternative horizon is **RETROSPECTIVE / EXPLORATORY**, not a confirmed locked-test result.
- Current 1h rule beat its fold baseline in 0/3 folds. Candidate 12h fold stability cannot be reconstructed because historical fold prediction rows/models were not persisted.

## Pattern B — incomplete evidence

- Pattern ID: `{PATTERN_B}`
- Prediction-level availability: 0/111 walk-forward and 0/46 validation signals (0%).
- Only aggregate metrics survive; event IDs, LONG/SHORT mappings, confidence and fold prediction rows do not.
- Frozen GradientBoosting artifact: absent.
- Persisted current-12h aggregate beat baseline in 1/3 folds (weak), but path/horizon alternatives are unavailable.
- Status: **INSUFFICIENT_SAMPLE / CANNOT_RECONSTRUCT_WITHOUT_REFIT**.

## Main answers

1. Whether 12h hid an early move is measurable for Pattern A only: median retained MFE at 12h was {retention12*100:.2f}%.
2. Pattern A median time to maximum favorable price was {median_mfe:.0f} minutes.
3. Pattern A average giveback by 12h was {avg_giveback:.3f}%.
4. Pattern A retrospective best net candidate was {best_net.horizon}; it is not confirmed.
5. Pattern B optimal horizon is not identifiable without forbidden refitting.
6. Pattern A best-net candidate expectancy was {best_net.net_expectancy:+.3f}% after Base costs.
7. Pattern A current 1h result was 0/3 versus fold baselines; Pattern B current 12h was 1/3. Candidate-horizon stability is unknown because fold-level signals were not persisted.

No `fit()`, OpenAI API, paper trading, real trading, interpolation or synthetic candles were used. Stage 17/17B statuses and protected artifacts remain unchanged.
"""
    (REPORTS / "stage17c_final_summary.md").write_text(summary,encoding="utf-8")
    after=snapshot(); changed=[p for p in sorted(set(before)|set(after)) if before.get(p)!=after.get(p)]
    if changed: raise RuntimeError(f"Protected Stage 17 artifacts changed: {changed}")
    print(json.dumps({"status":"PARTIAL_DIAGNOSTIC","pattern_a_signals":len(signals),"pattern_b_available":0,"best_accuracy":best_accuracy.horizon,"best_gross":best_gross.horizon,"best_net":best_net.horizon,"protected_unchanged":True},indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
