import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.stage13_experiments import TARGETS, VARIANTS, feature_columns, regression_metrics, verify_stage12

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/"reports";MODELS=ROOT/"models"/"stage13"


def test_stage13_01_stage12_manifest_and_hashes_verify():
    manifest,_=verify_stage12(ROOT);assert manifest["dataset_version"]=="stage12_eth_v1"


def test_stage13_02_targets_never_enter_feature_lists():
    manifest,_=verify_stage12(ROOT)
    for variant in VARIANTS:assert not any(x.startswith("target_") for x in feature_columns(manifest,variant))


def test_stage13_03_fixed_split_counts_preserved():
    _,frames=verify_stage12(ROOT)
    for variant in VARIANTS:assert frames[variant].split.value_counts().to_dict()=={"train":4110,"test":1371,"validation":1370}


def test_stage13_04_validation_search_does_not_use_test():
    frame=pd.read_csv(REPORTS/"stage13_eth_validation_metrics.csv");assert set(frame.split)=={"validation"}


def test_stage13_05_two_main_targets_and_three_variants_in_leaderboard():
    frame=pd.read_csv(REPORTS/"stage13_eth_model_leaderboard.csv");assert len(frame)==6 and set(frame.target_name)==set(TARGETS) and set(frame.dataset_variant)==set(VARIANTS)


def test_stage13_06_three_walkforward_folds_exist():
    frame=pd.read_csv(REPORTS/"stage13_eth_walkforward_metrics.csv");assert set(frame.fold)=={1,2,3} and len(frame)==18


def test_stage13_07_walkforward_is_strictly_forward():
    frame=pd.read_csv(REPORTS/"stage13_eth_walkforward_metrics.csv",parse_dates=["train_end","evaluation_start"]);assert (frame.train_end<frame.evaluation_start).all()


def test_stage13_08_test_predictions_schema_and_count():
    frame=pd.read_parquet(REPORTS/"stage13_eth_test_predictions.parquet");expected={"event_key","published_at","split","target_name","dataset_variant","model_name","prediction","actual","residual","prediction_rank","source"};assert expected<=set(frame) and len(frame)==1371*2*3


def test_stage13_09_predictions_are_finite():
    frame=pd.read_parquet(REPORTS/"stage13_eth_test_predictions.parquet");assert np.isfinite(frame[["prediction","actual","residual","prediction_rank"]]).all().all()


def test_stage13_10_research_artifacts_exist_and_are_not_production():
    for target in TARGETS:
        for variant in VARIANTS:
            path=MODELS/target/variant;assert all((path/name).exists() for name in ("pipeline.joblib","model_metadata.json","feature_list.json","validation_metrics.json","test_metrics.json"));assert json.loads((path/"model_metadata.json").read_text())["artifact_type"]=="baseline_research_not_production"


def test_stage13_11_saved_pipeline_predicts_without_test_refit():
    manifest,frames=verify_stage12(ROOT);variant="market_plus_ai";target=TARGETS[0];model=joblib.load(MODELS/target/variant/"pipeline.joblib");prediction=model.predict(frames[variant].loc[frames[variant].split.eq("test"),feature_columns(manifest,variant)].head(3));assert len(prediction)==3 and np.isfinite(prediction).all()


def test_stage13_12_ablation_has_both_comparisons():
    frame=pd.read_csv(REPORTS/"stage13_eth_ablation_results.csv");assert set(frame.comparison)=={"C_vs_A","B_vs_A"} and len(frame)==4


def test_stage13_13_bootstrap_intervals_are_ordered():
    frame=pd.read_csv(REPORTS/"stage13_eth_bootstrap_intervals.csv");assert (frame.ci_low<=frame.ci_high).all()


def test_stage13_14_preprocessing_metadata_declares_no_test_selection():
    for path in MODELS.glob("*/*/model_metadata.json"):assert json.loads(path.read_text())["test_used_for_selection"] is False


def test_stage13_15_summary_safety_and_integrity_flags():
    summary=json.loads((REPORTS/"stage13_eth_summary.json").read_text());assert summary["stage12_unchanged"] and summary["openai_api_requests"]==0 and not summary["paper_trading_run"] and not summary["real_trading_run"] and not summary["production_model_created"]


def test_stage13_16_metric_contract():
    metrics=regression_metrics(np.array([1.,2.,3.]),np.array([1.,2.,3.]));assert metrics["mae"]==0 and metrics["spearman"]==1 and metrics["top_decile_lift"]>1
