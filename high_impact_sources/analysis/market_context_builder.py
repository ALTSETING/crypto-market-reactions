from __future__ import annotations
import numpy as np
from high_impact_sources.config import PRE_WINDOWS
from ml.stage11_dataset_builder import CandleGrid

def pct(current,previous):return float((current/previous-1)*100) if previous else None
def returns(prices):return np.diff(np.log(prices)) if len(prices)>1 else np.array([])
def ema(values,span):
    alpha=2/(span+1);out=float(values[0])
    for value in values[1:]:out=alpha*float(value)+(1-alpha)*out
    return out
def rolling_beta(asset:CandleGrid,btc:CandleGrid,cutoff:int,minutes:int=10080):
    ai=asset.index(cutoff-1);bi=btc.index(cutoff-1)
    if ai is None or bi is None or ai<minutes or bi<minutes:return 1.0
    a=returns(asset.open[ai-minutes:ai+1:5]);b=returns(btc.open[bi-minutes:bi+1:5]);n=min(len(a),len(b));a=a[-n:];b=b[-n:]
    variance=float(np.var(b,ddof=1)) if n>20 else 0
    return float(np.cov(a,b,ddof=1)[0,1]/variance) if variance>1e-16 else 1.0
def build_pre_context(grid:CandleGrid,btc:CandleGrid,baseline_minute:int):
    index=grid.index(baseline_minute-1);btc_index=btc.index(baseline_minute-1)
    if index is None or btc_index is None or index<720 or btc_index<720:return None
    current=float(grid.open[index]);result={}
    for minutes in PRE_WINDOWS:
        past=grid.index(baseline_minute-1-minutes)
        result[f"pre_return_{minutes}m"]=pct(current,float(grid.open[past])) if past is not None else None
    for minutes in (5,20,60,180,720):
        r=returns(grid.open[index-minutes:index+1])*100
        result[f"pre_realized_vol_{minutes}m"]=float(np.sqrt(np.sum(r*r))) if len(r)==minutes else None
    hist=grid.volume[index-60:index];mean=float(np.mean(hist));std=float(np.std(hist,ddof=1));last=float(grid.volume[index])
    result.update({"pre_volume_z60":(last-mean)/std if std else 0.0,"pre_volume_vs_avg60":last/mean if mean else None})
    for window in (20,50,200):
        prices=grid.open[index-window+1:index+1];sma=float(np.mean(prices));result[f"pre_distance_sma{window}"]=pct(current,sma);result[f"pre_distance_ema{window}"]=pct(current,ema(prices,window))
    result["pre_sma20_slope"]=pct(float(np.mean(grid.open[index-19:index+1])),float(np.mean(grid.open[index-39:index-19])))/20
    result["pre_trend_regime"]="bullish" if result["pre_distance_sma200"]>0 and result["pre_return_60m"]>0 else "bearish" if result["pre_distance_sma200"]<0 and result["pre_return_60m"]<0 else "range"
    beta=rolling_beta(grid,btc,baseline_minute);result["pre_rolling_beta_btc"]=beta
    a=returns(grid.open[index-10080:index+1:5]);b=returns(btc.open[btc_index-10080:btc_index+1:5]);n=min(len(a),len(b));result["pre_rolling_corr_btc"]=float(np.corrcoef(a[-n:],b[-n:])[0,1]) if n>20 else None
    btc_now=float(btc.open[btc_index]);btc_past=btc.index(baseline_minute-61);btc_60=pct(btc_now,float(btc.open[btc_past])) if btc_past is not None else None
    result["pre_relative_strength_1h"]=result["pre_return_60m"]-btc_60 if btc_60 is not None else None
    return result
