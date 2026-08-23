from __future__ import annotations
import hashlib,json
from pathlib import Path
import pandas as pd
from sqlalchemy import text
from database.db import SessionLocal
from market_intelligence.futures.futures_feature_builder import build_futures_features
from .feature_registry import IDENTITY,assert_no_post_news_features

VERSION="stage135_eth_v1"
def _sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def build_stage135_datasets(root:Path):
    manifest12=json.loads((root/"data/stage12/manifest.json").read_text(encoding="utf-8"));market=pd.read_parquet(root/"data/stage12/eth_market_only.parquet");targets12=pd.read_parquet(root/"data/stage12/eth_targets.parquet")
    features=[c for c in manifest12["feature_list"] if c in market and not c.startswith("ai_")];core=market[IDENTITY+features].copy();core["dataset_version"]=VERSION
    core["baseline_time"]=pd.to_datetime(core.baseline_time,utc=True).astype("datetime64[ns, UTC]");core["published_at"]=pd.to_datetime(core.published_at,utc=True).astype("datetime64[ns, UTC]")
    events=core[["event_key","baseline_time"]].copy()
    with SessionLocal() as s:
        funding=pd.read_sql(text("select symbol,funding_time,funding_rate,mark_price from futures_funding_rates"),s.connection());oi=pd.read_sql(text("select symbol,timestamp,open_interest,open_interest_value,period from futures_open_interest"),s.connection());ratios=pd.read_sql(text("select symbol,timestamp,ratio_type,long_short_ratio,period from futures_long_short_ratios"),s.connection());taker=pd.read_sql(text("select symbol,timestamp,buy_sell_ratio,buy_volume,sell_volume,period from futures_taker_volume"),s.connection())
        early=pd.read_sql(text("select * from news_early_reactions where latency_minutes=0 and symbol='ETHUSDT'"),s.connection());timeline=pd.read_sql(text("select * from event_information_timeline"),s.connection())
    for frame,column in ((funding,"funding_time"),(oi,"timestamp"),(ratios,"timestamp"),(taker,"timestamp")):frame[column]=pd.to_datetime(frame[column],utc=True).astype("datetime64[ns, UTC]")
    futures=build_futures_features(events,funding,oi,ratios,taker);market_futures=core.merge(futures.drop(columns="baseline_time"),on="event_key",validate="one_to_one")
    up=market_futures.pre_eth_return_5m>0;oi_up=market_futures.pre_oi_change_5m>0
    market_futures["price_up_oi_up"]=(up&oi_up).astype("Int64");market_futures["price_up_oi_down"]=(up&~oi_up).astype("Int64")
    market_futures["price_down_oi_up"]=(~up&oi_up).astype("Int64");market_futures["price_down_oi_down"]=(~up&~oi_up).astype("Int64")
    market_futures["possible_short_squeeze"]=(market_futures.crowded_short.eq(1)&up&oi_up).astype("Int64");market_futures["possible_long_squeeze"]=(market_futures.crowded_long.eq(1)&~up&oi_up).astype("Int64")
    pre_cols=[f"pre_return_{h}m" for h in (1,2,3,5,10,15)];early=early[["news_id",*pre_cols,*[f"abnormal_return_{h}m" for h in (1,3,5,15)],"realized_vol_5m","return_5m"]]
    timeline_features=timeline[["event_key","primary_source_time","delay_seconds","grouping_confidence"]].copy();timeline_features["primary_source_time"]=pd.to_datetime(timeline_features.primary_source_time,utc=True)
    timing=core[["event_key","news_id","baseline_time"]].merge(early,on="news_id",validate="one_to_one").merge(timeline_features,on="event_key",how="left",validate="one_to_one")
    known=timing.primary_source_time.notna()&(timing.primary_source_time<=timing.baseline_time);timing["pre_primary_source_found"]=known.astype(int);timing["pre_primary_lead_seconds"]=timing.delay_seconds.where(known);timing["pre_primary_grouping_confidence"]=timing.grouping_confidence.where(known)
    predictive_timing=timing[["event_key",*pre_cols,"pre_primary_source_found","pre_primary_lead_seconds","pre_primary_grouping_confidence"]]
    combined=market_futures.merge(predictive_timing,on="event_key",validate="one_to_one")
    target=targets12[IDENTITY+["target_abs_abnormal_return_1h","target_realized_vol_15m","target_realized_vol_1h"]].copy();target["dataset_version"]=VERSION
    early_targets=timing[["event_key","news_id",*[f"abnormal_return_{h}m" for h in (1,3,5,15)],"realized_vol_5m","return_5m","pre_return_5m"]]
    target=target.merge(early_targets.drop(columns="news_id"),on="event_key",validate="one_to_one")
    for h in (1,3,5,15):target[f"target_abs_abnormal_return_{h}m"]=target[f"abnormal_return_{h}m"].abs()
    target=target.rename(columns={"realized_vol_5m":"target_realized_vol_5m"});target["target_post_news_move_stronger_than_pre_move"]=(target.return_5m.abs()>target.pre_return_5m.abs()).astype(int);target["target_new_information_reaction"]=((target.return_5m.abs()>=.10)&(target.return_5m.abs()>target.pre_return_5m.abs())).astype(int);target["target_late_article"]=((target.pre_return_5m.abs()>=.10)&(target.pre_return_5m.abs()>target.return_5m.abs())).astype(int)
    target=target.drop(columns=[*[f"abnormal_return_{h}m" for h in (1,3,5,15)],"return_5m","pre_return_5m"])
    variants={"market_core":core,"market_futures":market_futures,"market_futures_primary_timing":combined};out=root/"data/stage135";out.mkdir(parents=True,exist_ok=True)
    files={}
    for name,frame in variants.items():
        feature_columns=[c for c in frame if c not in IDENTITY];assert_no_post_news_features(feature_columns);path=out/f"{name}.parquet";frame.to_parquet(path,index=False);files[str(path.relative_to(root)).replace('\\','/')]=_sha(path)
    target_path=out/"targets.parquet";target.to_parquet(target_path,index=False);files[str(target_path.relative_to(root)).replace('\\','/')]=_sha(target_path)
    cutoff_violations=int((timing.loc[known,"primary_source_time"]>timing.loc[known,"baseline_time"]).sum())
    return variants,target,{"dataset_version":VERSION,"row_count":len(core),"variants":{k:{"rows":len(v),"features":len([c for c in v if c not in IDENTITY])} for k,v in variants.items()},"targets":[c for c in target if c.startswith("target_")],"split_counts":core.split.value_counts().to_dict(),"event_split_overlap":0,"post_news_features_in_predictors":0,"cutoff_violations":cutoff_violations,"file_hashes_sha256":files,"stage12_schema_hash":manifest12["schema_hash"]}
