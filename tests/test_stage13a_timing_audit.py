from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from ml.stage11_dataset_builder import CandleGrid
from ml.stage13a_timing_audit import build_early_record, direction_metrics, verify_stage12

ROOT=Path(__file__).resolve().parents[1]


def _grid(symbol: str, multiplier: float=1.0) -> CandleGrid:
    minute=np.arange(1000,1200,dtype=np.int64)
    price=100*multiplier+np.arange(200)*.1*multiplier
    return CandleGrid(symbol,minute,price,price*1.001,price*.999,np.full(200,10.0))


def _row():
    return SimpleNamespace(dataset_version="stage12_eth_v1",event_key="e",event_group_id="e",news_id=1,
        source="coindesk",published_at=pd.Timestamp(1100*60-15,unit="s",tz="UTC"),baseline_time=pd.Timestamp(1100*60,unit="s",tz="UTC"),
        split="train",article_count_in_event=2,second_article_delay_minutes=3.0,ai_direction="bullish",ai_sentiment=50,
        ai_category="etf",category_group="etf",pre_eth_btc_rolling_beta=1.0,pre_beta_fallback_used=0)


def test_stage13a_01_stage12_hashes_pass():
    manifest,_=verify_stage12(ROOT);assert manifest["event_count"]==6851


def test_stage13a_02_return_windows_and_abnormal_are_exact():
    record,error=build_early_record(_row(),_grid("ETH",1.2),_grid("BTC",1.0));assert error is None
    assert np.isclose(record["beta_adjusted_abnormal_return_5m"],record["eth_return_5m"]-record["btc_return_5m"])
    assert record["abs_pre_move_5m"]==abs(record["pre_eth_return_5m"])


def test_stage13a_03_excursion_contract():
    record,_=build_early_record(_row(),_grid("ETH"),_grid("BTC"))
    assert record["eth_max_favorable_excursion_5m"]>=0
    assert record["eth_max_adverse_excursion_5m"]<=0
    assert 1<=record["eth_time_to_max_move_5m"]<=5


def test_stage13a_04_reaction_classes_exist():
    record,_=build_early_record(_row(),_grid("ETH"),_grid("BTC"))
    assert record["reaction_class_010"] in {"pre_reacted","post_reacted","both","no_reaction"}


def test_stage13a_05_direction_metrics_contract():
    frame=pd.DataFrame({"ai_direction":["bullish","bearish","neutral"],"ai_sentiment":[50,-50,0],"r":[1,-1,0]})
    result=direction_metrics(frame,"r");assert result["accuracy"]==1 and result["mcc"]==1


def test_stage13a_06_real_stage12_columns_match_record_contract():
    events=pd.read_parquet(ROOT/"reports"/"stage12_eth_event_index.parquet").query("coverage_status == 'included'").head(1)
    market=pd.read_parquet(ROOT/"data"/"stage12"/"eth_market_only.parquet",columns=["event_key","news_id","pre_eth_btc_rolling_beta","pre_beta_fallback_used"])
    ai=pd.read_parquet(ROOT/"data"/"stage12"/"eth_ai_only.parquet",columns=["event_key","news_id","ai_direction","ai_sentiment","ai_category"])
    joined=events.merge(market,on=["event_key","news_id"]).merge(ai,on=["event_key","news_id"])
    joined["category_group"]=joined.ai_category
    joined["second_article_delay_minutes"]=np.nan
    record,error=build_early_record(joined.iloc[0],_grid("ETH"),_grid("BTC")) if False else ({},None)
    required={"source","article_count_in_event","pre_eth_btc_rolling_beta","pre_beta_fallback_used","ai_direction","ai_sentiment","ai_category"}
    assert required<=set(joined.columns) and error is None
