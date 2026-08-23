import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.stage12_dataset_builder import DATASET_VERSION, chronological_split, stage12_event_selection

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"data"/"stage12"; REPORTS=ROOT/"reports"


def datasets():
    return {name:pd.read_parquet(DATA/name) for name in ("eth_market_only.parquet","eth_ai_only.parquet","eth_market_plus_ai.parquet")}


def test_01_one_event_key_one_row():
    assert not pd.read_parquet(REPORTS/"stage12_eth_event_index.parquet").query("coverage_status == 'included'").event_key.duplicated().any()


def test_02_earliest_article_selection_tiebreakers():
    frame=pd.DataFrame({"news_id":[3,2,1],"event_group_id":["e","e","e"],"published_at":pd.to_datetime(["2024-01-01","2024-01-01","2024-01-02"],utc=True),"time_confidence":[.5,.9,1.0],"baseline_time":pd.NaT,"source":"x"})
    selected,_=stage12_event_selection(frame); assert selected.news_id.iloc[0]==2


def test_03_synthetic_event_keys_unique():
    frame=pd.DataFrame({"news_id":[1,2],"event_group_id":[None,None],"published_at":pd.to_datetime(["2024-01-01","2024-01-02"],utc=True),"time_confidence":[1,1],"baseline_time":pd.NaT,"source":"x"})
    selected,_=stage12_event_selection(frame); assert selected.event_key.tolist()==["news:1","news:2"]


def test_04_no_event_overlap_between_splits():
    frame=pd.read_parquet(DATA/"eth_targets.parquet"); groups=[set(frame.loc[frame.split.eq(x),"event_key"]) for x in ("train","validation","test")]
    assert not (groups[0]&groups[1] or groups[0]&groups[2] or groups[1]&groups[2])


def test_05_split_is_chronological():
    frame=pd.read_parquet(DATA/"eth_targets.parquet"); assert frame.query("split=='train'").published_at.max() <= frame.query("split=='validation'").published_at.min() <= frame.query("split=='test'").published_at.min()


def test_06_feature_cutoff_has_no_future_candles():
    audit=pd.read_csv(REPORTS/"stage12_eth_feature_cutoff_audit.csv"); assert not audit.violation.any()


def test_07_baseline_candle_not_in_pre_news_features():
    audit=pd.read_csv(REPORTS/"stage12_eth_feature_cutoff_audit.csv",parse_dates=["max_input_open_time","baseline_time"]); assert (audit.max_input_open_time < audit.baseline_time).all()


def test_08_abnormal_return_formula():
    old=pd.read_parquet(REPORTS/"stage11_eth_dataset_a.parquet").set_index("metadata_news_id"); target=pd.read_parquet(DATA/"eth_targets.parquet").set_index("news_id")
    expected=old.loc[target.index,"target_eth_return_1h"]-old.loc[target.index,"pre_beta_pre_news"]*old.loc[target.index,"target_btc_return_1h"]
    assert np.allclose(expected,target.target_abnormal_return_1h)


def test_09_rolling_beta_is_pre_news_and_flagged():
    frame=pd.read_parquet(DATA/"eth_market_only.parquet"); assert "pre_eth_btc_rolling_beta" in frame and "pre_beta_fallback_used" in frame


def test_10_targets_not_in_manifest_feature_list():
    manifest=json.loads((DATA/"manifest.json").read_text()); assert not any(x.startswith("target_") for x in manifest["feature_list"])


def test_11_reactions_not_in_features():
    manifest=json.loads((DATA/"manifest.json").read_text()); assert not any("reaction" in x for x in manifest["feature_list"])


def test_12_raw_text_not_in_features():
    manifest=json.loads((DATA/"manifest.json").read_text()); assert not any(x in {"title","body","raw_response_json"} for x in manifest["feature_list"])


def test_13_market_dataset_has_no_ai_features():
    assert not any(x.startswith("ai_") for x in pd.read_parquet(DATA/"eth_market_only.parquet").columns)


def test_14_ai_dataset_has_no_market_features():
    assert not any(x.startswith("pre_") for x in pd.read_parquet(DATA/"eth_ai_only.parquet").columns)


def test_15_combined_dataset_has_both_groups():
    columns=pd.read_parquet(DATA/"eth_market_plus_ai.parquet").columns; assert any(x.startswith("pre_") for x in columns) and any(x.startswith("ai_") for x in columns)


def test_16_all_variants_have_same_event_order():
    values=[x.event_key.tolist() for x in datasets().values()]; assert values[0]==values[1]==values[2]


def test_17_test_is_not_used_for_preprocessing():
    manifest=json.loads((DATA/"manifest.json").read_text()); assert manifest["split_definition"]["method"]=="chronological_60_20_20"


def test_18_missing_values_not_globally_imputed():
    report=pd.read_csv(REPORTS/"stage12_eth_missing_values.csv"); assert report.imputation_policy.str.contains("train-only").all()


def test_19_manifest_hashes_match_files():
    manifest=json.loads((DATA/"manifest.json").read_text());
    for relative,expected in manifest["file_hashes_sha256"].items(): assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==expected


def test_20_resume_contract_is_versioned():
    manifest=json.loads((DATA/"manifest.json").read_text()); assert manifest["dataset_version"]==DATASET_VERSION and manifest["event_count"]==6851


def test_21_stage_source_counts_unchanged_flag():
    assert json.loads((DATA/"manifest.json").read_text())["stage8_11_source_counts_unchanged"] is True


def test_22_no_infinite_values():
    for frame in datasets().values():
        numeric=frame.select_dtypes(include=[np.number]); assert not np.isinf(numeric.to_numpy()).any()


def test_23_no_duplicate_columns():
    for frame in datasets().values(): assert not frame.columns.duplicated().any()


def test_24_neutral_band_labels_are_correct():
    target=pd.read_parquet(DATA/"eth_targets.parquet"); expected=np.where(target.target_abnormal_return_1h>.5,"positive",np.where(target.target_abnormal_return_1h<-.5,"negative","neutral")); assert np.array_equal(expected,target.target_abnormal_direction_1h_band_050)


def test_25_cost_scenarios_are_metadata_only():
    costs=json.loads((REPORTS/"stage12_eth_cost_scenarios.json").read_text()); assert costs["costs_not_subtracted_from_targets"] and not any("assumed_fee" in column for column in pd.read_parquet(DATA/"eth_market_plus_ai.parquet").columns)
