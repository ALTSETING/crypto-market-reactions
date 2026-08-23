from datetime import datetime,timezone
import numpy as np
from ml.stage11_dataset_builder import CandleGrid
from high_impact_sources.analysis.reaction_calculator import baseline_minute,calculate_event_reaction,classify_pre_post
from high_impact_sources.analysis.market_context_builder import rolling_beta

def grid(symbol,mult=1):
    minute=np.arange(10000,22001,dtype=np.int64);values=(100+np.arange(len(minute))*.01)*mult;volume=np.ones(len(minute))*10
    return CandleGrid(symbol,minute,values,values*1.001,values*.999,volume)
def test_baseline_minute_calculation():assert baseline_minute(datetime.fromtimestamp(15000*60+12,tz=timezone.utc))==15001
def test_all_horizons_and_latencies():
    rows,reason=calculate_event_reaction(1,datetime.fromtimestamp(15000*60+12,tz=timezone.utc),"ETHUSDT",grid("ETH"),grid("BTC"));assert reason is None and len(rows)==5 and rows[0]["return_12h"] is not None
def test_pre_windows_do_not_use_future():
    rows,_=calculate_event_reaction(1,datetime.fromtimestamp(15000*60+12,tz=timezone.utc),"ETHUSDT",grid("ETH"),grid("BTC"));assert "pre_return_720m" in rows[0]["pre_context_json"]
def test_abnormal_return_correct_for_equal_beta_series():
    rows,_=calculate_event_reaction(1,datetime.fromtimestamp(15000*60+12,tz=timezone.utc),"ETHUSDT",grid("ETH",2),grid("BTC"));assert abs(rows[0]["abnormal_return_5m"])<1e-8
def test_latency_applied():
    rows,_=calculate_event_reaction(1,datetime.fromtimestamp(15000*60+12,tz=timezone.utc),"BTCUSDT",grid("BTC"),grid("BTC"));assert [r["latency_minutes"] for r in rows]==[0,1,2,3,5]
def test_reaction_classification():assert classify_pre_post(.3,.1,.25)=="pre_reacted" and classify_pre_post(.3,.3,.25)=="both"
