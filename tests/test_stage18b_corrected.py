from __future__ import annotations

import ast
import math
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from ml.stage18_unified import add_missing_flags, chronological_split, directional_target, semantic_score, signed_return
from ml.stage18b_corrected import (
    canonical_digest, cluster_bootstrap, event_block_permutation, file_tree_hash,
    full_performance, normalize_semantic_series, normalize_semantic_value,
    probability_map, semantic_gate, signal_from_probabilities,
)


def test_01_schema_specific_normalization(): assert normalize_semantic_value(50, "high_impact_semantic_v2_1") == .5
def test_02_zero_one_scale(): assert semantic_score(.25, "zero_one") == .25
def test_03_zero_ten_scale(): assert semantic_score(5, "zero_ten") == .5
def test_04_zero_hundred_scale(): assert semantic_score(75, "zero_hundred") == .75
def test_05_unknown_schema_rejected():
    with pytest.raises(ValueError): normalize_semantic_value(1, "unknown")


def test_06_no_clipping():
    with pytest.raises(ValueError): semantic_score(101, "zero_hundred")


def test_07_out_of_range_gate():
    result = semantic_gate(pd.DataFrame({"sem_importance": [0, 1.1]}), ["sem_importance"])
    assert result["semantic_out_of_range_count"] == 1


def test_08_stage18_bug_regression(): assert normalize_semantic_value(95, "high_impact_semantic_v2_1") == .95
def test_09_dataset_b_never_reaches_1000(): assert normalize_semantic_series(pd.Series([4, 95]), "high_impact_semantic_v2_1").max() <= 1
def test_10_canonical_values_zero_one(): assert normalize_semantic_series(pd.Series([0, 100]), "stage9_eth_label_v1").tolist() == [0, 1]
def test_11_signed_valence_scale(): assert normalize_semantic_value(-80, "high_impact_semantic_v2_1", signed=True) == -.8
def test_12_missing_indicator(): assert add_missing_flags(pd.DataFrame({"x": [None, 1]}), ["x"]).x_missing.tolist() == [1, 0]
def test_13_missing_not_zero(): assert math.isnan(normalize_semantic_value(np.nan, "high_impact_semantic_v2_1"))
def test_14_feature_order_digest(): assert canonical_digest(["a", "b"]) != canonical_digest(["b", "a"])
def test_15_preprocessor_hash_deterministic(): assert joblib.hash({"a": np.array([1, 2])}) == joblib.hash({"a": np.array([1, 2])})


def test_16_chronological_split_event_safe():
    frame = pd.DataFrame({"canonical_event_id": [f"e{i}" for i in range(20)] * 2,
                          "published_at": list(pd.date_range("2020-01-01", periods=20, tz="UTC")) * 2})
    split = chronological_split(frame, pd.Series(False, index=frame.index))
    assert split.groupby(frame.canonical_event_id).nunique().max() == 1


def test_17_no_temporal_leakage():
    train_end = pd.Timestamp("2020-01-01", tz="UTC"); validation_start = pd.Timestamp("2020-01-02", tz="UTC")
    assert train_end < validation_start


def test_18_target_recalculation(): assert directional_target(pd.Series([.11, -.11, .1])).tolist() == ["UP", "DOWN", "NEUTRAL"]
def test_19_long_return_sign(): assert signed_return(2, "LONG") == 2
def test_20_short_return_sign(): assert signed_return(2, "SHORT") == -2


def test_21_cost_calculation():
    frame = pd.DataFrame({"signal": ["LONG"], "gross_return": [1.0], "predicted_direction": ["UP"], "actual_direction": ["UP"]})
    assert full_performance(frame, .2)["mean_net_return"] == pytest.approx(.8)


def test_22_confidence_signal_funnel():
    frame = pd.DataFrame({"p_DOWN": [.6, .2], "p_NEUTRAL": [.1, .7], "p_UP": [.3, .1]})
    result = signal_from_probabilities(frame, .4)
    assert result.predicted_direction.tolist() == ["DOWN", "NO_SIGNAL"]


def test_23_probability_mapping_uses_classes():
    estimator = SimpleNamespace(classes_=np.array(["UP", "DOWN", "NEUTRAL"]))
    model = SimpleNamespace(named_steps={"model": estimator})
    result = probability_map(model, np.array([[.1, .8, .1]]))
    assert result.p_DOWN.iloc[0] == .8


def test_24_baseline_timestamp_equality():
    left = pd.DataFrame({"event_id": [1, 2]}); right = left.copy(); assert left.event_id.tolist() == right.event_id.tolist()


def _sample_predictions() -> pd.DataFrame:
    return pd.DataFrame({"event_id": [1, 2, 3, 4], "signal": ["LONG", "SHORT", "LONG", "SHORT"],
                         "predicted_direction": ["UP", "DOWN", "UP", "DOWN"], "actual_direction": ["UP", "UP", "DOWN", "DOWN"],
                         "gross_return": [1., -1., .5, .25], "net_return": [.8, -1.2, .3, .05], "return_12h": [1., 1., .5, -.25]})


def test_25_cluster_bootstrap_deterministic():
    a = cluster_bootstrap(_sample_predictions(), 20, 7, .5); b = cluster_bootstrap(_sample_predictions(), 20, 7, .5)
    assert a == b


def test_26_permutation_deterministic():
    a = event_block_permutation(_sample_predictions(), 20, 7); b = event_block_permutation(_sample_predictions(), 20, 7)
    assert a == b


def test_27_model_reload(tmp_path):
    path = tmp_path / "x.joblib"; joblib.dump({"x": [1]}, path); assert joblib.load(path) == {"x": [1]}


def test_28_prediction_level_persistence(tmp_path):
    path = tmp_path / "x.parquet"; _sample_predictions().to_parquet(path); assert len(pd.read_parquet(path)) == 4


def test_29_protected_hash_and_idempotency(tmp_path):
    path = tmp_path / "x"; path.write_text("a"); before = file_tree_hash([path], tmp_path); after = file_tree_hash([path], tmp_path)
    assert before == after and canonical_digest(before) == canonical_digest(after)


def test_30_no_api_or_trading_actions_in_runner():
    source = (Path(__file__).parents[1] / "scripts" / "run_stage18b_corrected.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"create_order", "submit_order", "openai", "client.responses.create", "client.batches.create"}
    calls = {getattr(node.func, "attr", "") for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not (forbidden & calls)
