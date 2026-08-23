from __future__ import annotations
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from sqlalchemy import text
from high_impact_sources.config import DATASETS,HORIZONS,PROMPT_VERSION,STAGE16_DATASET_VERSION

def chronological_split(frame):
    ordered=frame.sort_values(["metadata_published_at","metadata_event_id"]).index;n=len(ordered);a=int(n*.6);b=int(n*.8);out=pd.Series(index=frame.index,dtype="object");out.loc[ordered[:a]]="train";out.loc[ordered[a:b]]="validation";out.loc[ordered[b:]]="test";return out
def _hash(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def build(session,reports_dir:Path,manifest_name="stage16_dataset_manifest.json"):
    query=text("""SELECT e.id event_id,e.source,e.source_type,e.platform,e.author_name,e.author_handle,e.published_at,e.discovered_at,e.time_confidence,e.source_authenticity,e.crypto_relevance,e.event_group_id,a.asset,a.relevance asset_relevance,r.symbol,r.baseline_time,r.pre_context_json,
      an.event_type,an.information_status,an.source_reliability ai_source_reliability,an.novelty ai_novelty,an.importance ai_importance,an.specificity ai_specificity,an.confidence ai_confidence,
      an.surprise_level ai_surprise_level,an.surprise_evidence ai_surprise_evidence,an.first_disclosure ai_first_disclosure,an.actionability ai_actionability,an.institutional_relevance ai_institutional_relevance,an.retail_relevance ai_retail_relevance,an.market_scope ai_market_scope,an.regulatory_strength ai_regulatory_strength,an.economic_significance ai_economic_significance,an.technical_significance ai_technical_significance,an.security_significance ai_security_significance,an.adoption_significance ai_adoption_significance,an.execution_certainty ai_execution_certainty,an.urgency ai_urgency,an.fundamental_relevance ai_fundamental_relevance,an.temporary_vs_structural ai_temporary_vs_structural,an.evidence_quality ai_evidence_quality,an.assets_json ai_assets_json,
      r.return_1m,r.return_5m,r.return_10m,r.return_20m,r.return_40m,r.return_1h,r.return_3h,r.return_5h,r.return_8h,r.return_12h,
      r.abnormal_return_1m,r.abnormal_return_5m,r.abnormal_return_10m,r.abnormal_return_20m,r.abnormal_return_40m,r.abnormal_return_1h,r.abnormal_return_3h,r.abnormal_return_5h,r.abnormal_return_8h,r.abnormal_return_12h,r.max_favorable_1h,r.max_adverse_1h,r.max_absolute_1h,r.max_favorable_12h,r.max_adverse_12h,r.max_absolute_12h,r.realized_vol_1h,r.realized_vol_12h
      FROM high_impact_events e JOIN high_impact_event_assets a ON a.event_id=e.id JOIN high_impact_market_reactions r ON r.event_id=e.id AND r.symbol=CASE a.asset WHEN 'BTC' THEN 'BTCUSDT' WHEN 'ETH' THEN 'ETHUSDT' ELSE 'SOLUSDT' END AND r.latency_minutes=0
      LEFT JOIN high_impact_event_analysis an ON an.event_id=e.id AND an.status='success' AND an.model_name='gpt-5-mini' AND an.prompt_version=:prompt_version WHERE e.status='accepted' ORDER BY e.published_at,e.id,a.asset""")
    raw=pd.read_sql(query,session.connection(),params={"prompt_version":PROMPT_VERSION});records=[];targets=[]
    group_counts=raw.groupby("event_group_id").event_id.transform("nunique") if len(raw) else pd.Series(dtype=int)
    for pos,row in raw.iterrows():
        pre=row.pre_context_json or {};ai_assets=row.ai_assets_json or [];ai_asset=next((item for item in ai_assets if item.get("asset")==row.asset),{})
        base={"metadata_event_id":int(row.event_id),"metadata_published_at":row.published_at,"metadata_asset":row.asset,"metadata_symbol":row.symbol,"metadata_source":row.source,"metadata_source_type":row.source_type,"metadata_platform":row.platform,"metadata_author_name":row.author_name,"metadata_author_handle":row.author_handle,"metadata_event_group_id":row.event_group_id,"metadata_split":"","source_time_confidence":float(row.time_confidence),"source_authenticity":float(row.source_authenticity),"source_crypto_relevance":float(row.crypto_relevance),"source_asset_relevance":float(row.asset_relevance),"source_event_type":row.event_type,"source_information_status":row.information_status,"ai_source_reliability":row.ai_source_reliability,"ai_novelty":row.ai_novelty,"ai_importance":row.ai_importance,"ai_specificity":row.ai_specificity,"ai_confidence":row.ai_confidence,"ai_surprise_level":row.ai_surprise_level,"ai_surprise_evidence":row.ai_surprise_evidence,"ai_first_disclosure":row.ai_first_disclosure,"ai_actionability":row.ai_actionability,"ai_institutional_relevance":row.ai_institutional_relevance,"ai_retail_relevance":row.ai_retail_relevance,"ai_market_scope":row.ai_market_scope,"ai_regulatory_strength":row.ai_regulatory_strength,"ai_economic_significance":row.ai_economic_significance,"ai_technical_significance":row.ai_technical_significance,"ai_security_significance":row.ai_security_significance,"ai_adoption_significance":row.ai_adoption_significance,"ai_execution_certainty":row.ai_execution_certainty,"ai_urgency":row.ai_urgency,"ai_fundamental_relevance":row.ai_fundamental_relevance,"ai_temporary_vs_structural":row.ai_temporary_vs_structural,"ai_evidence_quality":row.ai_evidence_quality,"ai_asset_relevance":ai_asset.get("relevance"),"ai_content_valence":ai_asset.get("content_valence"),"ai_content_valence_score":ai_asset.get("content_valence_score"),"ai_directness":ai_asset.get("directness"),**pre,"timing_ingestion_delay_seconds":(row.discovered_at-row.published_at).total_seconds(),"timing_event_group_source_count":int(group_counts.iloc[pos])}
        records.append(base);target={"metadata_event_id":int(row.event_id),"metadata_asset":row.asset,"metadata_published_at":row.published_at}
        for label in HORIZONS:
            value=row[f"return_{label}"];abnormal=row[f"abnormal_return_{label}"];target[f"target_return_{label}"]=value;target[f"target_direction_{label}"]="positive" if value>.1 else "negative" if value<-.1 else "neutral";target[f"target_abs_return_{label}"]=abs(value);target[f"target_abnormal_return_{label}"]=abnormal;target[f"target_abs_abnormal_return_{label}"]=abs(abnormal)
            for threshold in (.25,.5,1,2,3):target[f"target_strong_{label}_{str(threshold).replace('.','_')}"]=int(abs(value)>=threshold)
            for name,bps in {"low":4,"base":10,"stress":25}.items():target[f"target_exceeds_{name}_cost_{label}"]=int(abs(value)>bps/100)
        for name in ("max_favorable_1h","max_adverse_1h","max_absolute_1h","max_favorable_12h","max_adverse_12h","max_absolute_12h","realized_vol_1h","realized_vol_12h"):target[f"target_{name}"]=row[name]
        targets.append(target)
    features=pd.DataFrame(records);target_frame=pd.DataFrame(targets)
    if len(features):features["metadata_split"]=chronological_split(features)
    forbidden=[c for c in features if c.startswith(("target_","return_","abnormal_return_","future_"))]
    if forbidden:raise ValueError(f"post-event leakage in features: {forbidden}")
    DATASETS.mkdir(parents=True,exist_ok=True);reports_dir.mkdir(parents=True,exist_ok=True)
    source_cols=[c for c in features if c.startswith(("metadata_","source_","ai_"))]
    market_cols=[c for c in features if c.startswith("pre_") or c in ("metadata_event_id","metadata_published_at","metadata_asset","metadata_symbol","metadata_split")]
    variants={"a_source_only":features[source_cols],"b_market_only":features[market_cols],"c_source_market":features[sorted(set(source_cols+market_cols),key=lambda x:list(features).index(x))],"d_source_market_timing":features}
    files={}
    for name,frame in variants.items():path=DATASETS/f"{name}.parquet";frame.to_parquet(path,index=False);files[str(path)]=_hash(path)
    target_path=DATASETS/"targets.parquet";target_frame.to_parquet(target_path,index=False);files[str(target_path)]=_hash(target_path)
    manifest={"dataset_version":STAGE16_DATASET_VERSION,"rows":len(features),"target_rows":len(target_frame),"variants":{k:list(v.columns) for k,v in variants.items()},"targets":list(target_frame.columns),"leakage_violations":len(forbidden),"files":files,"split_counts":features.metadata_split.value_counts().to_dict() if len(features) else {}}
    (reports_dir/manifest_name).write_text(json.dumps(manifest,indent=2,default=str),encoding="utf-8");return features,target_frame,manifest
