from __future__ import annotations
import numpy as np
import pandas as pd
from high_impact_sources.config import HORIZONS,LATENCIES
from high_impact_sources.analysis.market_context_builder import build_pre_context,rolling_beta,pct
from high_impact_sources.parsers.timestamp_parser import next_full_minute

def baseline_minute(published_at):return int(next_full_minute(published_at).timestamp()//60)
def _realized(prices):
    r=np.diff(np.log(prices));return float(np.sqrt(np.sum((r*100)**2))) if len(r) else None
def calculate_event_reaction(event_id,published_at,symbol,grid,btc):
    initial=baseline_minute(published_at);context=build_pre_context(grid,btc,initial)
    if context is None:return [],"missing_pre_context"
    beta=rolling_beta(grid,btc,initial);rows=[]
    for latency in LATENCIES:
        base=initial+latency;index=grid.index(base);btc_index=btc.index(base)
        if index is None or btc_index is None:continue
        if grid.index(base+720) is None or btc.index(base+720) is None:continue
        baseline=float(grid.open[index]);btc_baseline=float(btc.open[btc_index]);row={"event_id":event_id,"symbol":symbol,"baseline_time":pd.to_datetime(base*60,unit="s",utc=True).to_pydatetime(),"latency_minutes":latency,"baseline_price":baseline,"pre_context_json":context}
        for label,minutes in HORIZONS.items():
            end=grid.index(base+minutes);btc_end=btc.index(base+minutes);raw=pct(float(grid.open[end]),baseline);benchmark=pct(float(btc.open[btc_end]),btc_baseline)
            row[f"return_{label}"]=raw;row[f"abnormal_return_{label}"]=raw if symbol=="BTCUSDT" else raw-beta*benchmark
        for label,minutes in (("1h",60),("12h",720)):
            highs=(grid.high[index:index+minutes]/baseline-1)*100;lows=(grid.low[index:index+minutes]/baseline-1)*100
            row[f"max_favorable_{label}"]=float(np.max(highs));row[f"max_adverse_{label}"]=float(np.min(lows));row[f"max_absolute_{label}"]=float(max(np.max(np.abs(highs)),np.max(np.abs(lows))))
        pre_vol=grid.volume[max(0,index-60):index];post_vol=grid.volume[index:index+60];row["volume_shock_1h"]=float(np.mean(post_vol)/np.mean(pre_vol)) if np.mean(pre_vol) else None
        row["realized_vol_1h"]=_realized(grid.open[index:index+61]);row["realized_vol_12h"]=_realized(grid.open[index:index+721]);rows.append(row)
    return rows,None if rows else "missing_future_window"

def classify_pre_post(pre,post,threshold):
    a=abs(pre)>=threshold;b=abs(post)>=threshold
    return "both" if a and b else "pre_reacted" if a else "post_reacted" if b else "no_clear_reaction"
