from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.stage18_unified import (
    API_HARD_LIMIT_USD, FrozenRule, add_missing_flags, budget_allows,
    chronological_split, directional_target, duplicate_components,
    economic_metrics, endpoint_return, entry_timestamp, gap_minutes,
    mfe_mae, normalize_text, normalize_url, official_identifier,
    required_window, signed_return, text_fingerprint, validate_candles,
    wilson_interval, assert_no_future_features,
)


def sample_events():
    return pd.DataFrame({"canonical_event_id":[f"e{i}" for i in range(20)],
                         "published_at":pd.date_range("2024-01-01", periods=20, tz="UTC")})


def test_01_cross_dataset_url_dedup():
    f=pd.DataFrame({"member_id":["a","b"],"normalized_url":["x","x"],"official_id":["", ""],"content_hash":["", ""],"text_fingerprint":["1","2"],"normalized_title":["a","b"],"published_at":pd.to_datetime(["2024-01-01","2024-01-02"],utc=True)})
    roots,pairs=duplicate_components(f); assert roots["a"]==roots["b"] and len(pairs)==1


def test_02_same_event_assets_one_split():
    f=sample_events();f=pd.concat([f.assign(asset="ETH"),f.assign(asset="BTC")]);s=chronological_split(f,pd.Series(False,index=f.index));assert s.groupby(f.canonical_event_id).nunique().max()==1


def test_03_chronological_split():
    f=sample_events();s=chronological_split(f,pd.Series(False,index=f.index));assert list(s).index("validation")>list(s).index("train")


def test_04_external_split_isolated():
    f=sample_events();m=f.canonical_event_id.eq("e0");s=chronological_split(f,m);assert s.iloc[0]=="historical_external"


def test_05_normalized_url_removes_tracking(): assert normalize_url("HTTPS://www.X.com/a/?utm_x=1&b=2")=="https://x.com/a?b=2"
def test_06_normalized_text(): assert normalize_text(" A,  B! ")=="a b"
def test_07_fingerprint_stable(): assert text_fingerprint("A","B")==text_fingerprint("a","b")
def test_08_official_github_id(): assert official_identifier("https://github.com/a/b/pull/7")=="github:a/b:7"
def test_09_entry_latency(): assert entry_timestamp("2024-01-01T00:00:30Z")==pd.Timestamp("2024-01-01T00:02:00Z")


def test_10_required_window():
    a,b,c=required_window("2024-01-01T00:00:30Z");assert (b-a).total_seconds()==86400 and (c-b).total_seconds()==86400


def test_11_candle_validation_pass():
    f=pd.DataFrame({"open_time":["2024-01-01T00:00Z"],"open":[1.],"high":[2.],"low":[.5],"close":[1.5],"volume":[0.]});assert validate_candles(f).all()


def test_12_candle_validation_rejects_bad_ohlc():
    f=pd.DataFrame({"open_time":["2024-01-01T00:00Z"],"open":[1.],"high":[.5],"low":[.6],"close":[1.5],"volume":[0.]});assert not validate_candles(f).any()


def test_13_gap_detection(): assert gap_minutes(np.array([1,2,4]),1,4).tolist()==[3]
def test_14_no_synthetic_candles(): assert len(gap_minutes(np.array([1,3]),1,3))==1
def test_15_endpoint_formula(): assert endpoint_return(100,105)==pytest.approx(5)
def test_16_long_signed_return(): assert signed_return(2,"LONG")==2
def test_17_short_signed_return(): assert signed_return(2,"SHORT")==-2


def test_18_mfe_long():
    x=mfe_mae(np.array([0.,2.,1.]),np.array([0.,-1.,-.5]),"LONG");assert x==(2.,-1.,1,1)


def test_19_mae_short():
    x=mfe_mae(np.array([0.,2.,1.]),np.array([0.,-1.,-.5]),"SHORT");assert x==(1.,-2.,1,1)


def test_20_direction_target(): assert directional_target(pd.Series([.2,-.2,0])).tolist()==["UP","DOWN","NEUTRAL"]
def test_21_future_feature_guard_pass(): assert_no_future_features(["pre_return_5m","ai_importance"])
def test_22_future_feature_guard_fails():
    with pytest.raises(ValueError): assert_no_future_features(["target_return_12h"])


def test_23_missing_flags():
    f=add_missing_flags(pd.DataFrame({"x":[1,None]}),["x"]);assert f.x_missing.tolist()==[0,1]


def test_24_api_budget_pass(): assert budget_allows(0,1.89)
def test_25_api_budget_safety_stop(): assert not budget_allows(0,1.91)
def test_26_api_hard_limit_constant(): assert API_HARD_LIMIT_USD==2.0
def test_27_fixed_12h_rule_hash_stable():
    r=FrozenRule("a","12h",.1,.4,1);assert r.digest()==r.digest() and r.primary_horizon=="12h"


def test_28_economic_cost():
    result=economic_metrics([1.,-1.],.2);assert result["gross_expectancy"]==0 and result["net_expectancy"]==pytest.approx(-.2)


def test_29_wilson_bounds():
    lo,hi=wilson_interval(60,100);assert 0<lo<.6<hi<1
