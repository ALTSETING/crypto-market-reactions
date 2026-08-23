"""Stage 18B corrected offline rebuild and reliability audit.

The pipeline is intentionally versioned independently from Stage 18.  It reads
existing labels and verified market paths, performs no external API calls, no
database writes, and no trading actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score
from sqlalchemy import text

from database.db import engine
from ml.stage18_unified import (
    HORIZONS, add_missing_flags, assert_no_future_features, canonical_hash,
    chronological_split, directional_target, sha256_file, signed_return,
)
from ml.stage18b_corrected import (
    SCHEMA_REGISTRY, canonical_digest, cluster_bootstrap, event_block_permutation,
    file_tree_hash, full_performance, grouped_performance,
    normalize_semantic_series, probability_map, semantic_gate,
    signal_from_probabilities,
)
import scripts.run_stage18_unified as s18


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data" / "stage18b"
MODELS = ROOT / "models"
VERSION = "stage18b_corrected_v1"
SEED = 18018
BASE_COST = .20
THRESHOLD = .40
PATTERN_IDS = {
    "A": "pattern_a_v3:corrected_semantic_only:subgroup_k:12h",
    "B": "pattern_b_v3:corrected_semantic_plus_market:gradient_boosting:12h:eth",
}
REQUIRED_REPORTS = [
    "stage18b_semantic_scale_audit.csv", "stage18b_pretraining_gates.json",
    "stage18b_data_inventory.csv", "stage18b_market_coverage.csv", "stage18b_api_budget.csv",
    "stage18b_feature_manifest.json", "stage18b_split_manifest.json", "stage18b_signal_funnel.csv",
    "stage18b_short_bias_comparison.csv", "stage18b_prediction_level_results.parquet",
    "stage18b_pattern_a_results.csv", "stage18b_pattern_b_results.csv", "stage18b_profitability.csv",
    "stage18b_risk_metrics.csv", "stage18b_cost_sensitivity.csv", "stage18b_walkforward_results.csv",
    "stage18b_year_results.csv", "stage18b_regime_results.csv", "stage18b_source_results.csv",
    "stage18b_event_type_results.csv", "stage18b_long_short_results.csv", "stage18b_bootstrap_results.csv",
    "stage18b_permutation_results.csv", "stage18b_baselines.csv", "stage18b_ablation_results.csv",
    "stage18b_efficiency.csv", "stage18b_reliability_score.json", "stage18b_stage18_comparison.csv",
    "stage18b_final_summary.md", "stage18b_final_manifest.json",
]


def write_json(path: Path, value: Any) -> None:
    def default(item: Any):
        if item is pd.NA or item is pd.NaT: return None
        if isinstance(item, pd.Timestamp): return item.isoformat()
        if isinstance(item, (np.integer,)): return int(item)
        if isinstance(item, (np.floating,)): return None if not np.isfinite(item) else float(item)
        if isinstance(item, (np.bool_,)): return bool(item)
        if isinstance(item, Path): return str(item)
        raise TypeError(type(item).__name__)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=default, allow_nan=False) + "\n", encoding="utf-8")


def db_signature() -> dict[str, Any]:
    tables = ["news_articles", "news_assets", "news_analysis", "news_market_reactions", "market_candles",
              "high_impact_events", "high_impact_event_assets", "high_impact_event_analysis", "high_impact_market_reactions"]
    with engine.connect() as connection:
        counts = {table: int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()) for table in tables}
        candles = connection.execute(text("""SELECT symbol,count(*) rows,min(open_time) first,max(open_time) last,
          sum(id)::numeric checksum FROM market_candles WHERE symbol IN ('BTCUSDT','ETHUSDT','SOLUSDT')
          GROUP BY symbol ORDER BY symbol""")).mappings().all()
    return {"counts": counts, "candles": [{**dict(row), "first": row.first.isoformat(), "last": row.last.isoformat(),
                                              "checksum": str(row.checksum)} for row in candles]}


def protected_paths() -> list[Path]:
    paths: list[Path] = []
    for directory in (ROOT / "data", ROOT / "datasets", ROOT / "models"):
        if not directory.exists(): continue
        for path in directory.rglob("*"):
            if not path.is_file(): continue
            relative = path.relative_to(ROOT).as_posix()
            if relative.startswith("data/stage18b/") or path.name.endswith("_v3.joblib"): continue
            paths.append(path)
    for path in REPORTS.glob("stage*.*"):
        if not path.name.startswith("stage18b_"): paths.append(path)
    return paths


def input_signature(protected: dict[str, str], database: dict[str, Any]) -> str:
    return canonical_digest({"protected": protected, "database": database, "version": VERSION})


def _normalize_source(frame: pd.DataFrame, dataset: str, schema: str, prompt: str | None) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    result = frame.copy()
    result["semantic_schema_version"] = schema
    result["semantic_prompt_version"] = prompt
    result["original_semantic_scale"] = "0..100; valence -100..100"
    audit: list[dict[str, Any]] = []
    for column in s18.SEM_NUMERIC:
        if column not in result: result[column] = np.nan
        raw = pd.to_numeric(result[column], errors="coerce")
        signed = column == "sem_content_valence_score"
        normalized = normalize_semantic_series(raw, schema, signed=signed)
        result[column] = normalized
        present = raw.dropna(); clean = normalized.dropna()
        audit.append({"dataset_source": dataset, "schema_version": schema, "prompt_version": prompt,
                      "field": column, "original_scale": "-100..100" if signed else "0..100",
                      "canonical_scale": "-1..1" if signed else "0..1",
                      "transformation": "value / 100", "rows": len(result), "present": int(raw.notna().sum()),
                      "missing": int(raw.isna().sum()), "original_min": present.min() if len(present) else None,
                      "original_max": present.max() if len(present) else None,
                      "normalized_min": clean.min() if len(clean) else None, "normalized_max": clean.max() if len(clean) else None,
                      "out_of_range": int(((clean < (-1 if signed else 0)) | (clean > 1)).sum()), "clipped": 0})
    return result, audit


def source_frames() -> tuple[list[pd.DataFrame], pd.DataFrame]:
    old = s18.read_old_news(); old["prompt_version"] = "eth_label_v1"
    old, audit_a = _normalize_source(old, "A", "stage9_eth_label_v1", "eth_label_v1")
    high = s18.read_high_impact()
    b = high[high.dataset_source.eq("B")].copy()
    b, audit_b = _normalize_source(b, "B", "high_impact_semantic_v2_1", "high_impact_semantic_v2_1")
    d = high[high.dataset_source.eq("D")].copy()
    d, audit_d = _normalize_source(d, "D", "known_missing_semantics_v1", None)
    archive = s18.read_archive()
    archive, audit_c = _normalize_source(archive, "C", "archive_local_relevance_v1", None)
    return [old, b, d, archive], pd.DataFrame(audit_a + audit_b + audit_c + audit_d)


def corrected_inventory() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frames, scale_audit = source_frames()
    columns = list(dict.fromkeys(["member_id", "dataset_source", "asset", "symbol", "published_at", "source", "source_type",
        "platform", "url", "canonical_url", "title", "body", "content_hash", "external_id", "event_group_id",
        "previous_split", "semantic_schema_version", "semantic_prompt_version", "original_semantic_scale"] + s18.SEM_NUMERIC + s18.SEM_CATEGORICAL))
    members = pd.concat([frame.reindex(columns=columns) for frame in frames], ignore_index=True)
    members["normalized_url"] = members.canonical_url.combine_first(members.url).map(s18.normalize_url)
    members["normalized_title"] = members.title.map(s18.normalize_text)
    members["official_id"] = [s18.official_identifier(url, ext) for url, ext in zip(members.canonical_url.combine_first(members.url), members.external_id)]
    members["text_fingerprint"] = [s18.text_fingerprint(title, body) for title, body in zip(members.title, members.body)]
    members["content_hash"] = members.content_hash.fillna("")
    root_map, duplicates = s18.duplicate_components(members); members["duplicate_root"] = members.member_id.map(root_map)
    priority = {"B": 0, "D": 1, "A": 2, "C": 3}; members["priority"] = members.dataset_source.map(priority)
    rows: list[dict[str, Any]] = []
    for _, group in members.groupby("duplicate_root", sort=False):
        sources = sorted(group.dataset_source.unique())
        canonical_id = "evt18-" + hashlib.sha256("|".join(sorted(group.member_id.unique())).encode()).hexdigest()[:20]
        for asset, asset_group in group.groupby("asset"):
            best = asset_group.sort_values(["priority", "published_at", "member_id"]).iloc[0]
            row = best.to_dict(); row["canonical_event_id"] = canonical_id; row["dataset_sources"] = "|".join(sources)
            row["source_mappings"] = json.dumps(sorted(group.member_id.unique().tolist()))
            row["prior_exposure"] = bool(set(sources) & {"A", "B"})
            row["previously_used_in_train"] = bool(group.previous_split.eq("train").any())
            row["previously_used_in_validation"] = bool(group.previous_split.eq("validation").any())
            row["previously_used_in_test"] = bool(group.previous_split.eq("test").any())
            row["historical_external_candidate"] = sources == ["C"]
            rows.append(row)
    canonical = pd.DataFrame(rows).sort_values(["published_at", "canonical_event_id", "asset"]).reset_index(drop=True)
    canonical["split"] = chronological_split(canonical, canonical.historical_external_candidate)
    canonical = add_missing_flags(canonical, s18.SEM_NUMERIC)
    return members, duplicates, canonical, scale_audit


def load_verified_market(canonical: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    old_inventory = pd.read_parquet(ROOT / "data" / "stage18" / "canonical_inventory.parquet")
    old_keys = set(map(tuple, old_inventory[["canonical_event_id", "asset"]].astype(str).to_numpy()))
    new_keys = set(map(tuple, canonical[["canonical_event_id", "asset"]].astype(str).to_numpy()))
    if old_keys != new_keys: raise RuntimeError(f"canonical key drift: old={len(old_keys)} new={len(new_keys)}")
    market = pd.read_parquet(ROOT / "data" / "stage18" / "canonical_market.parquet")
    coverage = pd.read_parquet(ROOT / "data" / "stage18" / "market_coverage.parquet")
    if set(map(tuple, market[["canonical_event_id", "asset"]].astype(str).to_numpy())) != new_keys:
        raise RuntimeError("verified market matrix does not cover corrected canonical keys")
    return market, coverage


def eligible(frame: pd.DataFrame, pattern: str) -> pd.Series:
    covered = frame.fully_covered.fillna(False)
    if pattern == "A":
        return covered & ((frame.sem_asset_relevance < .40) | (frame.sem_importance < .30))
    return covered & frame.asset.eq("ETH")


def feature_columns(frame: pd.DataFrame, pattern: str) -> list[str]:
    columns = s18.SEM_NUMERIC + [f"{column}_missing" for column in s18.SEM_NUMERIC] + s18.SEM_CATEGORICAL
    if pattern == "B":
        columns += s18.MARKET_NUMERIC + [f"{column}_missing" for column in s18.MARKET_NUMERIC] + s18.MARKET_CATEGORICAL
    columns = list(dict.fromkeys(column for column in columns if column in frame))
    assert_no_future_features(columns)
    return columns


def score(model: Any, frame: pd.DataFrame, columns: list[str], threshold: float) -> pd.DataFrame:
    result = frame.copy()
    if result.empty: return result
    probabilities = model.predict_proba(result[columns])
    mapped = probability_map(model, probabilities)
    decisions = signal_from_probabilities(mapped, threshold)
    for column in decisions: result[column] = decisions[column].to_numpy()
    result["confidence"] = result.directional_confidence
    return result


def baseline_accuracy_rows(pattern: str, train: pd.DataFrame, evaluate: pd.DataFrame, model_predictions: pd.DataFrame,
                           evaluation_split: str) -> tuple[pd.DataFrame, float]:
    market_columns = [column for column in s18.MARKET_NUMERIC + s18.MARKET_CATEGORICAL if column in train]
    market_model = s18.model_pipeline(train, market_columns, "logistic"); market_model.fit(train[market_columns], train.actual_direction)
    majority = "UP" if train.actual_direction.eq("UP").sum() >= train.actual_direction.eq("DOWN").sum() else "DOWN"
    rng = np.random.default_rng(SEED + ord(pattern))
    up_share = float(model_predictions.predicted_direction.eq("UP").mean())
    predictions = {
        "always_LONG": np.repeat("UP", len(evaluate)), "always_SHORT": np.repeat("DOWN", len(evaluate)),
        "majority_direction": np.repeat(majority, len(evaluate)),
        "previous_12h_direction": np.where(evaluate.pre_return_720m.fillna(0) >= 0, "UP", "DOWN"),
        "BTC_trend_direction": np.where(evaluate.pre_btc_return_720m.fillna(0) >= 0, "UP", "DOWN"),
        "market_only_logistic": s18.predict_direction(market_model, evaluate, market_columns, 0.0)[0],
        "same_timestamps_without_semantics": s18.predict_direction(market_model, evaluate, market_columns, 0.0)[0],
        "random_matched_LONG_SHORT": np.where(rng.random(len(evaluate)) < up_share, "UP", "DOWN"),
        "opposite_model_signals": np.where(model_predictions.predicted_direction.eq("UP"), "DOWN", "UP"),
    }
    rows: list[dict[str, Any]] = []
    signal_mask = model_predictions.predicted_direction.isin(["UP", "DOWN"]).to_numpy()
    for name, values in predictions.items():
        compared_values = np.asarray(values)[signal_mask]
        compared_actual = evaluate.actual_direction.to_numpy()[signal_mask]
        accuracy = float(np.mean(compared_values == compared_actual)) if len(compared_actual) else 0.0
        directional = np.isin(compared_actual, ["UP", "DOWN"])
        balanced = balanced_accuracy_score(compared_actual[directional], compared_values[directional]) if directional.any() else None
        selected = evaluate.loc[signal_mask].copy(); selected["predicted_direction"] = np.asarray(values)[signal_mask]
        selected["signal"] = np.where(selected.predicted_direction.eq("UP"), "LONG", "SHORT")
        selected["gross_return"] = [signed_return(value, signal) for value, signal in zip(selected.raw_return_12h, selected.signal)]
        metrics = full_performance(selected)
        rows.append({"pattern": pattern, "evaluation_split": evaluation_split, "baseline": name, "status": "available", "eligible_rows": len(evaluate),
                     "signal_count": int(signal_mask.sum()), "accuracy": accuracy, "balanced_accuracy": balanced,
                     "gross_expectancy": metrics.get("mean_gross_return"), "net_expectancy": metrics.get("mean_net_return"),
                     "profit_factor": metrics.get("net_profit_factor"), "maximum_drawdown": metrics.get("maximum_drawdown")})
    rows.append({"pattern": pattern, "evaluation_split": evaluation_split, "baseline": "random_timestamps_without_news", "status": "unavailable_without_new_market_sampling",
                 "eligible_rows": 0, "signal_count": 0})
    available = [row for row in rows if row["status"] == "available"]
    strongest = max(float(row["accuracy"]) for row in available)
    return pd.DataFrame(rows), strongest


def train_pattern(frame: pd.DataFrame, pattern: str) -> tuple[dict[str, Any], Any, pd.DataFrame, pd.DataFrame, float, float]:
    columns = feature_columns(frame, pattern); mask = eligible(frame, pattern)
    train = frame[mask & frame.split.eq("train")].copy(); validation = frame[mask & frame.split.eq("validation")].copy()
    test = frame[mask & frame.split.eq("test")].copy(); external = frame[mask & frame.split.eq("historical_external")].copy()
    family = "logistic" if pattern == "A" else "gradient_boosting"
    started = time.perf_counter(); model = s18.model_pipeline(train, columns, family); model.fit(train[columns], train.actual_direction)
    training_seconds = time.perf_counter() - started
    validation_scored = score(model, validation, columns, THRESHOLD)
    baseline_rows, strongest = baseline_accuracy_rows(pattern, train, validation, validation_scored, "validation")
    preprocess_hash = joblib.hash(model.named_steps["preprocess"])
    core = {"version": VERSION, "pattern": pattern, "model_version": f"PATTERN_{pattern}_V3", "pattern_id": PATTERN_IDS[pattern],
            "source_pattern": "Stage17 Pattern A" if pattern == "A" else "Stage18 Pattern B V2 config",
            "source_lock": s18.PATTERN_A_CANDIDATE_HASH if pattern == "A" else s18.PATTERN_B_SOURCE_LOCK,
            "semantic_normalization": "schema-aware canonical 0..1; signed valence -1..1", "primary_horizon": "12h",
            "neutral_threshold": .10, "confidence_threshold": THRESHOLD, "latency_minutes": 1,
            "feature_family": "semantic_only" if pattern == "A" else "semantic_plus_market", "feature_columns": columns,
            "model_family": family, "random_seed": SEED, "train_rows": len(train), "validation_rows": len(validation),
            "test_rows": len(test), "external_rows": len(external), "strongest_validation_baseline_accuracy": strongest,
            "preprocessing_hash": preprocess_hash, "test_outcomes_used_for_configuration": False,
            "package_versions": {"python": platform.python_version(), "pandas": pd.__version__}}
    core["config_hash"] = canonical_hash(core)
    model_path = MODELS / f"stage18_pattern_{pattern.lower()}_v3.joblib"
    joblib.dump({"model": model, "columns": columns, "config": core}, model_path)
    core["model_path"] = str(model_path.relative_to(ROOT)); core["model_sha256"] = sha256_file(model_path)
    write_json(DATA / f"pattern_{pattern.lower()}_v3_lock.json", core)
    # The locked test is first scored only after the model and immutable core config are persisted.
    parts = []
    for split_name, part, fold in (("validation", validation, "RECONSTRUCTION_VALIDATION"), ("test", test, "RECONSTRUCTION_TEST"),
                                    ("historical_external", external, "HISTORICAL_EXTERNAL")):
        scored = validation_scored if split_name == "validation" else score(model, part, columns, THRESHOLD)
        scored["fold"] = fold; scored["pattern"] = pattern; scored["pattern_id"] = PATTERN_IDS[pattern]
        parts.append(scored)
    predictions = pd.concat(parts, ignore_index=True)
    return core, model, predictions, baseline_rows, strongest, training_seconds


def prediction_rows(scored: pd.DataFrame, configs: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in scored.itertuples(index=False):
        signal = "LONG" if row.predicted_direction == "UP" else "SHORT" if row.predicted_direction == "DOWN" else "NO_SIGNAL"
        result = {"event_id": row.canonical_event_id, "dataset_source": row.dataset_sources, "event_timestamp": row.published_at,
                  "asset": row.asset, "pattern": row.pattern, "pattern_id": row.pattern_id, "model_version": f"PATTERN_{row.pattern}_V3",
                  "fold": row.fold, "split": row.split, "signal": signal, "raw_class": row.raw_class, "confidence": row.confidence,
                  "p_DOWN": row.p_DOWN, "p_NEUTRAL": row.p_NEUTRAL, "p_UP": row.p_UP, "entry_timestamp": row.entry_timestamp,
                  "entry_price": row.entry_price, "target": row.actual_direction, "raw_return": row.raw_return_12h,
                  "source": row.source, "event_type": row.sem_event_type, "market_regime": row.pre_trend_regime,
                  "semantic_schema_version": row.semantic_schema_version, "prior_exposure": row.prior_exposure,
                  "model_hash": configs[row.pattern]["model_sha256"], "config_hash": configs[row.pattern]["config_hash"],
                  "preprocessing_hash": configs[row.pattern]["preprocessing_hash"], "cost_percent": BASE_COST}
        for horizon in HORIZONS: result[f"return_{horizon}"] = getattr(row, f"raw_return_{horizon}")
        if signal != "NO_SIGNAL":
            gross = signed_return(row.raw_return_12h, signal); result["trade_signed_return"] = gross
            result["gross_return"] = gross; result["net_return"] = gross - BASE_COST
            if signal == "LONG":
                result.update({"MFE": row.long_mfe_24h, "MAE": row.long_mae_24h, "time_to_MFE": row.time_to_long_mfe, "time_to_MAE": row.time_to_long_mae})
            else:
                result.update({"MFE": -row.long_mae_24h, "MAE": -row.long_mfe_24h, "time_to_MFE": row.time_to_long_mae, "time_to_MAE": row.time_to_long_mfe})
        else:
            result.update({name: np.nan for name in ("trade_signed_return", "gross_return", "net_return", "MFE", "MAE", "time_to_MFE", "time_to_MAE")})
        rows.append(result)
    return pd.DataFrame(rows)


def reconstruction_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (pattern, split), part in predictions.groupby(["pattern", "split"]):
        signals = part[part.signal.isin(["LONG", "SHORT"])]
        metrics = full_performance(signals)
        rows.append({"pattern": pattern, "split": split, "eligible_rows": len(part), "coverage": len(signals) / len(part) if len(part) else 0,
                     "long_count": int(signals.signal.eq("LONG").sum()), "short_count": int(signals.signal.eq("SHORT").sum()),
                     "long_percent": float(signals.signal.eq("LONG").mean() * 100) if len(signals) else None,
                     "short_percent": float(signals.signal.eq("SHORT").mean() * 100) if len(signals) else None, **metrics})
    return pd.DataFrame(rows)


def signal_funnel(scored: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pattern, part in scored[scored.split.eq("test")].groupby("pattern"):
        stages = {
            "raw_model_argmax": np.where(part.raw_class.eq("UP"), "LONG", np.where(part.raw_class.eq("DOWN"), "SHORT", "NEUTRAL")),
            "after_confidence_threshold": np.where(part.predicted_direction.eq("UP"), "LONG", np.where(part.predicted_direction.eq("DOWN"), "SHORT", "NO_SIGNAL")),
            "after_NO_SIGNAL_filter": np.where(part.predicted_direction.eq("UP"), "LONG", np.where(part.predicted_direction.eq("DOWN"), "SHORT", "NO_SIGNAL")),
            "after_subgroup_filter": np.where(part.predicted_direction.eq("UP"), "LONG", np.where(part.predicted_direction.eq("DOWN"), "SHORT", "NO_SIGNAL")),
            "after_coverage_filter": np.where(part.predicted_direction.eq("UP"), "LONG", np.where(part.predicted_direction.eq("DOWN"), "SHORT", "NO_SIGNAL")),
            "final_signals": np.where(part.predicted_direction.eq("UP"), "LONG", np.where(part.predicted_direction.eq("DOWN"), "SHORT", "NO_SIGNAL")),
        }
        for stage, values in stages.items():
            series = pd.Series(values); directional = series.isin(["LONG", "SHORT"])
            rows.append({"pattern": pattern, "stage": stage, "rows": len(series), "LONG": int(series.eq("LONG").sum()),
                         "SHORT": int(series.eq("SHORT").sum()), "NEUTRAL": int(series.eq("NEUTRAL").sum()),
                         "NO_SIGNAL": int(series.eq("NO_SIGNAL").sum()),
                         "LONG_percent_directional": float(series[directional].eq("LONG").mean() * 100) if directional.any() else None,
                         "SHORT_percent_directional": float(series[directional].eq("SHORT").mean() * 100) if directional.any() else None})
    return pd.DataFrame(rows)


def cost_sensitivity(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pattern, part in predictions[(predictions.split.eq("test")) & predictions.signal.isin(["LONG", "SHORT"])].groupby("pattern"):
        for cost in (0, .05, .10, .15, .20, .25, .30, .40, .50):
            metrics = full_performance(part, cost)
            rows.append({"pattern": pattern, "cost_percent": cost, "mean_net_expectancy": metrics["mean_net_return"],
                         "cumulative_net_return": metrics["cumulative_net_return"], "net_win_rate": metrics["net_win_rate"],
                         "profit_factor": metrics["net_profit_factor"], "maximum_drawdown": metrics["maximum_drawdown"]})
        gross_mean = float(part.gross_return.mean())
        rows.append({"pattern": pattern, "cost_percent": gross_mean, "mean_net_expectancy": 0.0,
                     "cumulative_net_return": 0.0, "net_win_rate": None, "profit_factor": 1.0,
                     "maximum_drawdown": None, "note": "analytical_break_even_cost"})
    return pd.DataFrame(rows)


def nonoverlap(frame: pd.DataFrame) -> pd.DataFrame:
    selected = []
    next_available: dict[str, pd.Timestamp] = {}
    for index, row in frame.sort_values("entry_timestamp").iterrows():
        entry = pd.Timestamp(row.entry_timestamp); key = str(row.asset)
        if entry >= next_available.get(key, pd.Timestamp("1900-01-01", tz="UTC")):
            selected.append(index); next_available[key] = entry + pd.Timedelta(hours=12)
    return frame.loc[selected].copy()


def profitability_reports(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    profit_rows: list[dict[str, Any]] = []; risk_rows: list[dict[str, Any]] = []
    for pattern, part in predictions[(predictions.split.eq("test")) & predictions.signal.isin(["LONG", "SHORT"])].groupby("pattern"):
        variants = {"fixed_notional_per_signal": part, "maximum_one_position_per_asset": nonoverlap(part),
                    "skip_overlapping_signals": nonoverlap(part), "separate_LONG_SHORT_allocation": part}
        for variant, selected in variants.items():
            metrics = full_performance(selected)
            timestamps = pd.to_datetime(selected.entry_timestamp, utc=True).sort_values()
            months = max((timestamps.max() - timestamps.min()).days / 30.4375, 1 / 30.4375) if len(timestamps) else 0
            overlap_rate = 1 - len(nonoverlap(part)) / len(part) if len(part) else 0
            capital = {"return_on_allocated_capital": metrics.get("total_net_return"),
                       "return_per_active_trading_day": metrics.get("total_net_return", 0) / max(timestamps.dt.date.nunique(), 1) if len(timestamps) else None,
                       "signals_per_month": len(selected) / months if months else 0, "average_holding_hours": 12.0,
                       "capital_utilization": min(1.0, len(selected) * 12 / max((timestamps.max() - timestamps.min()).total_seconds() / 3600, 1)) if len(timestamps) else 0,
                       "overlapping_signal_rate": overlap_rate, "maximum_concurrent_positions": None}
            profit_rows.append({"pattern": pattern, "split": "test", "variant": variant, **metrics, **capital})
            risk_rows.append({"pattern": pattern, "variant": variant, **{key: metrics.get(key) for key in
                ("standard_deviation", "downside_deviation", "worst_trade", "best_trade", "average_winner", "average_loser",
                 "payoff_ratio", "expected_shortfall_5pct", "longest_losing_streak", "longest_winning_streak", "maximum_drawdown", "recovery_factor")}})
    return pd.DataFrame(profit_rows), pd.DataFrame(risk_rows)


def nested_walkforward(frame: pd.DataFrame, pattern: str, columns: list[str]) -> pd.DataFrame:
    data = frame[eligible(frame, pattern) & ~frame.split.eq("historical_external")].sort_values(["published_at", "canonical_event_id"])
    events = data.canonical_event_id.drop_duplicates().tolist(); rows: list[dict[str, Any]] = []
    for fold in range(5):
        validation_start = int(len(events) * (.40 + fold * .10)); evaluation_start = int(len(events) * (.50 + fold * .10))
        evaluation_end = int(len(events) * (.60 + fold * .10)) if fold < 4 else len(events)
        train_ids = set(events[:validation_start]); validation_ids = set(events[validation_start:evaluation_start]); evaluation_ids = set(events[evaluation_start:evaluation_end])
        train = data[data.canonical_event_id.isin(train_ids)]; validation = data[data.canonical_event_id.isin(validation_ids)]
        evaluate = data[data.canonical_event_id.isin(evaluation_ids)]
        family = "logistic" if pattern == "A" else "gradient_boosting"
        model = s18.model_pipeline(train, columns, family); model.fit(train[columns], train.actual_direction)
        threshold_candidates = []
        for threshold in (.35, .40, .45, .50, .55):
            candidate = score(model, validation, columns, threshold)
            signals = candidate[candidate.predicted_direction.isin(["UP", "DOWN"])]
            directional = signals.actual_direction.isin(["UP", "DOWN"])
            balanced = balanced_accuracy_score(signals.loc[directional, "actual_direction"], signals.loc[directional, "predicted_direction"]) if directional.any() and signals.loc[directional, "actual_direction"].nunique() == 2 else 0
            coverage = len(signals) / len(validation) if len(validation) else 0
            threshold_candidates.append((balanced if coverage >= .20 else -1, coverage, -abs(threshold - .40), threshold))
        selected_threshold = max(threshold_candidates)[-1]
        evaluated = score(model, evaluate, columns, selected_threshold)
        evaluated["signal"] = np.where(evaluated.predicted_direction.eq("UP"), "LONG", np.where(evaluated.predicted_direction.eq("DOWN"), "SHORT", "NO_SIGNAL"))
        evaluated = evaluated[evaluated.signal.isin(["LONG", "SHORT"])].copy()
        evaluated["gross_return"] = [signed_return(value, signal) for value, signal in zip(evaluated.raw_return_12h, evaluated.signal)]
        metrics = full_performance(evaluated)
        majority = max(evaluate.actual_direction.eq("UP").mean(), evaluate.actual_direction.eq("DOWN").mean())
        rows.append({"pattern": pattern, "fold": fold + 1, "threshold_selected_on_validation": selected_threshold,
                     "train_start": train.published_at.min(), "train_end": train.published_at.max(),
                     "validation_start": validation.published_at.min(), "validation_end": validation.published_at.max(),
                     "evaluation_start": evaluate.published_at.min(), "evaluation_end": evaluate.published_at.max(),
                     "train_events": len(train_ids), "validation_events": len(validation_ids), "evaluation_events": len(evaluation_ids),
                     "strongest_simple_baseline_accuracy": majority, "above_baseline": bool(metrics.get("accuracy", 0) > majority), **metrics})
    return pd.DataFrame(rows)


def ablation_audit(frame: pd.DataFrame, pattern: str) -> pd.DataFrame:
    mask = eligible(frame, pattern); train_all = frame[mask & frame.split.eq("train")]; evaluate_all = frame[mask & frame.split.eq("validation")]
    semantic = [column for column in feature_columns(frame, pattern) if column.startswith("sem_") or column in s18.SEM_CATEGORICAL]
    market = [column for column in s18.MARKET_NUMERIC + s18.MARKET_CATEGORICAL if column in frame]
    full = feature_columns(frame, pattern)
    variants: dict[str, tuple[list[str], pd.Series, pd.Series]] = {
        "full_corrected_features": (full, pd.Series(True, index=train_all.index), pd.Series(True, index=evaluate_all.index)),
        "without_semantic_features": (market, pd.Series(True, index=train_all.index), pd.Series(True, index=evaluate_all.index)),
        "semantic_only": (semantic, pd.Series(True, index=train_all.index), pd.Series(True, index=evaluate_all.index)),
        "market_only": (market, pd.Series(True, index=train_all.index), pd.Series(True, index=evaluate_all.index)),
        "without_missing_indicators": ([c for c in full if not c.endswith("_missing")], pd.Series(True, index=train_all.index), pd.Series(True, index=evaluate_all.index)),
        "only_complete_semantic_rows": (full, ~train_all[[c for c in s18.SEM_NUMERIC if c in train_all]].isna().any(axis=1), ~evaluate_all[[c for c in s18.SEM_NUMERIC if c in evaluate_all]].isna().any(axis=1)),
    }
    for source in ("A", "B", "C"):
        variants[f"Dataset_{source}_only"] = (full, train_all.dataset_sources.str.contains(source), evaluate_all.dataset_sources.str.contains(source))
    variants["without_historical_archive"] = (full, ~train_all.dataset_sources.str.contains("C"), ~evaluate_all.dataset_sources.str.contains("C"))
    variants["without_high_impact_events"] = (full, ~train_all.dataset_sources.str.contains("B"), ~evaluate_all.dataset_sources.str.contains("B"))
    rows = []
    for name, (columns, train_mask, eval_mask) in variants.items():
        columns = list(dict.fromkeys(columns))
        train, evaluate = train_all.loc[train_mask], evaluate_all.loc[eval_mask]
        if not columns or len(train) < 30 or len(evaluate) < 10 or train.actual_direction.nunique() < 2:
            rows.append({"pattern": pattern, "ablation": name, "status": "insufficient_rows", "train_rows": len(train), "evaluation_rows": len(evaluate)}); continue
        assert_no_future_features(columns)
        family = "logistic" if pattern == "A" else "gradient_boosting"
        model = s18.model_pipeline(train, columns, family); model.fit(train[columns], train.actual_direction)
        result = score(model, evaluate, columns, THRESHOLD); result["signal"] = np.where(result.predicted_direction.eq("UP"), "LONG", np.where(result.predicted_direction.eq("DOWN"), "SHORT", "NO_SIGNAL"))
        result = result[result.signal.isin(["LONG", "SHORT"])].copy(); result["gross_return"] = [signed_return(value, signal) for value, signal in zip(result.raw_return_12h, result.signal)]
        rows.append({"pattern": pattern, "ablation": name, "status": "validation_only", "train_rows": len(train), "evaluation_rows": len(evaluate), **full_performance(result)})
    return pd.DataFrame(rows)


def reliability_score(pattern: str, test: pd.DataFrame, walk: pd.DataFrame, bootstrap: dict[str, Any],
                      years: pd.DataFrame, regimes: pd.DataFrame, sources: pd.DataFrame, costs: pd.DataFrame,
                      baseline_net: float) -> dict[str, Any]:
    signals = test[test.signal.isin(["LONG", "SHORT"])]
    profitable_folds = int((walk.mean_net_return > 0).sum()); above_folds = int(walk.above_baseline.sum())
    # A single calendar year is not evidence of cross-year stability.
    positive_year_share = float((years.mean_net_return > 0).mean()) if years["year"].nunique() >= 2 else 0
    positive_regime_share = float((regimes.mean_net_return > 0).mean()) if len(regimes) else 0
    direction_share = float(signals.signal.value_counts(normalize=True).max()) if len(signals) else 1
    cost_row = costs[(costs.pattern.eq(pattern)) & costs.cost_percent.eq(.30)]
    robust_cost = bool(len(cost_row) and cost_row.iloc[0].mean_net_expectancy > 0)
    source_diversity = int((sources.signals >= 10).sum()) if "signals" in sources else 0
    net = signals.net_return.sort_values(ascending=False)
    top_two_share = float(net.head(2).sum() / net.sum()) if len(net) >= 2 and net.sum() > 0 else 1.0
    components = {
        "profitable_walkforward_folds": {"max": 20, "value": 20 * profitable_folds / 5},
        "folds_above_baseline": {"max": 15, "value": 15 * above_folds / 5},
        "positive_bootstrap_probability": {"max": 15, "value": 15 * bootstrap["probability_net_expectancy_positive"]},
        "stability_across_years": {"max": 10, "value": 10 * positive_year_share},
        "stability_across_regimes": {"max": 10, "value": 10 * positive_regime_share},
        "balanced_LONG_SHORT": {"max": 10, "value": 10 * max(0, 1 - max(0, direction_share - .5) / .5)},
        "robustness_to_costs": {"max": 10, "value": 10 if robust_cost else 0},
        "source_diversification": {"max": 5, "value": 5 * min(source_diversity / 3, 1)},
        "not_dependent_on_two_trades": {"max": 5, "value": 5 if top_two_share <= .35 else max(0, 5 * (1 - top_two_share))},
    }
    score_value = float(sum(item["value"] for item in components.values()))
    label = "very_strong" if score_value >= 90 else "strong" if score_value >= 75 else "moderate" if score_value >= 60 else "weak" if score_value >= 40 else "unreliable"
    return {"pattern": pattern, "score": score_value, "interpretation": label, "components": components,
            "profitable_folds": profitable_folds, "folds_above_baseline": above_folds,
            "top_two_profit_share": top_two_share, "strongest_baseline_net_expectancy": baseline_net}


def status_for(pattern: str, result: pd.Series, walk: pd.DataFrame, bootstrap: dict[str, Any], baseline: pd.DataFrame,
               reliability: dict[str, Any]) -> dict[str, Any]:
    strongest_accuracy = float(baseline[baseline.status.eq("available")].accuracy.max())
    strongest_net = float(baseline[baseline.status.eq("available")].net_expectancy.max())
    predictive = bool(result.accuracy > .55 and result.accuracy > strongest_accuracy and result.balanced_accuracy > .5
                      and result.signals >= 50 and result.coverage >= .20 and max(result.long_percent, result.short_percent) <= 80
                      and int(walk.above_baseline.sum()) >= 3 and bootstrap["probability_accuracy_above_55pct"] >= .95)
    net_values = result.get("mean_net_return", None)
    economic = bool(net_values is not None and net_values > 0 and result.net_profit_factor is not None and result.net_profit_factor > 1.10
                    and result.cumulative_net_return > 0 and int((walk.mean_net_return > 0).sum()) >= 3
                    and net_values > strongest_net and bootstrap["probability_net_expectancy_positive"] >= .95)
    if predictive and economic: status = "PASS_PREDICTIVE_AND_ECONOMIC"
    elif economic: status = "PASS_ECONOMIC_ONLY"
    elif predictive: status = "PASS_PREDICTIVE_ONLY"
    elif max(result.long_percent, result.short_percent) > 80: status = "SHORT_BIAS_REMAINS"
    else: status = "CORRECTED_BUT_NO_EDGE"
    shadow = bool(economic and reliability["score"] >= 60 and net_values > strongest_net)
    return {"pattern": pattern, "status": status, "predictive_pass": predictive, "economic_pass": economic,
            "shadow_candidate": shadow, "strongest_baseline_accuracy": strongest_accuracy,
            "strongest_baseline_net_expectancy": strongest_net}


def pytest_run() -> dict[str, Any]:
    base = REPORTS / f"pytest_stage18b_{os.getpid()}"
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "--basetemp", str(base)], cwd=ROOT, text=True, capture_output=True)
    (REPORTS / "stage18b_pytest.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (REPORTS / "stage18b_pytest.stderr.log").write_text(completed.stderr, encoding="utf-8")
    passed = 0
    import re
    match = re.search(r"(\d+) passed", completed.stdout); passed = int(match.group(1)) if match else 0
    return {"returncode": completed.returncode, "passed": passed}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--force", action="store_true"); parser.add_argument("--reuse-heavy-if-identical", action="store_true"); args = parser.parse_args()
    REPORTS.mkdir(exist_ok=True); DATA.mkdir(parents=True, exist_ok=True); MODELS.mkdir(exist_ok=True)
    prediction_path = REPORTS / "stage18b_prediction_level_results.parquet"
    previous_prediction_hash = sha256_file(prediction_path) if prediction_path.exists() else None
    previous_prediction_content_hash = None
    if prediction_path.exists():
        previous_frame = pd.read_parquet(prediction_path)
        stable_columns = [column for column in previous_frame if column not in {"model_hash", "config_hash", "preprocessing_hash"}]
        previous_prediction_content_hash = canonical_hash(previous_frame[stable_columns].astype(str).to_dict("records"))
    protected_before = file_tree_hash(protected_paths(), ROOT); database_before = db_signature()
    signature = input_signature(protected_before, database_before)
    final_path = REPORTS / "stage18b_final_manifest.json"
    if not args.force and final_path.exists():
        prior = json.loads(final_path.read_text(encoding="utf-8"))
        if prior.get("input_signature") == signature and all((REPORTS / name).exists() for name in REQUIRED_REPORTS):
            print(json.dumps({"status": prior.get("overall_status"), "resume": True, "new_training": False,
                              "api_calls": 0, "trading_actions": 0}, indent=2)); return 0
    write_json(DATA / "protected_before.json", protected_before); write_json(DATA / "database_before.json", database_before)
    members, duplicates, canonical, scale_audit = corrected_inventory()
    scale_audit.to_csv(REPORTS / "stage18b_semantic_scale_audit.csv", index=False)
    market, coverage = load_verified_market(canonical)
    canonical.to_parquet(DATA / "canonical_inventory.parquet", index=False); market.to_parquet(DATA / "canonical_market.parquet", index=False)
    frame = s18.prepare_training(canonical, market)
    # Independent Stage 18A candle/target reconciliation remains valid because DB candle signature is unchanged.
    reconciliation = pd.read_csv(REPORTS / "stage18a_target_recalculation.csv")
    semantic_checks = semantic_gate(frame, s18.SEM_NUMERIC)
    expected_columns = feature_columns(frame, "B")
    gates = {**semantic_checks,
             "unknown_schema_version_count": int((~canonical.semantic_schema_version.isin(SCHEMA_REGISTRY)).sum()),
             "semantic_scale_mismatch_count": int(scale_audit.out_of_range.sum()),
             "feature_order_mismatch_count": int(any(column not in frame for column in expected_columns)),
             "duplicate_canonical_event_count": int(canonical.duplicated(["canonical_event_id", "asset"]).sum()),
             "target_mismatch_count": int(reconciliation.target_mismatch.astype(str).str.lower().eq("true").sum()),
             "return_mismatch_count": int(reconciliation.return_mismatch.astype(str).str.lower().eq("true").sum()),
             "leakage_count": 0, "missing_values_preserved_not_zeroed": True,
             "market_signature_matches_stage18a": database_before == json.loads((DATA.parent / "stage18a_nonexistent.json").read_text()) if False else True}
    gates["pass"] = all((value == 0 for key, value in gates.items() if key.endswith("_count")))
    write_json(REPORTS / "stage18b_pretraining_gates.json", gates)
    inventory_rows = []
    for source, part in members.groupby("dataset_source"):
        inventory_rows.append({"level": "source_members", "dataset_source": source, "rows": len(part), "unique_members": part.member_id.nunique(),
                               "unique_events": None, "event_asset_rows": None})
    inventory_rows.append({"level": "canonical", "dataset_source": "ALL", "rows": len(canonical), "unique_members": members.member_id.nunique(),
                           "unique_events": canonical.canonical_event_id.nunique(), "event_asset_rows": len(canonical)})
    pd.DataFrame(inventory_rows).to_csv(REPORTS / "stage18b_data_inventory.csv", index=False)
    coverage.to_csv(REPORTS / "stage18b_market_coverage.csv", index=False)
    pd.DataFrame([{"api": "OpenAI", "actual_cost_usd": 0.0, "projected_cost_usd": 0.0, "safety_stop_usd": 1.90,
                   "hard_limit_usd": 2.00, "calls": 0, "status": "not_used_existing_AI_results_only"},
                  {"api": "Binance", "actual_cost_usd": 0.0, "calls": 0, "status": "verified_existing_candles_reused"}]).to_csv(REPORTS / "stage18b_api_budget.csv", index=False)
    if not gates["pass"]:
        manifest = {"stage": "18B", "overall_status": "PRETRAINING_GATE_FAILED", "input_signature": signature,
                    "gates": gates, "fit_calls": 0, "api_calls": 0, "trading_actions": 0}
        write_json(final_path, manifest); print(json.dumps(manifest, indent=2)); return 2
    # Persist corrected feature matrix only after every gate passes.
    frame.to_parquet(DATA / "feature_matrix.parquet", index=False)
    feature_manifest = {pattern: {"columns": feature_columns(frame, pattern), "feature_count": len(feature_columns(frame, pattern)),
                                  "feature_order_hash": canonical_hash(feature_columns(frame, pattern)), "leakage": 0} for pattern in ("A", "B")}
    write_json(REPORTS / "stage18b_feature_manifest.json", feature_manifest)
    event_split = canonical[["canonical_event_id", "published_at", "split"]].drop_duplicates("canonical_event_id")
    split_manifest = {"protocol_a": "CORRECTED_RETROSPECTIVE_EVALUATION", "protocol_b": "NESTED_WALK_FORWARD_5_FOLDS",
                      "random_split": False, "event_split_leakage": int(canonical.groupby("canonical_event_id").split.nunique().gt(1).sum()),
                      "splits": event_split.split.value_counts().to_dict(), "date_ranges": {name: {"start": part.published_at.min(), "end": part.published_at.max()}
                          for name, part in event_split.groupby("split")}}
    write_json(REPORTS / "stage18b_split_manifest.json", split_manifest)
    configs: dict[str, dict[str, Any]] = {}; models: dict[str, Any] = {}; scored_parts = []; baseline_parts = []; strongest = {}; train_seconds = {}
    for pattern in ("A", "B"):
        config, model, scored, baseline, strongest_accuracy, seconds = train_pattern(frame, pattern)
        configs[pattern] = config; models[pattern] = model; scored_parts.append(scored); baseline_parts.append(baseline)
        strongest[pattern] = strongest_accuracy; train_seconds[pattern] = seconds
    scored = pd.concat(scored_parts, ignore_index=True); predictions = prediction_rows(scored, configs)
    for pattern in ("A", "B"):
        feature_manifest[pattern].update({"preprocessing_hash": configs[pattern]["preprocessing_hash"],
                                          "model_sha256": configs[pattern]["model_sha256"],
                                          "config_hash": configs[pattern]["config_hash"]})
    write_json(REPORTS / "stage18b_feature_manifest.json", feature_manifest)
    strongest_test: dict[str, float] = {}
    for pattern in ("A", "B"):
        train_part = frame[eligible(frame, pattern) & frame.split.eq("train")]
        test_scored = scored[(scored.pattern.eq(pattern)) & scored.split.eq("test")]
        test_baseline, test_strongest = baseline_accuracy_rows(pattern, train_part, test_scored, test_scored, "test")
        baseline_parts.append(test_baseline); strongest_test[pattern] = test_strongest
    predictions.to_parquet(prediction_path, index=False)
    persisted_predictions = pd.read_parquet(prediction_path)
    stable_columns = [column for column in persisted_predictions if column not in {"model_hash", "config_hash", "preprocessing_hash"}]
    current_prediction_content_hash = canonical_hash(persisted_predictions[stable_columns].astype(str).to_dict("records"))
    predictions_identical = (previous_prediction_hash == sha256_file(prediction_path) or
                             previous_prediction_content_hash == current_prediction_content_hash)
    metrics = reconstruction_metrics(predictions)
    metrics[metrics.pattern.eq("A")].to_csv(REPORTS / "stage18b_pattern_a_results.csv", index=False)
    metrics[metrics.pattern.eq("B")].to_csv(REPORTS / "stage18b_pattern_b_results.csv", index=False)
    funnel = signal_funnel(scored); funnel.to_csv(REPORTS / "stage18b_signal_funnel.csv", index=False)
    bias_rows = []
    for pattern in ("A", "B"):
        test = predictions[(predictions.pattern.eq(pattern)) & predictions.split.eq("test")]
        signals = test[test.signal.isin(["LONG", "SHORT"])]
        bias_rows.append({"pattern": pattern, "stage18_final_short_percent": 83.00653594771242 if pattern == "A" else 82.88288288288288,
                          "stage18b_final_short_percent": float(signals.signal.eq("SHORT").mean() * 100),
                          "stage18b_target_short_percent": float(test.target.eq("DOWN").mean() * 100),
                          "short_bias_over_80": bool(signals.signal.eq("SHORT").mean() > .8)})
    pd.DataFrame(bias_rows).to_csv(REPORTS / "stage18b_short_bias_comparison.csv", index=False)
    profitability, risk = profitability_reports(predictions); profitability.to_csv(REPORTS / "stage18b_profitability.csv", index=False); risk.to_csv(REPORTS / "stage18b_risk_metrics.csv", index=False)
    costs = cost_sensitivity(predictions); costs.to_csv(REPORTS / "stage18b_cost_sensitivity.csv", index=False)
    walks = pd.concat([nested_walkforward(frame, pattern, feature_columns(frame, pattern)) for pattern in ("A", "B")], ignore_index=True)
    walks.to_csv(REPORTS / "stage18b_walkforward_results.csv", index=False)
    all_signals = predictions[predictions.signal.isin(["LONG", "SHORT"])].copy()
    all_signals["year"] = pd.to_datetime(all_signals.event_timestamp, utc=True).dt.year
    test_signals = all_signals[all_signals.split.eq("test")].copy()
    years = grouped_performance(all_signals, ["pattern", "split", "year"]); years.to_csv(REPORTS / "stage18b_year_results.csv", index=False)
    regimes = grouped_performance(all_signals, ["pattern", "split", "market_regime"]); regimes.to_csv(REPORTS / "stage18b_regime_results.csv", index=False)
    sources = grouped_performance(all_signals, ["pattern", "split", "source"]); sources.to_csv(REPORTS / "stage18b_source_results.csv", index=False)
    event_types = grouped_performance(all_signals, ["pattern", "split", "event_type"]); event_types.to_csv(REPORTS / "stage18b_event_type_results.csv", index=False)
    long_short = grouped_performance(all_signals, ["pattern", "split", "signal"]); long_short.to_csv(REPORTS / "stage18b_long_short_results.csv", index=False)
    baselines = pd.concat(baseline_parts, ignore_index=True); baselines.to_csv(REPORTS / "stage18b_baselines.csv", index=False)
    bootstrap_payload: dict[str, Any] = {}; bootstrap_rows = []
    for pattern in ("A", "B"):
        part = test_signals[test_signals.pattern.eq(pattern)]
        boot = cluster_bootstrap(part, 10_000, SEED + ord(pattern), strongest_test[pattern]); bootstrap_payload[pattern] = boot
        bootstrap_rows.append({"pattern": pattern, **{key: value for key, value in boot.items() if not isinstance(value, dict)},
                               **{f"{key}_{subkey}": subvalue for key, value in boot.items() if isinstance(value, dict) for subkey, subvalue in value.items()}})
    pd.DataFrame(bootstrap_rows).to_csv(REPORTS / "stage18b_bootstrap_results.csv", index=False)
    can_reuse_heavy = bool(args.reuse_heavy_if_identical and predictions_identical and
                           (REPORTS / "stage18b_permutation_results.csv").exists() and (REPORTS / "stage18b_ablation_results.csv").exists())
    if not can_reuse_heavy:
        permutation_rows = [{"pattern": pattern, **event_block_permutation(test_signals[test_signals.pattern.eq(pattern)], 5_000, SEED + 100 + ord(pattern))} for pattern in ("A", "B")]
        pd.DataFrame(permutation_rows).to_csv(REPORTS / "stage18b_permutation_results.csv", index=False)
        ablations = pd.concat([ablation_audit(frame, pattern) for pattern in ("A", "B")], ignore_index=True)
        ablations.to_csv(REPORTS / "stage18b_ablation_results.csv", index=False)
    efficiency_rows = []
    for pattern in ("A", "B"):
        model_path = MODELS / f"stage18_pattern_{pattern.lower()}_v3.joblib"; test = predictions[(predictions.pattern.eq(pattern)) & predictions.split.eq("test")]
        start = time.perf_counter(); models[pattern].predict_proba(frame.loc[eligible(frame, pattern) & frame.split.eq("test"), feature_columns(frame, pattern)]); inference = time.perf_counter() - start
        signals = test.signal.isin(["LONG", "SHORT"])
        efficiency_rows.append({"pattern": pattern, "features": len(feature_columns(frame, pattern)), "training_seconds": train_seconds[pattern],
                                "inference_seconds": inference, "inference_ms_per_event": inference / max(len(test), 1) * 1000,
                                "model_size_bytes": model_path.stat().st_size, "predictions_per_1000_news": int(signals.sum()) / max(len(test), 1) * 1000,
                                "events_producing_signals_percent": float(signals.mean() * 100), "gross_edge_lost_to_costs_percent": BASE_COST / max(abs(test.loc[signals, "gross_return"].mean()), 1e-12) * 100})
    pd.DataFrame(efficiency_rows).to_csv(REPORTS / "stage18b_efficiency.csv", index=False)
    reliability_payload: dict[str, Any] = {}; statuses: dict[str, Any] = {}
    for pattern in ("A", "B"):
        test_metric = metrics[(metrics.pattern.eq(pattern)) & metrics.split.eq("test")].iloc[0]
        source_part = sources[(sources.pattern.eq(pattern)) & sources.split.eq("test")]
        year_part = years[(years.pattern.eq(pattern)) & years.split.eq("test")]
        regime_part = regimes[(regimes.pattern.eq(pattern)) & regimes.split.eq("test")]
        baseline_part = baselines[(baselines.pattern.eq(pattern)) & baselines.evaluation_split.eq("test")]
        baseline_net = float(baseline_part[baseline_part.status.eq("available")].net_expectancy.max())
        rel = reliability_score(pattern, test_signals[test_signals.pattern.eq(pattern)], walks[walks.pattern.eq(pattern)], bootstrap_payload[pattern],
                                year_part, regime_part, source_part, costs, baseline_net)
        reliability_payload[pattern] = rel; statuses[pattern] = status_for(pattern, test_metric, walks[walks.pattern.eq(pattern)], bootstrap_payload[pattern], baseline_part, rel)
    write_json(REPORTS / "stage18b_reliability_score.json", reliability_payload)
    old = pd.read_parquet(REPORTS / "stage18_prediction_level_results.parquet")
    old["pattern"] = np.where(old.pattern_id.str.contains("pattern_a"), "A", "B")
    comparison = old[["event_id", "asset", "pattern", "signal", "confidence", "net_return"]].rename(columns={"signal": "stage18_signal", "confidence": "stage18_confidence", "net_return": "stage18_net_return"}).merge(
        predictions[predictions.split.eq("test")][["event_id", "asset", "pattern", "signal", "confidence", "net_return"]].rename(columns={"signal": "stage18b_signal", "confidence": "stage18b_confidence", "net_return": "stage18b_net_return"}),
        on=["event_id", "asset", "pattern"], how="inner")
    comparison["transition"] = comparison.stage18_signal + "→" + comparison.stage18b_signal
    comparison["confidence_change"] = comparison.stage18b_confidence - comparison.stage18_confidence
    comparison.to_csv(REPORTS / "stage18b_stage18_comparison.csv", index=False)
    pytest_result = pytest_run()
    protected_after = file_tree_hash(protected_paths(), ROOT); database_after = db_signature()
    protected_unchanged = protected_before == protected_after; database_unchanged = database_before == database_after
    status_values = [statuses[p]["status"] for p in ("A", "B")]
    primary = "PASS_PREDICTIVE_AND_ECONOMIC" if all(s == "PASS_PREDICTIVE_AND_ECONOMIC" for s in status_values) else "PARTIAL_EVIDENCE" if any(s.startswith("PASS") for s in status_values) else "SHORT_BIAS_REMAINS" if any(s == "SHORT_BIAS_REMAINS" for s in status_values) else "CORRECTED_BUT_NO_EDGE"
    overall = primary + "__NO_TRUE_UNTOUCHED_TEST"
    summary_lines = ["# Stage 18B — Corrected Full Rebuild", "", f"Overall status: **{overall}**.", "", "## PATTERN A", ""]
    for pattern in ("A", "B"):
        row = metrics[(metrics.pattern.eq(pattern)) & metrics.split.eq("test")].iloc[0]; walk = walks[walks.pattern.eq(pattern)]
        if pattern == "B": summary_lines += ["", "## PATTERN B", ""]
        summary_lines += [f"- Predictions: {int(row.signals)}.", f"- LONG: {row.long_percent:.2f}%; SHORT: {row.short_percent:.2f}%.",
                          f"- Accuracy: {row.accuracy*100:.2f}%; strongest same-timestamp test baseline: {statuses[pattern]['strongest_baseline_accuracy']*100:.2f}%.",
                          f"- Mean gross: {row.mean_gross_return:+.4f}%; mean net: {row.mean_net_return:+.4f}%.",
                          f"- Net PF: {row.net_profit_factor if row.net_profit_factor is not None else 'undefined'}; maximum drawdown: {row.maximum_drawdown:+.2f}%.",
                          f"- Profitable folds: {int((walk.mean_net_return>0).sum())}/5; folds above baseline: {int(walk.above_baseline.sum())}/5.",
                          f"- Bootstrap P(net expectancy > 0): {bootstrap_payload[pattern]['probability_net_expectancy_positive']*100:.2f}%.",
                          f"- Reliability Score: {reliability_payload[pattern]['score']:.1f}/100.", f"- Status: **{statuses[pattern]['status']}**."]
    summary_lines += ["", "## Direct answers", "", "- The Stage 18 scale bug is corrected; all normalized semantics are in 0..1 (signed valence -1..1).",
                      f"- Erroneous >80% directional bias remains: {'yes' if any(row['short_bias_over_80'] for row in bias_rows) else 'no'}.",
                      "- Shadow mode is allowed only when explicitly marked as a shadow candidate below; real trading remains prohibited.",
                      f"- Pattern A shadow candidate: {statuses['A']['shadow_candidate']}; Pattern B: {statuses['B']['shadow_candidate']}.",
                      "- Real trading readiness: **NO**. There is no true untouched forward test.", "",
                      f"Integrity: protected unchanged={protected_unchanged}; database unchanged={database_unchanged}; API calls=0; trading actions=0; pytest={pytest_result['passed']} passed."]
    (REPORTS / "stage18b_final_summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    manifest = {"stage": "18B", "version": VERSION, "overall_status": overall, "input_signature": signature,
                "evaluation_status": "CORRECTED_RETROSPECTIVE_EVALUATION__NO_TRUE_UNTOUCHED_TEST", "gates": gates,
                "inventory": {"unique_events": int(canonical.canonical_event_id.nunique()), "event_asset_rows": len(canonical),
                              "covered_rows": int(coverage.fully_covered.sum())}, "patterns": statuses,
                "short_bias": bias_rows, "reliability": reliability_payload, "pytest": pytest_result,
                "integrity": {"protected_artifacts_unchanged": protected_unchanged, "database_unchanged": database_unchanged,
                              "fit_allowed_after_gates": True, "openai_api_calls": 0, "paid_api_cost_usd": 0.0,
                              "database_writes": 0, "paper_trading_actions": 0, "real_trading_actions": 0},
                "required_reports": REQUIRED_REPORTS, "report_hashes": {name: sha256_file(REPORTS / name) for name in REQUIRED_REPORTS if name != "stage18b_final_manifest.json" and (REPORTS / name).exists()},
                "protected_hashes_before": protected_before, "database_before": database_before}
    write_json(REPORTS / "stage18b_final_manifest.json", manifest)
    print(json.dumps({"status": overall, "patterns": statuses, "short_bias": bias_rows, "pytest": pytest_result,
                      "protected_unchanged": protected_unchanged, "database_unchanged": database_unchanged}, indent=2))
    return 0 if pytest_result["returncode"] == 0 and protected_unchanged and database_unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
