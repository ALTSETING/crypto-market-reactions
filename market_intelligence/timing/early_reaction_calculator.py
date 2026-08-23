from __future__ import annotations
import numpy as np
import pandas as pd
from ml.stage11_dataset_builder import CandleGrid
HORIZONS=(1,2,3,5,10,15)
EXCURSION_HORIZONS=(1,3,5,10,15)
def _ret(a,b):return float((a/b-1)*100)
def calculate_latency_record(news_id:int,baseline_time:pd.Timestamp,beta:float,eth:CandleGrid,btc:CandleGrid,latency_minutes:int):
    minute=int(pd.Timestamp(baseline_time).timestamp()//60)+latency_minutes;ei=eth.index(minute);bi=btc.index(minute)
    if ei is None or bi is None or eth.exact_window(minute-15,minute+15) is None or btc.exact_window(minute-15,minute+15) is None:return None
    row={"news_id":news_id,"symbol":"ETHUSDT","baseline_time":pd.Timestamp(baseline_time).to_pydatetime(),"latency_minutes":latency_minutes}
    for h in HORIZONS:
        er=_ret(eth.open[eth.index(minute+h)],eth.open[ei]);br=_ret(btc.open[btc.index(minute+h)],btc.open[bi])
        row[f"return_{h}m"]=er;row[f"btc_return_{h}m"]=br;row[f"eth_minus_btc_{h}m"]=er-br;row[f"abnormal_return_{h}m"]=er-beta*br;row[f"pre_return_{h}m"]=_ret(eth.open[ei],eth.open[eth.index(minute-h)])
    expected=float(np.mean(eth.volume[ei-60:ei]))
    for h in EXCURSION_HORIZONS:
        highs=eth.high[ei:ei+h];lows=eth.low[ei:ei+h];base=eth.open[ei];fav=(highs/base-1)*100;adv=(lows/base-1)*100
        row[f"max_favorable_{h}m"]=float(fav.max());row[f"max_adverse_{h}m"]=float(adv.min());row[f"max_absolute_{h}m"]=max(abs(row[f"max_favorable_{h}m"]),abs(row[f"max_adverse_{h}m"]))
        row[f"high_low_range_{h}m"]=float((highs.max()/lows.min()-1)*100)
        closes=eth.open[ei:ei+h+1];row[f"realized_vol_{h}m"]=float(np.sqrt(np.sum((np.diff(np.log(closes))*100)**2)))
        row[f"volume_shock_{h}m"]=float(np.sum(eth.volume[ei:ei+h])/(expected*h)) if expected else np.nan
        moves=np.maximum(abs(fav),abs(adv));row[f"time_to_max_move_{h}m"]=int(np.argmax(moves)+1)
    return row
