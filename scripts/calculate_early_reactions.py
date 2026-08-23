import json
import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from database.db import SessionLocal
from ml.stage11_dataset_builder import load_candle_grid
from market_intelligence.models import news_early_reactions
from market_intelligence.timing import calculate_latency_record

def main():
 events=pd.read_parquet("reports/stage12_eth_event_index.parquet").query("coverage_status == 'included'")
 market=pd.read_parquet("data/stage12/eth_market_only.parquet",columns=["event_key","news_id","pre_eth_btc_rolling_beta"])
 events=events.merge(market,on=["event_key","news_id"],validate="one_to_one");rows=[]
 with SessionLocal() as s:
  eth,btc=load_candle_grid(s,"ETHUSDT"),load_candle_grid(s,"BTCUSDT")
  for event in events.itertuples(index=False):
   for latency in (0,1,2,3):
    row=calculate_latency_record(int(event.news_id),event.baseline_time,float(event.pre_eth_btc_rolling_beta),eth,btc,latency)
    if row:rows.append(row)
  for start in range(0,len(rows),1000):
   base=insert(news_early_reactions);batch=rows[start:start+1000]
   s.execute(base.values(batch).on_conflict_do_update(index_elements=["news_id","symbol","latency_minutes"],set_={key:getattr(base.excluded,key) for key in batch[0] if key not in {"news_id","symbol","latency_minutes"}}));s.commit()
 print(json.dumps({"events":len(events),"rows":len(rows),"latencies":[0,1,2,3]},indent=2))
if __name__=="__main__":main()
