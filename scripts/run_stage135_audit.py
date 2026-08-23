import json
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
from sqlalchemy import text
from database.db import SessionLocal

REPORTS=Path("reports")
def coverage(frame,time_col,expected_minutes=None):
    if frame.empty:return {"rows":0,"start":None,"end":None,"duplicates":0,"missing_percentage":100.0}
    duplicate=int(frame.duplicated(["symbol",time_col,*(["ratio_type"] if "ratio_type" in frame else [])]).sum())
    missing=0.0
    if expected_minutes:
        expected=((frame[time_col].max()-frame[time_col].min()).total_seconds()/60/expected_minutes)+1;missing=max(0,100*(1-len(frame)/expected))
    return {"rows":len(frame),"start":frame[time_col].min().isoformat(),"end":frame[time_col].max().isoformat(),"duplicates":duplicate,"missing_percentage":float(missing)}
def main():
 REPORTS.mkdir(exist_ok=True)
 with SessionLocal() as s:
  funding=pd.read_sql(text("select symbol,funding_time,funding_rate,mark_price from futures_funding_rates"),s.connection());oi=pd.read_sql(text("select * from futures_open_interest"),s.connection());ratios=pd.read_sql(text("select * from futures_long_short_ratios"),s.connection());taker=pd.read_sql(text("select * from futures_taker_volume"),s.connection())
  early=pd.read_sql(text("select * from news_early_reactions"),s.connection());primary=pd.read_sql(text("select * from primary_source_events"),s.connection());timeline=pd.read_sql(text("select * from event_information_timeline"),s.connection())
 for frame,column in ((funding,"funding_time"),(oi,"timestamp"),(ratios,"timestamp"),(taker,"timestamp")):frame[column]=pd.to_datetime(frame[column],utc=True)
 rows=[]
 for symbol in ("ETHUSDT","BTCUSDT"):
  for metric,frame,column,interval in (("funding",funding,"funding_time",480),("open_interest",oi,"timestamp",5),("long_short",ratios,"timestamp",5),("taker_volume",taker,"timestamp",5)):
   item=coverage(frame.query("symbol == @symbol"),column,interval);rows.append({"symbol":symbol,"metric":metric,"interval_minutes":interval,**item,"api_history_limit":"full endpoint range" if metric=="funding" else "latest 30 days"})
 futures=pd.DataFrame(rows);futures.to_csv(REPORTS/"stage135_futures_coverage.csv",index=False)
 sources=[
  {"source":"ethereum_foundation_blog","category":"primary","earliest_available_date":"2014","latest_available_date":"current","interval":"event","api_limits":"robots + polite requests","free_paid":"free","estimated_cost_usd":0,"license_restrictions":"official site terms/robots","reliability":"high","timestamp_precision":"day/metadata","status":"live_tested"},
  {"source":"sec_press_rss","category":"primary","earliest_available_date":"feed-dependent","latest_available_date":"current","interval":"event","api_limits":"10 requests/s maximum","free_paid":"free","estimated_cost_usd":0,"license_restrictions":"SEC fair-access policy","reliability":"high","timestamp_precision":"RSS timestamp","status":"live_tested"},
  {"source":"binance_announcements","category":"primary","earliest_available_date":"sitemap historical","latest_available_date":"current","interval":"event","api_limits":"HTML returned 202 empty; /bapi prohibited","free_paid":"free","estimated_cost_usd":0,"license_restrictions":"robots disallows undocumented API","reliability":"blocked","timestamp_precision":"unknown","status":"live_tested_blocked"},
  {"source":"binance_futures_funding","category":"futures","earliest_available_date":funding.funding_time.min().isoformat(),"latest_available_date":funding.funding_time.max().isoformat(),"interval":"funding event","api_limits":"500 weight/5min/IP shared","free_paid":"free","estimated_cost_usd":0,"license_restrictions":"Binance API terms","reliability":"high","timestamp_precision":"milliseconds","status":"imported"},
  {"source":"binance_futures_statistics","category":"futures","earliest_available_date":oi.timestamp.min().isoformat(),"latest_available_date":oi.timestamp.max().isoformat(),"interval":"5m","api_limits":"latest 30 days only; 1000 requests/5min","free_paid":"free","estimated_cost_usd":0,"license_restrictions":"Binance API terms","reliability":"high","timestamp_precision":"milliseconds","status":"partial_30d"},
  {"source":"official_eth_etf_daily_flows","category":"etf","earliest_available_date":None,"latest_available_date":None,"interval":"daily","api_limits":"no verified stable official free API","free_paid":"blocked","estimated_cost_usd":None,"license_restrictions":"provider selection required","reliability":"unknown","timestamp_precision":"daily/published_at required","status":"blocked"},
  {"source":"etherscan","category":"onchain","earliest_available_date":"genesis endpoint-dependent","latest_available_date":"current","interval":"block/event","api_limits":"free 3 calls/s, 100000/day; key required","free_paid":"free tier / paid from about 41.65 USD monthly","estimated_cost_usd":0,"license_restrictions":"attribution/API terms","reliability":"medium-high","timestamp_precision":"block","status":"dry_run_key_required"},
  {"source":"fred_alfred","category":"macro","earliest_available_date":"series-dependent","latest_available_date":"current","interval":"daily/monthly","api_limits":"registered key required; adjustable limits","free_paid":"free","estimated_cost_usd":0,"license_restrictions":"FRED terms; vintage required for leakage safety","reliability":"high","timestamp_precision":"daily/release vintage","status":"dry_run_key_required"}]
 audit=pd.DataFrame(sources);audit.to_csv(REPORTS/"stage135_data_source_audit.csv",index=False);(REPORTS/"stage135_data_source_audit.json").write_text(json.dumps(sources,indent=2),encoding="utf-8")
 for name,category in (("stage135_etf_coverage.csv","etf"),("stage135_onchain_coverage.csv","onchain"),("stage135_macro_coverage.csv","macro")):audit.query("category == @category").to_csv(REPORTS/name,index=False)
 # Detailed publication-delay derivatives, latency 0 only.
 e=early.query("latency_minutes == 0").copy();thresholds=(.10,.25,.50,1.0)
 index=pd.read_parquet("reports/stage12_eth_event_index.parquet").query("coverage_status == 'included'")[["news_id","source","published_at","article_count_in_event"]]
 ai=pd.read_parquet("data/stage12/eth_ai_only.parquet",columns=["news_id","ai_category"]);e=e.merge(index,on="news_id",validate="one_to_one").merge(ai,on="news_id",validate="one_to_one");e["year"]=pd.to_datetime(e.published_at,utc=True).dt.year
 delay=[]
 for dimension,column in (("overall",None),("source","source"),("category","ai_category"),("year","year"),("event_group_size","article_count_in_event")):
  groups=[("all",e)] if column is None else e.groupby(column,dropna=False)
  for value,part in groups:
   for threshold in thresholds:
    pre=part.pre_return_5m.abs();post=part.return_5m.abs();before=pre>=threshold;after=post>=threshold
    delay.append({"group_dimension":dimension,"group_value":value,"threshold_percent":threshold,"events":len(part),"late_publication_rate":float((before&(pre>post)).mean()),"reacted_before_article_rate":float((before&~after).mean()),"reacted_after_article_rate":float((~before&after).mean()),"reacted_both_rate":float((before&after).mean()),"no_clear_reaction_rate":float((~before&~after).mean())})
 delay=pd.DataFrame(delay);delay.to_csv(REPORTS/"stage135_publication_delay.csv",index=False)
 reaction=[]
 for latency,part in early.groupby("latency_minutes"):
  for horizon in (1,2,3,5,10,15):
   row={"latency_minutes":latency,"horizon_minutes":horizon,"events":len(part),"median_abs_eth_return":part[f"return_{horizon}m"].abs().median(),"median_abs_btc_return":part[f"btc_return_{horizon}m"].abs().median(),"median_abs_eth_minus_btc":part[f"eth_minus_btc_{horizon}m"].abs().median(),"median_abs_abnormal_return":part[f"abnormal_return_{horizon}m"].abs().median()}
   if horizon in (1,3,5,10,15):row.update({"median_max_absolute_excursion":part[f"max_absolute_{horizon}m"].median(),"median_high_low_range":part[f"high_low_range_{horizon}m"].median(),"median_realized_vol":part[f"realized_vol_{horizon}m"].median(),"median_volume_shock":part[f"volume_shock_{horizon}m"].median(),"median_time_to_max_move":part[f"time_to_max_move_{horizon}m"].median()})
   reaction.append(row)
 pd.DataFrame(reaction).to_csv(REPORTS/"stage135_early_reaction_metrics.csv",index=False)
 # aliases required by the detailed section
 delay.to_csv(REPORTS/"stage135_eth_publication_delay.csv",index=False);pd.read_csv(REPORTS/"stage135_early_reaction_metrics.csv").to_csv(REPORTS/"stage135_eth_early_reaction_metrics.csv",index=False)
 source_delay=pd.read_csv(REPORTS/"stage13a_eth_source_timing.csv");category_delay=pd.read_csv(REPORTS/"stage13a_eth_category_timing.csv")
 source_delay.to_csv(REPORTS/"stage135_eth_source_delay.csv",index=False);source_delay.to_csv(REPORTS/"stage135_source_delay.csv",index=False)
 category_delay.to_csv(REPORTS/"stage135_eth_category_delay.csv",index=False);category_delay.to_csv(REPORTS/"stage135_category_delay.csv",index=False)
 print(json.dumps({"early_rows":len(early),"primary_events":len(primary),"timeline_rows":len(timeline),"futures_rows":{x:len(y) for x,y in (("funding",funding),("oi",oi),("ratios",ratios),("taker",taker))}},indent=2))
if __name__=="__main__":main()
