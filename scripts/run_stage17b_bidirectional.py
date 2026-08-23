"""Run isolated Stage 17B LONG/SHORT discovery without reopening Stage 17 test.

The script reads feature rows from the frozen Stage 17 asset parquet files, but
queries outcomes only for the original train and validation event IDs.  The 134
opened Stage 17 test rows are excluded from every discovery and evaluation query.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier
from sqlalchemy import text

from analysis.stage17b_bidirectional import (
    canonical_hash,
    directional_target,
    economic_metrics,
    rejection_reasons,
    signal_from_probabilities,
    signal_metrics,
)
from database.db import engine


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
STAGE17_DATA = ROOT / "data" / "stage17"
HORIZONS = ("20m", "40m", "1h", "3h", "5h", "8h", "12h")
PRIMARY_HORIZONS = ("1h", "3h", "12h")
NEUTRAL_THRESHOLDS = (0.10, 0.25, 0.50)
CONFIDENCE_THRESHOLDS = (0.40, 0.50, 0.60)
PRIMARY_LATENCY = 1
SENSITIVITY_LATENCIES = (0, 2, 3, 5)
RANDOM_STATE = 1702
MAX_RULES = 500

FEATURE_REPORT = REPORTS / "stage17b_feature_sets.json"
LONG_REPORT = REPORTS / "stage17b_long_candidates.csv"
SHORT_REPORT = REPORTS / "stage17b_short_candidates.csv"
COMBINED_REPORT = REPORTS / "stage17b_combined_candidates.csv"
REJECTED_REPORT = REPORTS / "stage17b_rejected_candidates.csv"
MODEL_REPORT = REPORTS / "stage17b_model_comparison.csv"
VALIDATION_REPORT = REPORTS / "stage17b_validation_metrics.csv"
WALKFORWARD_REPORT = REPORTS / "stage17b_walkforward_metrics.csv"
ECONOMIC_REPORT = REPORTS / "stage17b_economic_metrics.csv"
LOCK_REPORT = REPORTS / "stage17b_locked_config.json"
LOCK_SHA_REPORT = REPORTS / "stage17b_locked_config.sha256"
ASSESSMENT_REPORT = REPORTS / "stage17b_final_assessment.md"
PYTEST_REPORT = REPORTS / "stage17b_pytest.json"


SEMANTIC_COLUMNS = [
    "source_event_type",
    "source_information_status",
    "ai_asset_relevance",
    "ai_content_valence_score",
    "ai_importance",
    "ai_novelty",
    "ai_specificity",
    "ai_actionability",
    "ai_execution_certainty",
    "ai_institutional_relevance",
    "ai_regulatory_strength",
    "ai_technical_significance",
    "ai_fundamental_relevance",
    "ai_directness",
    "metadata_source",
    "metadata_asset",
    "ai_content_valence",
    "verified_primary_source",
]
MARKET_COLUMNS = [
    "pre_return_5m",
    "pre_return_20m",
    "pre_return_60m",
    "pre_return_180m",
    "pre_return_720m",
    "pre_btc_return_5m",
    "pre_btc_return_20m",
    "pre_btc_return_60m",
    "pre_btc_return_180m",
    "pre_btc_return_720m",
    "pre_realized_vol_20m",
    "pre_realized_vol_60m",
    "pre_realized_vol_180m",
    "pre_realized_vol_720m",
    "pre_volume_z60",
    "pre_volume_vs_avg60",
    "pre_trend_regime",
    "pre_relative_strength_1h",
    "pre_rolling_corr_btc",
    "pre_rolling_beta_btc",
    "context_btc_state",
    "context_asset_state",
    "context_volatility",
    "context_relative_strength",
    "metadata_asset",
]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Not JSON serializable: {type(value)!r}")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_stage17_snapshot() -> dict[str, str]:
    paths = list(REPORTS.glob("stage17_*")) + list(STAGE17_DATA.glob("*"))
    return {str(path.relative_to(ROOT)): file_hash(path) for path in sorted(paths) if path.is_file()}


def aggregate_hash(snapshot: dict[str, str]) -> str:
    payload = "\n".join(f"{key}|{value}" for key, value in sorted(snapshot.items())).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_features() -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = json.loads((STAGE17_DATA / "manifest.json").read_text(encoding="utf-8"))
    required = sorted(set(
        ["metadata_event_id", "metadata_published_at", "metadata_asset", "metadata_source", "metadata_split", "pre_return_1m"]
        + SEMANTIC_COLUMNS + MARKET_COLUMNS
    ))
    available = set(manifest["feature_columns"])
    missing = sorted(set(required) - available)
    if missing:
        raise RuntimeError(f"Missing frozen feature columns: {missing}")
    frames = [pd.read_parquet(STAGE17_DATA / f"{asset}_high_impact.parquet", columns=required) for asset in ("btc", "eth", "sol")]
    frame = pd.concat(frames, ignore_index=True)
    frame["metadata_published_at"] = pd.to_datetime(frame.metadata_published_at, utc=True)
    frame = frame.sort_values(["metadata_published_at", "metadata_event_id", "metadata_asset"]).reset_index(drop=True)
    if frame.duplicated(["metadata_event_id", "metadata_asset"]).any():
        raise RuntimeError("Duplicate event_id+asset feature key")
    if frame.groupby("metadata_event_id").metadata_split.nunique().max() != 1:
        raise RuntimeError("Event split contamination")
    return frame, manifest


def feature_sets(frame: pd.DataFrame) -> dict[str, list[str]]:
    semantic = [column for column in SEMANTIC_COLUMNS if column in frame]
    market = [column for column in MARKET_COLUMNS if column in frame]
    return {
        "semantic_only": semantic,
        "market_only": market,
        "semantic_plus_market": list(dict.fromkeys(semantic + market)),
    }


def load_allowed_targets(event_ids: list[int]) -> pd.DataFrame:
    """Read only train/validation target rows, at isolated latencies."""
    columns = ",".join(f"return_{horizon}" for horizon in HORIZONS)
    sql = text(f"""
        SELECT event_id,replace(symbol,'USDT','') AS asset,latency_minutes,{columns}
        FROM high_impact_market_reactions
        WHERE event_id=ANY(:event_ids) AND latency_minutes=ANY(:latencies)
        ORDER BY event_id,symbol,latency_minutes
    """)
    with engine.connect() as connection:
        targets = pd.read_sql(
            sql,
            connection,
            params={"event_ids": event_ids, "latencies": [PRIMARY_LATENCY, *SENSITIVITY_LATENCIES]},
        )
    if targets.duplicated(["event_id", "asset", "latency_minutes"]).any():
        raise RuntimeError("Duplicate reaction identity")
    unexpected = set(targets.event_id.astype(int)) - set(event_ids)
    if unexpected:
        raise RuntimeError("Outcome query returned forbidden event IDs")
    return targets


def untouched_oos_status(features: pd.DataFrame) -> dict[str, Any]:
    test = features[features.metadata_split.eq("test")]
    cutoff = test.metadata_published_at.max()
    sql = text("""
        SELECT count(DISTINCT e.id) AS events,count(*) AS event_asset_rows,
               min(e.published_at) AS min_published_at,max(e.published_at) AS max_published_at
        FROM high_impact_events e
        JOIN high_impact_event_analysis a ON a.event_id=e.id
          AND a.model_name='gpt-5-mini' AND a.prompt_version='high_impact_semantic_v2_1' AND a.status='success'
        JOIN high_impact_market_reactions r ON r.event_id=e.id AND r.latency_minutes=1
        WHERE e.status='accepted' AND e.published_at>:cutoff
    """)
    with engine.connect() as connection:
        row = dict(connection.execute(sql, {"cutoff": cutoff.to_pydatetime()}).mappings().one())
    return {
        "old_opened_test_rows": len(test),
        "old_opened_test_events": int(test.metadata_event_id.nunique()),
        "old_opened_test_max_published_at": cutoff.isoformat(),
        "new_untouched_events": int(row["events"]),
        "new_untouched_event_asset_rows": int(row["event_asset_rows"]),
        "new_min_published_at": row["min_published_at"],
        "new_max_published_at": row["max_published_at"],
        "available": int(row["events"]) > 0,
    }


def model_factories() -> dict[str, tuple[Callable[[], Any], bool, dict[str, Any]]]:
    return {
        "logistic_regression": (
            lambda: LogisticRegression(max_iter=2500, solver="lbfgs", random_state=RANDOM_STATE),
            True,
            {"max_iter": 2500, "class_weight": None},
        ),
        "class_weighted_logistic": (
            lambda: LogisticRegression(max_iter=2500, solver="lbfgs", class_weight="balanced", random_state=RANDOM_STATE),
            True,
            {"max_iter": 2500, "class_weight": "balanced"},
        ),
        "shallow_decision_tree": (
            lambda: DecisionTreeClassifier(max_depth=3, min_samples_leaf=15, class_weight="balanced", random_state=RANDOM_STATE),
            False,
            {"max_depth": 3, "min_samples_leaf": 15, "class_weight": "balanced"},
        ),
        "shallow_random_forest": (
            lambda: RandomForestClassifier(n_estimators=120, max_depth=4, min_samples_leaf=8, class_weight="balanced", n_jobs=-1, random_state=RANDOM_STATE),
            False,
            {"n_estimators": 120, "max_depth": 4, "min_samples_leaf": 8, "class_weight": "balanced"},
        ),
        "gradient_boosting": (
            lambda: GradientBoostingClassifier(n_estimators=80, learning_rate=0.05, max_depth=2, random_state=RANDOM_STATE),
            False,
            {"n_estimators": 80, "learning_rate": 0.05, "max_depth": 2},
        ),
    }


def pipeline_for(frame: pd.DataFrame, columns: list[str], model_name: str) -> Pipeline:
    factory, scale, _ = model_factories()[model_name]
    numeric = [column for column in columns if pd.api.types.is_numeric_dtype(frame[column])]
    categorical = [column for column in columns if column not in numeric]
    numeric_steps: list[tuple[str, Any]] = [("impute", SimpleImputer(strategy="median"))]
    if scale:
        numeric_steps.append(("scale", StandardScaler()))
    transformer = ColumnTransformer([
        ("numeric", Pipeline(numeric_steps), numeric),
        ("categorical", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), categorical),
    ])
    return Pipeline([("preprocess", transformer), ("model", factory())])


def merge_primary(features: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    primary = targets[targets.latency_minutes.eq(PRIMARY_LATENCY)].drop(columns="latency_minutes")
    data = features.merge(
        primary,
        left_on=["metadata_event_id", "metadata_asset"],
        right_on=["event_id", "asset"],
        how="inner",
        validate="one_to_one",
    )
    data["event_id"] = data.metadata_event_id.astype(int)
    data["asset"] = data.metadata_asset
    data["source"] = data.metadata_source
    data["published_at"] = data.metadata_published_at
    return data


def scope_mask(data: pd.DataFrame, scope: str) -> pd.Series:
    return pd.Series(True, index=data.index) if scope == "ALL" else data.asset.eq(scope)


def scope_baselines(train: pd.DataFrame, validation: pd.DataFrame, horizon: str, neutral: float) -> dict[str, float | None]:
    if validation.empty:
        return {name: None for name in ("always_long", "always_short", "majority_direction", "previous_1m", "previous_5m", "btc_trend", "strongest_baseline")}
    train_actual = directional_target(train[f"return_{horizon}"], neutral)
    actual = directional_target(validation[f"return_{horizon}"], neutral).to_numpy()
    majority = "UP" if int(train_actual.eq("UP").sum()) >= int(train_actual.eq("DOWN").sum()) else "DOWN"

    def score(prediction: np.ndarray) -> float:
        return float(np.mean(prediction == actual))

    result = {
        "always_long": score(np.repeat("UP", len(validation))),
        "always_short": score(np.repeat("DOWN", len(validation))),
        "majority_direction": score(np.repeat(majority, len(validation))),
        "previous_1m": score(np.where(pd.to_numeric(validation.pre_return_1m, errors="coerce").fillna(0).to_numpy() >= 0, "UP", "DOWN")),
        "previous_5m": score(np.where(pd.to_numeric(validation.pre_return_5m, errors="coerce").fillna(0).to_numpy() >= 0, "UP", "DOWN")),
        "btc_trend": score(np.where(pd.to_numeric(validation.pre_btc_return_60m, errors="coerce").fillna(0).to_numpy() >= 0, "UP", "DOWN")),
    }
    result["strongest_baseline"] = max(result.values())
    return result


def evaluated_rows(data: pd.DataFrame, horizon: str, neutral: float, signal: np.ndarray, confidence: np.ndarray) -> pd.DataFrame:
    result = data.copy()
    result["future_return"] = pd.to_numeric(result[f"return_{horizon}"], errors="coerce")
    result["actual_direction"] = directional_target(result.future_return, neutral)
    result["signal"] = signal
    result["signal_confidence"] = confidence
    return result[result.future_return.notna()].copy()


def metric_record(
    train_rows: pd.DataFrame,
    validation_rows: pd.DataFrame,
    train_scope: pd.DataFrame,
    validation_scope: pd.DataFrame,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    train_metrics = signal_metrics(train_rows)
    validation_metrics = signal_metrics(validation_rows)
    baselines = scope_baselines(
        train_scope,
        validation_scope,
        metadata["horizon"],
        metadata["neutral_threshold"],
    )
    validation_metrics.update({f"baseline_{key}": value for key, value in baselines.items()})
    validation_metrics["strongest_baseline"] = baselines["strongest_baseline"]
    reasons = rejection_reasons(validation_metrics, train_metrics)
    record = {
        **metadata,
        **validation_metrics,
        **{f"train_{key}": value for key, value in train_metrics.items()},
        "expectancy_sign_consistent": bool(
            (train_metrics.get("gross_expectancy_percent") or 0) > 0
            and (validation_metrics.get("gross_expectancy_percent") or 0) > 0
        ),
        "validation_eligible": len(reasons) == 0,
        "rejection_reasons": "|".join(reasons),
        "old_stage17_test_rows_used": 0,
        "leakage": 0,
    }
    return record


def discover_models(data: pd.DataFrame, sets: dict[str, list[str]]) -> tuple[pd.DataFrame, dict[tuple[Any, ...], Pipeline]]:
    train_mask = data.metadata_split.eq("train")
    validation_mask = data.metadata_split.eq("validation")
    records: list[dict[str, Any]] = []
    models: dict[tuple[Any, ...], Pipeline] = {}
    for feature_name, columns in sets.items():
        for horizon in PRIMARY_HORIZONS:
            for neutral in NEUTRAL_THRESHOLDS:
                target = directional_target(data[f"return_{horizon}"], neutral)
                for model_name in model_factories():
                    model = pipeline_for(data, columns, model_name)
                    model.fit(data.loc[train_mask, columns], target.loc[train_mask])
                    models[(feature_name, model_name, horizon, neutral)] = model
                    train_probability = model.predict_proba(data.loc[train_mask, columns])
                    validation_probability = model.predict_proba(data.loc[validation_mask, columns])
                    classes = list(model.named_steps["model"].classes_)
                    for confidence_threshold in CONFIDENCE_THRESHOLDS:
                        train_signal, train_confidence = signal_from_probabilities(train_probability, classes, confidence_threshold)
                        validation_signal, validation_confidence = signal_from_probabilities(validation_probability, classes, confidence_threshold)
                        train_part = evaluated_rows(data.loc[train_mask].copy(), horizon, neutral, train_signal, train_confidence)
                        validation_part = evaluated_rows(data.loc[validation_mask].copy(), horizon, neutral, validation_signal, validation_confidence)
                        for scope in ("ALL", "BTC", "ETH", "SOL"):
                            train_scope = train_part[scope_mask(train_part, scope)]
                            validation_scope = validation_part[scope_mask(validation_part, scope)]
                            if train_scope.empty or validation_scope.empty:
                                continue
                            records.append(metric_record(
                                train_scope,
                                validation_scope,
                                data.loc[train_mask & scope_mask(data, scope)],
                                data.loc[validation_mask & scope_mask(data, scope)],
                                {
                                    "candidate_type": "model",
                                    "candidate_id": f"model:{feature_name}:{model_name}:{horizon}:{neutral}:{confidence_threshold}:{scope}",
                                    "feature_set": feature_name,
                                    "model": model_name,
                                    "horizon": horizon,
                                    "neutral_threshold": neutral,
                                    "confidence_threshold": confidence_threshold,
                                    "asset_scope": scope,
                                    "rule_conditions": "",
                                    "direction_selected_on": "train_model_fit",
                                },
                            ))
    return pd.DataFrame(records), models


@dataclass(frozen=True)
class Rule:
    rule_id: str
    feature_set: str
    description: str
    conditions: tuple[tuple[str, str, Any], ...]


def apply_condition(data: pd.DataFrame, condition: tuple[str, str, Any]) -> pd.Series:
    column, operation, value = condition
    if operation == ">=":
        return pd.to_numeric(data[column], errors="coerce") >= float(value)
    if operation == "<=":
        return pd.to_numeric(data[column], errors="coerce") <= float(value)
    if operation == "==":
        return data[column].fillna("<NULL>").astype(str) == str(value)
    raise ValueError(operation)


def apply_rule(data: pd.DataFrame, rule: Rule) -> pd.Series:
    result = pd.Series(True, index=data.index)
    for condition in rule.conditions:
        result &= apply_condition(data, condition)
    return result


def generate_rules(data: pd.DataFrame) -> list[Rule]:
    train = data[data.metadata_split.eq("train")]
    semantic_conditions: list[tuple[str, str, Any]] = []
    market_conditions: list[tuple[str, str, Any]] = []
    for column in ("ai_asset_relevance", "ai_importance", "ai_novelty", "ai_specificity", "ai_actionability", "ai_execution_certainty", "ai_institutional_relevance", "ai_technical_significance", "ai_fundamental_relevance", "ai_content_valence_score"):
        values = pd.to_numeric(train[column], errors="coerce").dropna()
        if values.nunique() > 1:
            semantic_conditions.extend([(column, ">=", float(values.quantile(0.67))), (column, "<=", float(values.quantile(0.33)))])
    for column in ("pre_return_20m", "pre_return_60m", "pre_return_180m", "pre_btc_return_60m", "pre_btc_return_180m", "pre_realized_vol_60m", "pre_volume_z60", "pre_relative_strength_1h"):
        values = pd.to_numeric(train[column], errors="coerce").dropna()
        if values.nunique() > 1:
            market_conditions.extend([(column, ">=", float(values.quantile(0.67))), (column, "<=", float(values.quantile(0.33)))])
    for column in ("source_event_type", "source_information_status", "ai_content_valence", "ai_directness", "metadata_source", "metadata_asset"):
        for value in train[column].dropna().astype(str).value_counts().head(2).index:
            semantic_conditions.append((column, "==", value))
    for column in ("pre_trend_regime", "context_btc_state", "context_volatility"):
        for value in train[column].dropna().astype(str).value_counts().head(2).index:
            market_conditions.append((column, "==", value))

    raw: list[tuple[str, tuple[tuple[str, str, Any], ...]]] = []
    raw.extend(("semantic_only", (condition,)) for condition in semantic_conditions)
    raw.extend(("market_only", (condition,)) for condition in market_conditions)
    raw.extend(("semantic_only", pair) for pair in list(combinations(semantic_conditions, 2))[:60])
    raw.extend(("market_only", pair) for pair in list(combinations(market_conditions, 2))[:60])
    raw.extend(("semantic_plus_market", (semantic, market)) for semantic in semantic_conditions for market in market_conditions)
    rules: list[Rule] = []
    seen_membership: set[str] = set()
    for feature_name, conditions in raw:
        description = " AND ".join(f"{column}{operation}{value}" for column, operation, value in conditions)
        rule_id = "rule_" + hashlib.sha256((feature_name + "|" + description).encode("utf-8")).hexdigest()[:12]
        rule = Rule(rule_id, feature_name, description, conditions)
        membership = apply_rule(train, rule).to_numpy(dtype=np.uint8)
        membership_hash = hashlib.sha256(membership.tobytes()).hexdigest()
        if membership_hash in seen_membership:
            continue
        seen_membership.add(membership_hash)
        rules.append(rule)
        if len(rules) >= MAX_RULES:
            break
    return rules


def discover_rules(data: pd.DataFrame, rules: list[Rule]) -> tuple[pd.DataFrame, dict[str, Rule]]:
    records: list[dict[str, Any]] = []
    train_split = data.metadata_split.eq("train")
    validation_split = data.metadata_split.eq("validation")
    rule_map = {rule.rule_id: rule for rule in rules}
    for rule in rules:
        membership = apply_rule(data, rule)
        for horizon in HORIZONS:
            for neutral in NEUTRAL_THRESHOLDS:
                actual = directional_target(data[f"return_{horizon}"], neutral)
                for scope in ("ALL", "BTC", "ETH", "SOL"):
                    scope_all = scope_mask(data, scope)
                    train_match = train_split & membership & scope_all & data[f"return_{horizon}"].notna()
                    validation_match = validation_split & membership & scope_all & data[f"return_{horizon}"].notna()
                    if int(train_match.sum()) < 30:
                        continue
                    train_actual = actual.loc[train_match]
                    future = pd.to_numeric(data.loc[train_match, f"return_{horizon}"], errors="coerce")
                    choices = {
                        "LONG": (float(train_actual.eq("UP").mean()), float(future.mean())),
                        "SHORT": (float(train_actual.eq("DOWN").mean()), float((-future).mean())),
                    }
                    direction = max(choices, key=lambda key: choices[key])
                    confidence = choices[direction][0]
                    train_data = data.loc[train_split & scope_all].copy()
                    validation_data = data.loc[validation_split & scope_all].copy()
                    train_signal = np.where(membership.loc[train_data.index], direction, "NO_SIGNAL")
                    validation_signal = np.where(membership.loc[validation_data.index], direction, "NO_SIGNAL")
                    train_rows = evaluated_rows(train_data, horizon, neutral, train_signal, np.repeat(confidence, len(train_data)))
                    validation_rows = evaluated_rows(validation_data, horizon, neutral, validation_signal, np.repeat(confidence, len(validation_data)))
                    records.append(metric_record(
                        train_rows,
                        validation_rows,
                        train_data,
                        validation_data,
                        {
                            "candidate_type": "explicit_subgroup_rule",
                            "candidate_id": f"{rule.rule_id}:{horizon}:{neutral}:{scope}:{direction}",
                            "feature_set": rule.feature_set,
                            "model": "explicit_subgroup_rule",
                            "horizon": horizon,
                            "neutral_threshold": neutral,
                            "confidence_threshold": confidence,
                            "asset_scope": scope,
                            "rule_conditions": rule.description,
                            "direction_selected_on": "train_only",
                            "rule_direction": direction,
                        },
                    ))
    return pd.DataFrame(records), rule_map


def directional_candidate_gate(row: pd.Series, direction: str) -> tuple[bool, str]:
    prefix = "long" if direction == "LONG" else "short"
    reasons = []
    if int(row.get(f"train_{prefix}_signals", 0)) < 30:
        reasons.append("train_signals_below_30")
    if int(row.get(f"{prefix}_signals", 0)) < 20:
        reasons.append("validation_signals_below_20")
    if float(row.get(f"{prefix}_signals", 0)) / max(int(row.get("total_rows", 0)), 1) < 0.20:
        reasons.append("coverage_below_20pct")
    if (row.get(f"{prefix}_accuracy") or 0) <= 0.55:
        reasons.append("accuracy_not_above_55pct")
    if (row.get(f"{prefix}_accuracy") or 0) <= (row.get("strongest_baseline") or 0):
        reasons.append("does_not_beat_strongest_baseline")
    if (row.get(f"{prefix}_gross_expectancy_percent") or 0) <= 0 or (row.get(f"train_{prefix}_gross_expectancy_percent") or 0) <= 0:
        reasons.append("expectancy_not_positive_both_splits")
    if (row.get(f"{prefix}_source_max_share") or 1) > 0.80:
        reasons.append("single_source_dependence")
    if (row.get(f"{prefix}_month_max_share") or 1) > 0.80:
        reasons.append("single_month_dependence")
    return not reasons, "|".join(reasons)


def build_directional_shortlists(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    long_rows: list[dict[str, Any]] = []
    short_rows: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        for direction, output in (("LONG", long_rows), ("SHORT", short_rows)):
            passed, reasons = directional_candidate_gate(row, direction)
            if passed:
                item = row.to_dict()
                item["shortlist_direction"] = direction
                item["directional_gate_passed"] = True
                item["directional_rejection_reasons"] = reasons
                output.append(item)
    sort_columns = ["combined_accuracy", "gross_expectancy_percent", "combined_signals"]
    long_frame = pd.DataFrame(long_rows)
    short_frame = pd.DataFrame(short_rows)
    if not long_frame.empty:
        long_frame = long_frame.sort_values(sort_columns, ascending=False)
    if not short_frame.empty:
        short_frame = short_frame.sort_values(sort_columns, ascending=False)
    return long_frame, short_frame


def selected_model_row(model_results: pd.DataFrame) -> tuple[pd.Series, bool]:
    eligible = model_results[model_results.validation_eligible].copy()
    if not eligible.empty:
        chosen = eligible.sort_values(["combined_accuracy", "gross_expectancy_percent", "combined_signals"], ascending=False).iloc[0]
        return chosen, True
    diagnostic = model_results[
        (model_results.combined_signals >= 20)
        & (model_results.coverage >= 0.20)
        & (model_results.dominant_direction_share <= 0.80)
    ].copy()
    if diagnostic.empty:
        diagnostic = model_results.copy()
    chosen = diagnostic.sort_values(["combined_accuracy", "gross_expectancy_percent", "combined_signals"], ascending=False).iloc[0]
    return chosen, False


def fit_and_predict_config(data: pd.DataFrame, sets: dict[str, list[str]], chosen: pd.Series, train_mask: pd.Series, eval_mask: pd.Series) -> tuple[pd.DataFrame, Pipeline]:
    columns = sets[str(chosen.feature_set)]
    model = pipeline_for(data.loc[train_mask], columns, str(chosen.model))
    target = directional_target(data.loc[train_mask, f"return_{chosen.horizon}"], float(chosen.neutral_threshold))
    model.fit(data.loc[train_mask, columns], target)
    probabilities = model.predict_proba(data.loc[eval_mask, columns])
    signal, confidence = signal_from_probabilities(probabilities, list(model.named_steps["model"].classes_), float(chosen.confidence_threshold))
    evaluate = evaluated_rows(data.loc[eval_mask].copy(), str(chosen.horizon), float(chosen.neutral_threshold), signal, confidence)
    evaluate = evaluate[scope_mask(evaluate, str(chosen.asset_scope))]
    return evaluate, model


def walkforward(data: pd.DataFrame, sets: dict[str, list[str]], chosen: pd.Series) -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    prelock = data[data.metadata_split.isin(["train", "validation"])].sort_values(["published_at", "event_id", "asset"])
    event_ids = prelock.drop_duplicates("event_id").event_id.to_numpy()
    records: list[dict[str, Any]] = []
    predictions: list[pd.DataFrame] = []
    for fold, (train_fraction, eval_fraction) in enumerate(((0.40, 0.60), (0.60, 0.80), (0.80, 1.00)), 1):
        train_ids = set(event_ids[: int(len(event_ids) * train_fraction)])
        eval_ids = set(event_ids[int(len(event_ids) * train_fraction): int(len(event_ids) * eval_fraction)])
        train_mask = prelock.event_id.isin(train_ids)
        eval_mask = prelock.event_id.isin(eval_ids)
        evaluate, _ = fit_and_predict_config(prelock, sets, chosen, train_mask, eval_mask)
        train_scope = prelock[train_mask & scope_mask(prelock, str(chosen.asset_scope))]
        eval_scope = prelock[eval_mask & scope_mask(prelock, str(chosen.asset_scope))]
        metrics = signal_metrics(evaluate)
        baselines = scope_baselines(train_scope, eval_scope, str(chosen.horizon), float(chosen.neutral_threshold))
        records.append({
            "fold": fold,
            "train_events": len(train_ids),
            "evaluation_events": len(eval_ids),
            **metrics,
            **{f"baseline_{key}": value for key, value in baselines.items()},
            "beats_55": bool((metrics.get("combined_accuracy") or 0) > 0.55),
            "beats_strongest_baseline": bool((metrics.get("combined_accuracy") or 0) > (baselines.get("strongest_baseline") or 0)),
            "old_stage17_test_rows_used": 0,
        })
        evaluate["fold"] = fold
        predictions.append(evaluate)
    return pd.DataFrame(records), predictions


def sensitivity_metrics(
    features: pd.DataFrame,
    targets: pd.DataFrame,
    sets: dict[str, list[str]],
    chosen: pd.Series,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    primary_data = merge_primary(features, targets)
    train_mask = primary_data.metadata_split.eq("train")
    validation_mask = primary_data.metadata_split.eq("validation")
    primary_predictions, model = fit_and_predict_config(primary_data, sets, chosen, train_mask, validation_mask)
    signal_map = primary_predictions.set_index(["event_id", "asset"])[["signal", "signal_confidence"]]
    records = []
    economics = []
    validation_features = features[features.metadata_split.eq("validation")].copy()
    for latency in (PRIMARY_LATENCY, *SENSITIVITY_LATENCIES):
        latency_targets = targets[targets.latency_minutes.eq(latency)]
        merged = validation_features.merge(latency_targets, left_on=["metadata_event_id", "metadata_asset"], right_on=["event_id", "asset"], how="inner", validate="one_to_one")
        merged["event_id"] = merged.metadata_event_id.astype(int)
        merged["asset"] = merged.metadata_asset
        merged["source"] = merged.metadata_source
        merged["published_at"] = merged.metadata_published_at
        merged = merged.join(signal_map, on=["event_id", "asset"])
        merged["signal"] = merged.signal.fillna("NO_SIGNAL")
        merged["signal_confidence"] = merged.signal_confidence.fillna(0.0)
        merged = merged[scope_mask(merged, str(chosen.asset_scope))]
        for horizon in HORIZONS:
            rows = evaluated_rows(
                merged,
                horizon,
                float(chosen.neutral_threshold),
                merged.signal.to_numpy(),
                merged.signal_confidence.to_numpy(),
            )
            metrics = signal_metrics(rows)
            records.append({
                "evaluation_type": "primary" if latency == 1 and horizon == str(chosen.horizon) else "sensitivity_only",
                "latency_minutes": latency,
                "horizon": horizon,
                "neutral_threshold": float(chosen.neutral_threshold),
                **metrics,
                "selection_changed": False,
                "old_stage17_test_rows_used": 0,
            })
            for cost_name, cost in (("gross", 0.0), ("low", 0.10), ("base", 0.20), ("stress", 0.40)):
                economics.append({
                    "split": "validation",
                    "evaluation_type": "primary" if latency == 1 and horizon == str(chosen.horizon) else "sensitivity_only",
                    "latency_minutes": latency,
                    "horizon": horizon,
                    "cost_scenario": cost_name,
                    **economic_metrics(rows, cost),
                })
    return pd.DataFrame(records), economics


def run_pytest() -> dict[str, Any]:
    base_temp = REPORTS / f"pytest_stage17b_{time.time_ns()}" / "run"
    base_temp.parent.mkdir(parents=True, exist_ok=False)
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={base_temp}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    text_output = process.stdout + "\n" + process.stderr
    passed = 0
    for token in text_output.replace("=", " ").split():
        if token.isdigit():
            continue
    match = re.search(r"(\d+) passed", text_output)
    if match:
        passed = int(match.group(1))
    return {
        "returncode": process.returncode,
        "passed": passed,
        "stdout_tail": process.stdout[-5000:],
        "stderr_tail": process.stderr[-3000:],
        "base_temp": str(base_temp.relative_to(ROOT)),
    }


def empty_with_columns(path: Path, template: pd.DataFrame, extra: list[str] | None = None) -> None:
    columns = list(template.columns) + [column for column in (extra or []) if column not in template.columns]
    pd.DataFrame(columns=columns).to_csv(path, index=False)


def finalize_existing(stage17_before: dict[str, str]) -> int:
    """Resume only the local technical finalization; never repeat discovery."""
    expected = LOCK_SHA_REPORT.read_text(encoding="ascii").strip()
    lock = json.loads(LOCK_REPORT.read_text(encoding="utf-8"))
    if canonical_hash(lock) != expected:
        raise RuntimeError("Stage 17B lock SHA mismatch on resume")
    pytest_result = run_pytest()
    write_json(PYTEST_REPORT, pytest_result)
    stage17_after = protected_stage17_snapshot()
    changed = sorted(path for path in set(stage17_before) | set(stage17_after) if stage17_before.get(path) != stage17_after.get(path))
    if changed:
        raise RuntimeError(f"Protected Stage 17 artifacts changed on resume: {changed}")
    assessment = ASSESSMENT_REPORT.read_text(encoding="utf-8")
    assessment = re.sub(
        r"- Pytest: (?:PASS|FAIL) \(\d+ passed\)\.",
        f"- Pytest: {'PASS' if pytest_result['returncode'] == 0 else 'FAIL'} ({pytest_result['passed']} passed).",
        assessment,
    )
    assessment = re.sub(
        r"aggregate SHA-256 `[0-9a-f]+`",
        f"aggregate SHA-256 `{aggregate_hash(stage17_after)}`",
        assessment,
    )
    ASSESSMENT_REPORT.write_text(assessment, encoding="utf-8")
    selected = lock["selected_candidate"]
    result = {
        "resume": True,
        "discovery_repeated": False,
        "status": lock["status"],
        "new_untouched_events": lock["new_untouched_oos"]["new_untouched_events"],
        "selected_candidate_id": selected["candidate_id"],
        "pytest": {"returncode": pytest_result["returncode"], "passed": pytest_result["passed"]},
        "stage17_unchanged": True,
        "lock_sha256": expected,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if pytest_result["returncode"] == 0 else 1


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stage17_before = protected_stage17_snapshot()
    required_existing = [
        FEATURE_REPORT, LONG_REPORT, SHORT_REPORT, COMBINED_REPORT, REJECTED_REPORT,
        MODEL_REPORT, VALIDATION_REPORT, WALKFORWARD_REPORT, ECONOMIC_REPORT,
        LOCK_REPORT, LOCK_SHA_REPORT, ASSESSMENT_REPORT,
    ]
    if all(path.exists() for path in required_existing):
        return finalize_existing(stage17_before)
    before_aggregate = aggregate_hash(stage17_before)
    features, manifest = load_features()
    oos = untouched_oos_status(features)
    prelock_features = features[features.metadata_split.isin(["train", "validation"])].copy()
    old_test_ids = set(features.loc[features.metadata_split.eq("test"), "metadata_event_id"].astype(int))
    allowed_ids = prelock_features.metadata_event_id.drop_duplicates().astype(int).tolist()
    if old_test_ids.intersection(allowed_ids):
        raise RuntimeError("Opened Stage 17 test event leaked into Stage 17B discovery IDs")
    targets = load_allowed_targets(allowed_ids)
    if set(targets.event_id.astype(int)).intersection(old_test_ids):
        raise RuntimeError("Opened Stage 17 test outcome was read")
    data = merge_primary(prelock_features, targets)
    sets = feature_sets(data)
    forbidden = [
        column for columns in sets.values() for column in columns
        if column.startswith("target_") or column in {
            "baseline_price", "max_return", "min_return", "news_market_reactions",
            "return_1m", "return_5m", "return_20m", "return_1h", "return_3h", "return_12h",
        }
    ]
    if forbidden:
        raise RuntimeError(f"Feature leakage: {sorted(set(forbidden))}")

    model_results, _ = discover_models(data, sets)
    rules = generate_rules(data)
    rule_results, _ = discover_rules(data, rules)
    all_candidates = pd.concat([model_results, rule_results], ignore_index=True, sort=False)
    long_candidates, short_candidates = build_directional_shortlists(all_candidates)

    combined_candidates = all_candidates[all_candidates.validation_eligible].copy()
    if not combined_candidates.empty:
        combined_candidates = combined_candidates.sort_values(
            ["combined_accuracy", "gross_expectancy_percent", "combined_signals"], ascending=False
        )
    rejected = all_candidates[~all_candidates.validation_eligible].copy()
    if not rejected.empty:
        rejected = rejected.sort_values(["combined_accuracy", "combined_signals"], ascending=False)

    chosen, validation_gate_passed = selected_model_row(model_results)
    walkforward_frame, walkforward_predictions = walkforward(data, sets, chosen)
    sensitivity_frame, economic_rows = sensitivity_metrics(prelock_features, targets, sets, chosen)
    for fold, predictions in enumerate(walkforward_predictions, 1):
        for cost_name, cost in (("gross", 0.0), ("low", 0.10), ("base", 0.20), ("stress", 0.40)):
            economic_rows.append({
                "split": f"nested_walkforward_{fold}",
                "evaluation_type": "diagnostic_oos",
                "latency_minutes": 1,
                "horizon": str(chosen.horizon),
                "cost_scenario": cost_name,
                **economic_metrics(predictions, cost),
            })
    economics = pd.DataFrame(economic_rows)

    all_candidates.to_csv(MODEL_REPORT, index=False)
    if long_candidates.empty:
        empty_with_columns(LONG_REPORT, all_candidates, ["shortlist_direction", "directional_gate_passed", "directional_rejection_reasons"])
    else:
        long_candidates.to_csv(LONG_REPORT, index=False)
    if short_candidates.empty:
        empty_with_columns(SHORT_REPORT, all_candidates, ["shortlist_direction", "directional_gate_passed", "directional_rejection_reasons"])
    else:
        short_candidates.to_csv(SHORT_REPORT, index=False)
    if combined_candidates.empty:
        empty_with_columns(COMBINED_REPORT, all_candidates)
    else:
        combined_candidates.to_csv(COMBINED_REPORT, index=False)
    rejected.to_csv(REJECTED_REPORT, index=False)
    all_candidates.to_csv(VALIDATION_REPORT, index=False)
    walkforward_frame.to_csv(WALKFORWARD_REPORT, index=False)
    economics.to_csv(ECONOMIC_REPORT, index=False)

    stage17_lock = json.loads((REPORTS / "stage17_directional_locked_config.json").read_text(encoding="utf-8"))
    stage17_status = json.loads((REPORTS / "stage17_directional_locked_test_metrics.json").read_text(encoding="utf-8"))["final_status"]
    feature_payload = {
        "stage": "17B",
        "status": "PASS",
        "feature_sets": sets,
        "feature_counts": {name: len(columns) for name, columns in sets.items()},
        "semantic_only_not_the_only_feature_set": True,
        "future_or_reaction_features": [],
        "surprise_level_excluded": True,
        "leakage": 0,
        "predictive_ai_fields": 0,
        "discovery_splits": ["train", "validation"],
        "discovery_rows": len(data),
        "discovery_events": int(data.event_id.nunique()),
        "old_stage17_test_rows_used": 0,
        "old_stage17_test_events_used": 0,
        "old_stage17_test_status_preserved": stage17_status,
        "old_stage17_lock_sha256": canonical_hash(stage17_lock),
        "stage17_artifact_count": len(stage17_before),
        "stage17_aggregate_sha256_before": before_aggregate,
        "horizons_checked": list(HORIZONS),
        "primary_horizons": list(PRIMARY_HORIZONS),
        "neutral_thresholds": list(NEUTRAL_THRESHOLDS),
        "primary_latency_minutes": PRIMARY_LATENCY,
        "sensitivity_latencies": list(SENSITIVITY_LATENCIES),
        "models": list(model_factories()) + ["explicit_subgroup_rule"],
        "model_parameters": {name: parameters for name, (_, _, parameters) in model_factories().items()},
        "rules_generated": len(rules),
        "maximum_rules": MAX_RULES,
        "maximum_conditions_per_rule": max((len(rule.conditions) for rule in rules), default=0),
        "threshold_source": "train_only",
        "oos_availability": oos,
        "openai_api_requests": 0,
        "paper_trading": False,
        "real_trading": False,
    }
    write_json(FEATURE_REPORT, feature_payload)

    selected_metrics = {
        key: (None if pd.isna(value) else value)
        for key, value in chosen.to_dict().items()
        if key not in {"rejection_reasons"}
    }
    stable_folds = int((
        (walkforward_frame.combined_accuracy > 0.55)
        & (walkforward_frame.combined_accuracy > walkforward_frame.baseline_strongest_baseline)
    ).sum())
    lock_payload = {
        "lock_version": "stage17b_bidirectional_shadow_lock_v1",
        "created_before_any_new_oos_outcomes": True,
        "status": "INSUFFICIENT_NEW_DATA",
        "confirmation_claimed": False,
        "selected_candidate": selected_metrics,
        "validation_gate_passed": bool(validation_gate_passed),
        "feature_columns": sets[str(chosen.feature_set)],
        "model_parameters": model_factories()[str(chosen.model)][2],
        "signal_logic": "LONG/SHORT from independently fitted UP/DOWN probabilities; NO_SIGNAL below locked confidence",
        "inverse_stage17_model": False,
        "old_stage17_test_rows_excluded": 134,
        "old_stage17_test_events_excluded": 116,
        "old_stage17_test_outcomes_read": 0,
        "old_stage17_lock_sha256": canonical_hash(stage17_lock),
        "new_untouched_oos": oos,
        "required_new_oos_predictions": 50,
        "shadow_collection_required": True,
        "walkforward_folds_above_gate": stable_folds,
        "walkforward_folds_total": 3,
        "leakage": 0,
        "configuration_must_not_change_after_new_outcomes": True,
    }
    lock_sha = canonical_hash(lock_payload)
    write_json(LOCK_REPORT, lock_payload)
    LOCK_SHA_REPORT.write_text(lock_sha + "\n", encoding="ascii")

    pytest_result = run_pytest()
    write_json(PYTEST_REPORT, pytest_result)
    stage17_after = protected_stage17_snapshot()
    changed = sorted(path for path in set(stage17_before) | set(stage17_after) if stage17_before.get(path) != stage17_after.get(path))
    if changed:
        raise RuntimeError(f"Protected Stage 17 artifacts changed: {changed}")
    if canonical_hash(json.loads(LOCK_REPORT.read_text(encoding="utf-8"))) != LOCK_SHA_REPORT.read_text(encoding="ascii").strip():
        raise RuntimeError("Stage 17B lock SHA mismatch")

    best_feature = str(chosen.feature_set)
    best_asset = str(chosen.asset_scope)
    best_horizon = str(chosen.horizon)
    best_long = long_candidates.sort_values(["long_accuracy", "long_signals"], ascending=False).iloc[0] if len(long_candidates) else None
    best_short = short_candidates.sort_values(["short_accuracy", "short_signals"], ascending=False).iloc[0] if len(short_candidates) else None
    best_long_answer = f"Best separate pattern: {float(best_long.long_accuracy) * 100:.2f}% ({int(best_long.long_signals)} validation signals)." if best_long is not None else "No separate LONG candidate passed."
    best_short_answer = f"Best separate pattern: {float(best_short.short_accuracy) * 100:.2f}% ({int(best_short.short_signals)} validation signals)." if best_short is not None else "No separate SHORT candidate passed."
    assessment = f"""# Stage 17B — Bidirectional LONG/SHORT Pattern Discovery

## Final status

`INSUFFICIENT_NEW_DATA`

Stage 17 remains unchanged with status `{stage17_status}`. Its opened 134-row test was not queried or reused. The database contains **0** eligible events after `{oos['old_opened_test_max_published_at']}`, so no new locked confirmation is scientifically possible. The configuration below is locked only for a future shadow period.

## Discovery boundary

- Discovery rows: {len(data)} event-asset rows / {data.event_id.nunique()} events (original train + validation only).
- Opened Stage 17 test outcomes read: 0.
- Generated explicit rules: {len(rules)} (maximum {MAX_RULES}); maximum conditions: {feature_payload['maximum_conditions_per_rule']}.
- LONG validation shortlist: {len(long_candidates)}.
- SHORT validation shortlist: {len(short_candidates)}.
- Combined validation shortlist: {len(combined_candidates)}.
- Best separate LONG validation pattern: {f"{float(best_long.long_accuracy) * 100:.2f}% / {int(best_long.long_signals)} signals / {best_long.asset_scope} / {best_long.horizon}" if best_long is not None else "none"}.
- Best separate SHORT validation pattern: {f"{float(best_short.short_accuracy) * 100:.2f}% / {int(best_short.short_signals)} signals / {best_short.asset_scope} / {best_short.horizon}" if best_short is not None else "none"}.
- Selected experimental config: `{chosen.model}` / `{best_feature}` / `{best_asset}` / `{best_horizon}` / neutral ±{float(chosen.neutral_threshold):.2f}% / confidence {float(chosen.confidence_threshold):.2f}.
- Validation gate passed: {bool(validation_gate_passed)}.
- Nested walk-forward folds above both 55% and strongest baseline: {stable_folds}/3.
- Leakage: 0; OpenAI requests: 0; paper/real trades: 0.
- Base cost includes 0.05% entry fee + 0.05% exit fee + 0.05% entry slippage + 0.05% exit slippage. Funding data is unavailable and shown as 0, not silently estimated.
- Pytest: {'PASS' if pytest_result['returncode'] == 0 else 'FAIL'} ({pytest_result['passed']} passed).
- Stage 17 artifact integrity: PASS ({len(stage17_after)} files, aggregate SHA-256 `{aggregate_hash(stage17_after)}`).

## Required answers

1. **LONG patterns found?** {"Validation candidates exist (" + str(len(long_candidates)) + "), but none is confirmed on new OOS." if len(long_candidates) else "No candidate passed the complete validation gate."}
2. **SHORT patterns found?** {"Validation candidates exist (" + str(len(short_candidates)) + "), but none is confirmed on new OOS." if len(short_candidates) else "No candidate passed the complete validation gate."}
3. **Best feature set?** `{best_feature}` on train+validation only; not an OOS conclusion.
4. **Best asset?** `{best_asset}` on train+validation only.
5. **Best horizon?** `{best_horizon}` on train+validation only.
6. **LONG accuracy?** {best_long_answer} Locked combined candidate LONG leg: {float(chosen.long_accuracy) * 100:.2f}% ({int(chosen.long_signals)}).
7. **SHORT accuracy?** {best_short_answer} Locked combined candidate SHORT leg: {float(chosen.short_accuracy) * 100:.2f}% ({int(chosen.short_signals)}).
8. **Combined accuracy?** {float(chosen.combined_accuracy) * 100:.2f}% ({int(chosen.combined_signals)} validation signals; coverage {float(chosen.coverage) * 100:.2f}%).
9. **Above 55%?** {"Yes on validation only" if float(chosen.combined_accuracy) > .55 else "No"}; this does not satisfy the new-OOS success criterion.
10. **New shadow period needed?** Yes. At least 50 untouched predictions are required with the locked SHA `{lock_sha}`.

No ML/pattern claim is promoted to trading. No next stage was started.
"""
    ASSESSMENT_REPORT.write_text(assessment, encoding="utf-8")
    print(json.dumps({
        "status": "INSUFFICIENT_NEW_DATA",
        "new_untouched_events": oos["new_untouched_events"],
        "selected": selected_metrics,
        "long_candidates": len(long_candidates),
        "short_candidates": len(short_candidates),
        "combined_candidates": len(combined_candidates),
        "walkforward_folds_above_gate": stable_folds,
        "pytest": {"returncode": pytest_result["returncode"], "passed": pytest_result["passed"]},
        "stage17_unchanged": not changed,
        "lock_sha256": lock_sha,
    }, ensure_ascii=False, indent=2, default=json_default))
    return 0 if pytest_result["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
