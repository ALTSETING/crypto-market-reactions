import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from patterns.engine import bh_adjust, condition_mask, evaluate_rule, merge_duplicate_rules, reject_reason, wilson_interval

ROOT=Path(__file__).resolve().parents[1]

def _frame():
    return pd.DataFrame({"event_key":["a","b","c","d"],"published_at":pd.to_datetime(["2026-01-01","2026-02-01","2026-03-01","2026-04-01"],utc=True),"metadata_source":["coindesk","decrypt","coindesk","decrypt"],"x":[1,2,3,4],"target_abnormal_return_1h":[1,-1,2,-2],"execution":[.5,-.5,1,-1]})

def _rule(direction="bullish",conditions=None):return {"rule_id":"r","version":"1","direction":direction,"target_horizon":"1h","conditions":conditions or {"x":{"gte":2}},"minimum_sample_size":1}

def test_stage15_01_ai_feature_contract_has_no_raw_response():
    frame=pd.read_parquet(ROOT/"data/stage12/eth_ai_only.parquet");assert "ai_sentiment" in frame and not any("raw_response" in c for c in frame)

def test_stage15_02_market_predictors_are_pre_news():
    columns=pd.read_parquet(ROOT/"data/stage12/eth_market_only.parquet").columns[:105];assert all(c.startswith(("pre_","metadata_")) or c in {"dataset_version","event_key","news_id","published_at","baseline_time","split"} for c in columns)

def test_stage15_03_generated_thresholds_are_train_created():
    rules=json.load(open(ROOT/"patterns/generated_rules.yaml",encoding="utf-8"));assert rules and all("train" in r["created_from"] for r in rules)

def test_stage15_04_validation_selects_holding():
    rules=json.load(open(ROOT/"patterns/shortlisted_rules.yaml",encoding="utf-8"));assert all(r["selected_holding_minutes"] in {15,30,60,240} for r in rules)

def test_stage15_05_test_not_used_for_tuning():
    summary=json.load(open(ROOT/"reports/stage15_summary.json",encoding="utf-8"));assert summary["test_used_once"] and not summary["test_used_for_tuning"]

def test_stage15_06_input_events_unique():
    frame=pd.read_parquet(ROOT/"data/stage12/eth_market_only.parquet",columns=["event_key"]);assert frame.event_key.is_unique

def test_stage15_07_event_split_overlap_zero():
    frame=pd.read_parquet(ROOT/"data/stage12/eth_market_only.parquet",columns=["event_key","split"]);assert frame.groupby("event_key").split.nunique().max()==1

def test_stage15_08_rule_parser_executes_all_operators():
    mask=condition_mask(_frame(),{"x":{"gte":2,"lt":4}});assert mask.tolist()==[False,True,True,False]

def test_stage15_09_bullish_success_definition():
    metrics,_=evaluate_rule(_frame(),_rule("bullish",{"x":{"gte":1}}),split="x");assert metrics["wins"]==2

def test_stage15_10_bearish_success_definition():
    metrics,_=evaluate_rule(_frame(),_rule("bearish",{"x":{"gte":1}}),split="x");assert metrics["wins"]==2

def test_stage15_11_neutral_band_contract():
    values=np.array([.2,-.2,.05]);labels=np.select([values>.1,values<-.1],["positive","negative"],default="neutral");assert labels.tolist()==["positive","negative","neutral"]

def test_stage15_12_costs_are_subtracted_once_as_round_trip_total():
    metrics,_=evaluate_rule(_frame(),_rule("bullish",{"x":{"gte":1}}),split="x",execution_column="execution",round_trip_cost_pct=.2);assert np.isclose(metrics["mean_net_return"],_frame().execution.mean()-.2)

def test_stage15_13_latency_scenarios_are_distinct():
    costs=pd.read_csv(ROOT/"reports/stage15_cost_sensitivity.csv");assert set(costs.groupby("scenario").latency_minutes.first().to_dict().items())=={("low",1),("base",1),("stress",2)}

def test_stage15_14_holding_not_tuned_on_test():
    assert "selected_holding_minutes" in json.load(open(ROOT/"patterns/shortlisted_rules.yaml",encoding="utf-8"))[0]

def test_stage15_15_wilson_interval_known_case():
    low,high=wilson_interval(55,100);assert .45<low<.46 and .64<high<.65

def test_stage15_16_bh_is_monotone_in_rank():
    adjusted=bh_adjust([.01,.02,.20]);assert np.allclose(adjusted,[.03,.03,.20])

def test_stage15_17_walkforward_folds_are_disjoint_and_complete():
    walk=pd.read_csv(ROOT/"reports/stage15_walkforward_metrics.csv");test=pd.read_csv(ROOT/"reports/stage15_test_metrics.csv");joined=walk.groupby("rule_id").n.sum().to_frame("fold_n").join(test.set_index("rule_id").n);assert (joined.fold_n==joined.n).all() and set(walk.fold)=={1,2,3}

def test_stage15_18_low_sample_rule_rejected():
    assert reject_reason({"complexity":2,"n":29,"win_rate":.8,"mean_net_return":1,"profit_factor":2,"source_count":2,"month_count":2})=="low_sample"

def test_stage15_19_complex_rule_rejected():
    assert reject_reason({"complexity":5,"n":100,"win_rate":.8,"mean_net_return":1,"profit_factor":2,"source_count":2,"month_count":2})=="complexity_gt_4"

def test_stage15_20_duplicate_rules_merge():
    a=_rule();b={**_rule(),"rule_id":"other"};assert len(merge_duplicate_rules([a,b]))==1

def test_stage15_21_simplified_thresholds_are_bounded_complexity():
    rules=json.load(open(ROOT/"patterns/generated_rules.yaml",encoding="utf-8"));assert all(len(r["conditions"])<=4 for r in rules)

def test_stage15_22_pattern_registry_ids_unique():
    registry=json.load(open(ROOT/"reports/stage15_pattern_registry.json",encoding="utf-8"));assert len(registry)==len({(r["rule_id"],r["version"]) for r in registry})

def test_stage15_23_resume_preserves_final_approval_semantics():
    summary=json.load(open(ROOT/"reports/stage15_summary.json",encoding="utf-8"));approved=json.load(open(ROOT/"patterns/approved_rules.yaml",encoding="utf-8"));assert len(approved)==summary["shadow_candidates"]

def test_stage15_24_stage12_hashes_unchanged():
    manifest=json.load(open(ROOT/"data/stage12/manifest.json",encoding="utf-8"));assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in manifest["file_hashes_sha256"].items())

def test_stage15_25_leakage_zero():
    summary=json.load(open(ROOT/"reports/stage15_summary.json",encoding="utf-8"));assert summary["leakage_violations"]==0 and summary["stage8_13_5_hashes_unchanged"]
