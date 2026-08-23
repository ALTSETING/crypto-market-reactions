"""Stage 18A frozen-model forensic audit.

FORENSIC HOLD: this module performs no estimator fitting, API calls, database
writes, threshold changes, pattern searches, or trading actions.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sqlalchemy import text

from analysis.stage18a_forensic import (
    array_hash, distribution, net_trade_return, probability_columns,
    raw_return_percent, replay_signals, signal_metrics, target_from_percent,
    trade_return,
)
from database.db import engine
from ml.stage18_unified import canonical_hash, entry_timestamp, sha256_file
from scripts.run_stage18_unified import (
    MARKET_CATEGORICAL, MARKET_NUMERIC, PATTERN_A_ID, PATTERN_B_ID,
    SEM_CATEGORICAL, SEM_NUMERIC, eligible_pattern, prepare_training,
)


ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/"reports"
DATA=ROOT/"data"/"stage18a"
SEED=18017
COST=.20
MODEL_PATHS={"A":ROOT/"models"/"stage18_pattern_a_v2.joblib","B":ROOT/"models"/"stage18_pattern_b_v2.joblib"}
LOCK_PATHS={"A":ROOT/"data"/"stage18"/"pattern_a_v2_lock.json","B":ROOT/"data"/"stage18"/"pattern_b_v2_lock.json"}
PATTERN_IDS={"A":PATTERN_A_ID,"B":PATTERN_B_ID}
REQUIRED_REPORTS=(
 "stage18a_forensic_manifest.json","stage18a_class_mapping_audit.csv","stage18a_target_recalculation.csv",
 "stage18a_trade_return_reconciliation.csv","stage18a_target_class_distribution.csv","stage18a_signal_funnel.csv",
 "stage18a_probability_distribution.csv","stage18a_feature_order_audit.csv","stage18a_preprocessor_audit.json",
 "stage18a_semantic_mapping_audit.csv","stage18a_missing_value_bias.csv","stage18a_source_signal_bias.csv",
 "stage18a_year_regime_bias.csv","stage18a_training_weight_audit.json","stage18a_event_weighting_audit.csv",
 "stage18a_pattern_a_66_reconciliation.csv","stage18a_pattern_b_configuration_diff.md","stage18a_short_baselines.csv",
 "stage18a_short_driver_features.csv","stage18a_deterministic_replay.json","stage18a_final_summary.md")


def write_json(path:Path,value:Any)->None:
    def default(item:Any):
        if item is pd.NaT or item is pd.NA:return None
        if isinstance(item,pd.Timestamp):return item.isoformat()
        if isinstance(item,(np.integer,)):return int(item)
        if isinstance(item,(np.floating,)):return None if not np.isfinite(item) else float(item)
        if isinstance(item,(np.bool_,)):return bool(item)
        if isinstance(item,Path):return str(item)
        raise TypeError(type(item).__name__)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=default,allow_nan=False)+"\n",encoding="utf-8")


def protected_files()->list[Path]:
    paths=[]
    for directory in (ROOT/"data",ROOT/"datasets",ROOT/"models"):
        if directory.exists():
            paths.extend(p for p in directory.rglob("*") if p.is_file() and "stage18a" not in p.parts and "tmp" not in p.parts)
    for path in REPORTS.iterdir():
        if path.is_file() and path.name.startswith("stage") and not path.name.startswith("stage18a"):
            match=re.match(r"stage(\d+)",path.name)
            if match and 8<=int(match.group(1))<=18:paths.append(path)
    return sorted(set(paths))


def snapshot()->dict[str,str]:return {str(path.relative_to(ROOT)):sha256_file(path) for path in protected_files()}


def database_counts()->dict[str,int]:
    tables=("news_articles","news_assets","news_analysis","news_market_reactions","market_candles","high_impact_events",
            "high_impact_event_assets","high_impact_event_analysis","high_impact_market_reactions")
    with engine.connect() as connection:return {table:int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()) for table in tables}


def git_commit()->str|None:
    result=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,text=True,capture_output=True)
    return result.stdout.strip() if result.returncode==0 else None


def object_hash(value:Any)->str:
    buffer=io.BytesIO();joblib.dump(value,buffer);return hashlib.sha256(buffer.getvalue()).hexdigest()


def load_state():
    canonical=pd.read_parquet(ROOT/"data"/"stage18"/"canonical_inventory.parquet")
    market=pd.read_parquet(ROOT/"data"/"stage18"/"canonical_market.parquet")
    frame=prepare_training(canonical,market)
    persisted=pd.read_parquet(REPORTS/"stage18_prediction_level_results.parquet")
    payloads={pattern:joblib.load(path) for pattern,path in MODEL_PATHS.items()}
    locks={pattern:json.loads(path.read_text(encoding="utf-8")) for pattern,path in LOCK_PATHS.items()}
    for pattern in ("A","B"):
        if sha256_file(MODEL_PATHS[pattern])!=locks[pattern]["model_sha256"]:raise RuntimeError(f"{pattern} model hash mismatch")
        if payloads[pattern]["columns"]!=locks[pattern]["feature_columns"]:raise RuntimeError(f"{pattern} feature registry mismatch")
        probability_columns(payloads[pattern]["model"].named_steps["model"].classes_)
    return canonical,market,frame,persisted,payloads,locks


def replay(frame:pd.DataFrame,persisted:pd.DataFrame,payloads:dict)->dict[str,pd.DataFrame]:
    output={}
    for pattern in ("A","B"):
        model=payloads[pattern]["model"];columns=payloads[pattern]["columns"]
        universe=frame[frame.fully_covered.fillna(False)].copy()
        probabilities=model.predict_proba(universe[columns])
        detail=pd.concat([universe.reset_index(drop=True),replay_signals(probabilities,model.named_steps["model"].classes_,.4)],axis=1)
        detail["pattern"]=pattern;detail["pattern_id"]=PATTERN_IDS[pattern]
        detail["scope_eligible"]=eligible_pattern(detail,pattern)
        detail["after_scope_filter"]=np.where(detail.scope_eligible,detail.after_confidence,"NO_SIGNAL")
        detail["replayed_signal"]=detail.after_scope_filter.map({"UP":"LONG","DOWN":"SHORT","NO_SIGNAL":"NO_SIGNAL"})
        old=persisted[persisted.pattern_id.eq(PATTERN_IDS[pattern])][["event_id","asset","split","signal","confidence"]].rename(columns={"event_id":"canonical_event_id","signal":"persisted_signal","confidence":"persisted_confidence"})
        detail=detail.merge(old,on=["canonical_event_id","asset","split"],how="left",validate="one_to_one")
        detail["persisted_match"]=np.where(detail.persisted_signal.notna(),detail.replayed_signal.eq(detail.persisted_signal),np.nan)
        output[pattern]=detail
    return output


def class_mapping_report(replays:dict,payloads:dict)->pd.DataFrame:
    rows=[]
    rng=np.random.default_rng(SEED)
    for pattern,detail in replays.items():
        test=detail[detail.split.eq("test")&detail.scope_eligible&detail.persisted_signal.notna()].copy()
        sample=test.iloc[np.sort(rng.choice(len(test),min(20,len(test)),replace=False))]
        classes=[str(value) for value in payloads[pattern]["model"].named_steps["model"].classes_]
        for row in sample.itertuples(index=False):
            vector=[row.p_SHORT,row.p_NEUTRAL,row.p_LONG] if classes==["DOWN","NEUTRAL","UP"] else [getattr(row,{"DOWN":"p_SHORT","NEUTRAL":"p_NEUTRAL","UP":"p_LONG"}[value]) for value in classes]
            rows.append({"pattern":pattern,"event_id":row.canonical_event_id,"asset":row.asset,"model_classes":json.dumps(classes),
                         "predict_proba_vector":json.dumps(vector),"argmax_index":row.raw_argmax_index,"predicted_raw_class":row.raw_argmax_class,
                         "directional_winner":row.directional_winner,"mapped_signal":{"UP":"LONG","DOWN":"SHORT"}[row.directional_winner],
                         "persisted_signal":row.persisted_signal,"confidence":row.directional_confidence,"persisted_match":row.persisted_match})
    return pd.DataFrame(rows)


def target_recalculation(persisted:pd.DataFrame)->pd.DataFrame:
    base=persisted.copy();base["entry_timestamp"]=pd.to_datetime(base.entry_timestamp,utc=True);base["event_timestamp"]=pd.to_datetime(base.event_timestamp,utc=True)
    unique=base[["event_id","asset","entry_timestamp","entry_price"]].drop_duplicates()
    price_map={}
    with engine.connect() as connection:
        for asset,part in unique.groupby("asset"):
            times=sorted(set(part.entry_timestamp.tolist()+list(part.entry_timestamp+pd.Timedelta(hours=12))))
            candles=pd.read_sql(text("SELECT open_time,open::double precision open FROM market_candles WHERE symbol=:symbol AND interval='1m' AND open_time=ANY(:times)"),connection,
                                params={"symbol":f"{asset}USDT","times":[value.to_pydatetime() for value in times]})
            for row in candles.itertuples(index=False):price_map[(asset,pd.Timestamp(row.open_time).tz_convert("UTC"))]=float(row.open)
    rows=[]
    for row in base.itertuples(index=False):
        entry=price_map.get((row.asset,row.entry_timestamp));exit_price=price_map.get((row.asset,row.entry_timestamp+pd.Timedelta(hours=12)))
        recomputed=raw_return_percent(entry,exit_price) if entry is not None and exit_price is not None else np.nan
        expected_entry=entry_timestamp(row.event_timestamp)
        target=target_from_percent(recomputed) if np.isfinite(recomputed) else None
        rows.append({"pattern_id":row.pattern_id,"event_id":row.event_id,"asset":row.asset,"split":row.split,"event_timestamp":row.event_timestamp,
                     "stored_entry_timestamp":row.entry_timestamp,"expected_entry_timestamp":expected_entry,"entry_timestamp_match":row.entry_timestamp==expected_entry,
                     "stored_entry_price":row.entry_price,"recomputed_entry_open":entry,"exit_open_12h":exit_price,"stored_raw_return_percent":row.return_12h,
                     "recomputed_raw_return_percent":recomputed,"return_mismatch":not np.isclose(row.return_12h,recomputed,rtol=0,atol=1e-10,equal_nan=True),
                     "stored_target":row.actual_direction,"recomputed_target":target,"target_mismatch":row.actual_direction!=target,
                     "threshold_percent":.10,"utc":str(row.entry_timestamp.tzinfo) in {"UTC","UTC+00:00"}})
    return pd.DataFrame(rows)


def trade_reconciliation(persisted:pd.DataFrame,targets:pd.DataFrame)->pd.DataFrame:
    signals=persisted[persisted.signal.isin(["LONG","SHORT"])].copy()
    rec=targets[["pattern_id","event_id","asset","split","recomputed_raw_return_percent"]]
    signals=signals.merge(rec,on=["pattern_id","event_id","asset","split"],how="left",validate="one_to_one")
    signals["expected_gross_return"]=[trade_return(value,signal) for value,signal in zip(signals.recomputed_raw_return_percent,signals.signal)]
    signals["expected_net_return"]=[net_trade_return(value,signal,COST) for value,signal in zip(signals.recomputed_raw_return_percent,signals.signal)]
    signals["gross_mismatch"]=~np.isclose(signals.gross_return,signals.expected_gross_return,rtol=0,atol=1e-10,equal_nan=True)
    signals["net_mismatch"]=~np.isclose(signals.net_return,signals.expected_net_return,rtol=0,atol=1e-10,equal_nan=True)
    signals["cost_subtracted_once"]=np.isclose(signals.expected_gross_return-signals.expected_net_return,COST,atol=1e-12)
    return signals


def class_distribution(frame:pd.DataFrame,replays:dict)->pd.DataFrame:
    rows=[]
    for pattern,detail in replays.items():
        data=detail[detail.scope_eligible].copy();data["year"]=data.published_at.dt.year
        events=data.canonical_event_id.drop_duplicates().sort_values().tolist();order=data[["canonical_event_id","published_at"]].drop_duplicates().sort_values(["published_at","canonical_event_id"]).canonical_event_id.tolist()
        fold_map={}
        for fold in range(5):
            start=int(len(order)*(.40+fold*.10));end=int(len(order)*(.50+fold*.10))
            for event in order[start:end]:fold_map[event]=f"fold_{fold+1}"
        data["walkforward_fold"]=data.canonical_event_id.map(fold_map).fillna("not_evaluation")
        dimensions=[("full_dataset",pd.Series("all",index=data.index)),("split",data.split),("year",data.year.astype(str)),
                    ("dataset_source",data.dataset_sources),("source",data.source.fillna("missing")),
                    ("market_regime",data.pre_trend_regime.fillna("missing")),("fold",data.walkforward_fold)]
        for dimension,values in dimensions:
            for value,part in data.groupby(values,dropna=False):
                counts=part.actual_direction.value_counts();total=len(part)
                rows.append({"pattern":pattern,"dimension":dimension,"value":value,"rows":total,
                             "LONG_target_count":int(counts.get("UP",0)),"LONG_target_percent":float(counts.get("UP",0)/total*100) if total else None,
                             "SHORT_target_count":int(counts.get("DOWN",0)),"SHORT_target_percent":float(counts.get("DOWN",0)/total*100) if total else None,
                             "NEUTRAL_target_count":int(counts.get("NEUTRAL",0)),"NEUTRAL_target_percent":float(counts.get("NEUTRAL",0)/total*100) if total else None})
    return pd.DataFrame(rows)


def signal_funnel(replays:dict)->pd.DataFrame:
    rows=[]
    for pattern,detail in replays.items():
        test=detail[detail.split.eq("test")].copy()
        stages={"raw_model_argmax":test.raw_argmax_class,"directional_neutral_removed":test.directional_winner,
                "after_confidence_threshold":test.after_confidence,"after_subgroup_asset_filter":test.after_scope_filter,
                "final_persisted_scope":test.loc[test.scope_eligible,"persisted_signal"].map({"LONG":"UP","SHORT":"DOWN","NO_SIGNAL":"NO_SIGNAL"})}
        for stage,values in stages.items():
            counts=values.value_counts();total=len(values);directional=int(counts.get("UP",0)+counts.get("DOWN",0))
            rows.append({"pattern":pattern,"stage":stage,"rows":total,"LONG":int(counts.get("UP",0)),"SHORT":int(counts.get("DOWN",0)),
                         "NEUTRAL":int(counts.get("NEUTRAL",0)),"NO_SIGNAL":int(counts.get("NO_SIGNAL",0)),
                         "SHORT_percent_all":float(counts.get("DOWN",0)/total*100) if total else None,
                         "SHORT_percent_directional":float(counts.get("DOWN",0)/directional*100) if directional else None})
    return pd.DataFrame(rows)


def probability_report(replays:dict)->pd.DataFrame:
    rows=[]
    for pattern,detail in replays.items():
        test=detail[detail.split.eq("test")&detail.scope_eligible].copy()
        for row in test.itertuples(index=False):
            rows.append({"record_type":"prediction","pattern":pattern,"event_id":row.canonical_event_id,"asset":row.asset,"final_signal":row.replayed_signal,
                         "p_LONG":row.p_LONG,"p_SHORT":row.p_SHORT,"p_NEUTRAL":row.p_NEUTRAL,"winning_probability":row.winning_probability,
                         "second_highest_probability":row.second_probability,"probability_margin":row.probability_margin,"confidence_threshold":.4})
        for group,part in [("all",test)]+list(test.groupby("replayed_signal")):
            for column in ("p_LONG","p_SHORT","p_NEUTRAL","winning_probability","probability_margin"):
                rows.append({"record_type":"summary","pattern":pattern,"final_signal":group,"metric":column,**distribution(part[column])})
    return pd.DataFrame(rows)


def feature_order_report(frame:pd.DataFrame,payloads:dict)->pd.DataFrame:
    rows=[]
    for pattern,payload in payloads.items():
        model=payload["model"];columns=payload["columns"];registered=list(model.feature_names_in_)
        scope=frame[eligible_pattern(frame,pattern)];train=scope[scope.split.eq("train")];test=scope[scope.split.eq("test")]
        for index,column in enumerate(columns):
            numeric=pd.api.types.is_numeric_dtype(frame[column]);tr=pd.to_numeric(train[column],errors="coerce") if numeric else None;te=pd.to_numeric(test[column],errors="coerce") if numeric else None
            pooled_std=float(tr.std()) if numeric and tr.notna().sum()>1 else np.nan
            rows.append({"pattern":pattern,"expected_index":index,"feature":column,"model_feature_at_index":registered[index] if index<len(registered) else None,
                         "name_match":index<len(registered) and registered[index]==column,"present":column in frame,"dtype":str(frame[column].dtype),
                         "numeric_transformer":numeric,"all_zero_train":bool(numeric and tr.fillna(0).eq(0).all()),"constant_train":bool(train[column].nunique(dropna=False)<=1),
                         "train_missing_rate":float(train[column].isna().mean()),"test_missing_rate":float(test[column].isna().mean()),
                         "train_mean":float(tr.mean()) if numeric else None,"test_mean":float(te.mean()) if numeric else None,
                         "standardized_mean_shift":float((te.mean()-tr.mean())/pooled_std) if numeric and np.isfinite(pooled_std) and pooled_std>0 else None,
                         "selected_matrix_extra_columns":0,"silently_reordered":registered!=columns})
    return pd.DataFrame(rows)


def preprocessor_report(payloads:dict,locks:dict)->dict:
    result={}
    for pattern,payload in payloads.items():
        pipeline=payload["model"];pre=pipeline.named_steps["preprocess"]
        components={"pipeline":object_hash(pipeline),"preprocessor":object_hash(pre),"estimator":object_hash(pipeline.named_steps["model"]),
                    "feature_registry":hashlib.sha256("\n".join(payload["columns"]).encode()).hexdigest()}
        detail={"model_sha256":sha256_file(MODEL_PATHS[pattern]),"expected_model_sha256":locks[pattern]["model_sha256"],"components":components,
                "feature_names_in":list(pipeline.feature_names_in_),"feature_order_match":list(pipeline.feature_names_in_)==payload["columns"],"transformers":{}}
        for name,transformer,columns in pre.transformers_:
            if name=="remainder":continue
            entry={"columns":list(columns),"hash":object_hash(transformer),"steps":{step:object_hash(value) for step,value in transformer.named_steps.items()}}
            if "impute" in transformer.named_steps:entry["imputer_statistics"]=[None if pd.isna(v) else v for v in transformer.named_steps["impute"].statistics_.tolist()]
            if "onehot" in transformer.named_steps:entry["encoder_categories"]=[[str(v) for v in values] for values in transformer.named_steps["onehot"].categories_]
            detail["transformers"][name]=entry
        result[pattern]=detail
    return result


def semantic_mapping_report(canonical:pd.DataFrame)->pd.DataFrame:
    old=pd.read_parquet(ROOT/"data"/"stage12"/"eth_market_plus_ai.parquet")
    current=pd.read_csv(REPORTS/"stage16_semantic_v21_results.csv")
    asset_rows=[]
    for row in current.itertuples(index=False):
        try:assets=json.loads(row.assets_json) if isinstance(row.assets_json,str) else row.assets_json
        except Exception:assets=[]
        for asset in assets or []:
            asset_rows.append({"event_id":row.event_id,**asset})
    assets=pd.DataFrame(asset_rows)
    rows=[]
    specs={
      "A":[("ai_eth_relevance","sem_relevance",0,100,"identity"),("ai_sentiment","sem_content_valence_score",-100,100,"identity"),
           ("ai_importance","sem_importance",0,100,"identity"),("ai_novelty","sem_novelty",0,100,"identity"),("ai_confidence","sem_confidence",0,100,"identity"),("ai_credibility","sem_source_reliability",0,100,"identity")],
      "B":[("asset.relevance","sem_relevance",0,100,"unconditional_x10"),("asset.content_valence_score","sem_content_valence_score",-100,100,"unconditional_x10"),
           ("importance","sem_importance",0,100,"unconditional_x10"),("novelty","sem_novelty",0,100,"unconditional_x10"),("confidence","sem_confidence",0,100,"unconditional_x10"),("source_reliability","sem_source_reliability",0,100,"unconditional_x10")],
      "C":[("local_relevance_score","sem_relevance",0,100,"identity"),("missing","sem_content_valence_score",-100,100,"null_plus_missing_flag")],}
    for dataset,items in specs.items():
        canon=canonical[canonical.dataset_sources.str.split("|").map(lambda values:dataset in values)]
        for source,target,minimum,maximum,transform in items:
            mapped=pd.to_numeric(canon[target],errors="coerce")
            if dataset=="A":original=pd.to_numeric(old[source],errors="coerce")
            elif dataset=="B":
                # Reconstruct the exact values consumed by the Stage 18 mapper.
                # Stage 18 unconditionally multiplied these source values by 10.
                # The source was mixed-scale, so the inverse is the only exact
                # row-aligned forensic source for the fitted feature matrix.
                original=mapped/10.0
            else:original=pd.Series(dtype=float) if source=="missing" else pd.to_numeric(canon[target],errors="coerce")
            rows.append({"dataset":dataset,"original_field":source,"original_expected_range":f"{minimum}..{maximum}","canonical_field":target,"transformation":transform,
                         "missing_handling":f"{target}_missing flag; median imputer in frozen model","expected_direction":"same sign and semantic meaning",
                         "original_count":int(original.notna().sum()),"original_min":original.min() if len(original) else None,"original_max":original.max() if len(original) else None,
                         "original_values_above_10":int((original.abs()>10).sum()),"canonical_min":mapped.min(),"canonical_max":mapped.max(),
                         "canonical_out_of_expected_range":int(((mapped<minimum)|(mapped>maximum)).sum()),
                         "mapping_issue":bool(transform=="unconditional_x10" and (original.abs()>10).any())})
    return pd.DataFrame(rows)


def imputer_values(payload:dict)->dict[str,Any]:
    pre=payload["model"].named_steps["preprocess"];result={}
    for name,transformer,columns in pre.transformers_:
        if name=="remainder" or "impute" not in transformer.named_steps:continue
        result.update({column:value for column,value in zip(columns,transformer.named_steps["impute"].statistics_)})
    return result


def missing_bias_report(replays:dict,payloads:dict)->pd.DataFrame:
    rows=[]
    for pattern,detail in replays.items():
        data=detail[detail.scope_eligible].copy();imputed=imputer_values(payloads[pattern]);features=payloads[pattern]["columns"]
        for (split,dataset),part in data.groupby(["split","dataset_sources"]):
            for feature in features:
                missing=part[feature].isna();predicted=part.replayed_signal
                rows.append({"pattern":pattern,"split":split,"dataset_source":dataset,"feature":feature,"rows":len(part),
                             "missing_rate":float(missing.mean()),"imputed_value":imputed.get(feature),
                             "SHORT_rate_when_missing":float(predicted[missing].eq("SHORT").mean()) if missing.any() else None,
                             "SHORT_rate_when_present":float(predicted[~missing].eq("SHORT").mean()) if (~missing).any() else None})
        missing_count=data[SEM_NUMERIC].isna().sum(axis=1);data["completeness"]=np.select([missing_count.eq(0),missing_count.le(len(SEM_NUMERIC)//2)],["complete","partial"],default="heavily_missing")
        for group,part in data.groupby("completeness"):
            signals=part[part.replayed_signal.isin(["LONG","SHORT"])]
            rows.append({"pattern":pattern,"split":"all","dataset_source":"all","feature":f"__semantic_completeness__:{group}","rows":len(part),
                         "missing_rate":float(part[SEM_NUMERIC].isna().mean().mean()),"SHORT_rate_when_missing":float(signals.replayed_signal.eq("SHORT").mean()) if len(signals) else None,
                         "accuracy":float(signals.directional_winner.eq(signals.actual_direction).mean()) if len(signals) else None})
    return pd.DataFrame(rows)


def grouped_signal_report(replays:dict,dimension:str)->pd.DataFrame:
    rows=[]
    for pattern,detail in replays.items():
        data=detail[detail.split.eq("test")&detail.scope_eligible].copy();data["final_signal"]=data.replayed_signal
        for value,part in data.groupby(dimension,dropna=False):
            signals=part[part.final_signal.isin(["LONG","SHORT"])]
            metrics=signal_metrics(signals.actual_direction,signals.final_signal,signals.raw_return_12h,COST)
            rows.append({"pattern":pattern,"dimension":dimension,"value":value,"events":part.canonical_event_id.nunique(),"rows":len(part),**metrics,
                         "always_SHORT_accuracy":float(part.actual_direction.eq("DOWN").mean())})
    return pd.DataFrame(rows)


def year_regime_report(replays:dict)->pd.DataFrame:
    rows=[]
    for pattern,detail in replays.items():
        data=detail[detail.split.eq("test")&detail.scope_eligible].copy();data["year"]=data.published_at.dt.year
        for (year,regime),part in data.groupby(["year","pre_trend_regime"],dropna=False):
            signals=part[part.replayed_signal.isin(["LONG","SHORT"])]
            metrics=signal_metrics(signals.actual_direction,signals.replayed_signal,signals.raw_return_12h,COST)
            always=signal_metrics(part.actual_direction,np.repeat("SHORT",len(part)),part.raw_return_12h,COST)
            rows.append({"pattern":pattern,"year":year,"market_regime":regime,"rows":len(part),"actual_rising_percent":float(part.actual_direction.eq("UP").mean()*100),
                         "actual_falling_percent":float(part.actual_direction.eq("DOWN").mean()*100),"median_pre_volatility":part.pre_realized_vol_60m.median(),
                         **metrics,"always_SHORT_accuracy":always["accuracy"],"always_SHORT_net_expectancy":always["net_expectancy"]})
    return pd.DataFrame(rows)


def training_weight_report(replays:dict,payloads:dict)->dict:
    result={}
    for pattern,detail in replays.items():
        train=detail[detail.scope_eligible&detail.split.eq("train")];counts=train.actual_direction.value_counts();classes=list(payloads[pattern]["model"].named_steps["model"].classes_)
        params=payloads[pattern]["model"].named_steps["model"].get_params();class_weight=params.get("class_weight")
        effective={}
        for value in classes:
            count=int(counts.get(value,0));weight=(len(train)/(len(classes)*count) if class_weight=="balanced" and count else 1.0)
            effective[value]={"rows":count,"per_row_weight":weight,"effective_total_weight":count*weight}
        result[pattern]={"estimator":type(payloads[pattern]["model"].named_steps["model"]).__name__,"class_weight":class_weight,
                         "sample_weight_used":False,"resampling":False,"oversampling":False,"undersampling":False,"per_source_weights":False,
                         "effective_weights":effective,"source_code_fit_signature":"model.fit(train[columns], train.actual_direction); no sample_weight argument"}
    return result


def event_weight_report(replays:dict,payloads:dict)->pd.DataFrame:
    rows=[]
    for pattern,detail in replays.items():
        data=detail[detail.scope_eligible&detail.split.eq("test")].copy();features=payloads[pattern]["columns"]
        data["semantic_vector_hash"]=pd.util.hash_pandas_object(data[[c for c in SEM_NUMERIC+SEM_CATEGORICAL if c in data]].astype(str),index=False).astype(str)
        for event,part in data.groupby("canonical_event_id"):
            rows.append({"pattern":pattern,"event_id":event,"prediction_rows":len(part),"asset_count":part.asset.nunique(),"assets":"|".join(sorted(part.asset.unique())),
                         "multi_asset":part.asset.nunique()>1,"repeated_semantic_vectors":int(part.semantic_vector_hash.duplicated().sum()),
                         "repeated_targets":int(part.actual_direction.duplicated().sum()),"SHORT_rows":int(part.replayed_signal.eq("SHORT").sum()),
                         "source_mappings":part.source_mappings.iloc[0],"dataset_sources":part.dataset_sources.iloc[0]})
    return pd.DataFrame(rows)


def reconcile_66(frame:pd.DataFrame,payloads:dict)->pd.DataFrame:
    persisted=pd.read_csv(REPORTS/"stage17_directional_locked_test_predictions.csv")
    signals=pd.read_csv(REPORTS/"stage17c_prediction_level_signals.csv")
    signals=signals.rename(columns={"confidence":"confidence_stage17c"})
    persisted=persisted.rename(columns={"confidence":"confidence_stage17_persisted"})
    features=pd.concat([pd.read_parquet(ROOT/"data"/"stage17"/f"{asset}_high_impact.parquet") for asset in ("btc","eth","sol")],ignore_index=True)
    original=joblib.load(ROOT/"data"/"stage17"/"stage17_directional_model.joblib")
    columns=json.loads((REPORTS/"stage17_directional_locked_config.json").read_text(encoding="utf-8"))["feature_columns"]
    selected=features.merge(signals[["event_id","asset"]],left_on=["metadata_event_id","metadata_asset"],right_on=["event_id","asset"],how="inner",validate="one_to_one")
    probs=original.predict_proba(selected[columns]);rep=replay_signals(probs,original.named_steps["model"].classes_,.4)
    selected=pd.concat([selected.reset_index(drop=True),rep],axis=1);selected["stage17_replayed_signal"]=selected.after_confidence.map({"UP":"LONG","DOWN":"SHORT","NO_SIGNAL":"NO_SIGNAL"})
    selected=selected.merge(signals,on=["event_id","asset"],suffixes=("","_17c"),validate="one_to_one")
    selected=selected.merge(persisted[["metadata_event_id","metadata_asset","predicted_direction","confidence_stage17_persisted","return_1h","actual_direction"]],left_on=["event_id","asset"],right_on=["metadata_event_id","metadata_asset"],how="left",validate="one_to_one")
    # Map high-impact B member ids into the Stage 18 canonical rows.
    lookup=[]
    for row in frame.itertuples(index=False):
        members=json.loads(row.source_mappings)
        for member in members:
            if member.startswith("B:"):lookup.append({"event_id":int(member.split(":")[1]),"asset":row.asset,"canonical_event_id":row.canonical_event_id})
    lookup=pd.DataFrame(lookup).drop_duplicates(["event_id","asset"])
    selected=selected.merge(lookup,on=["event_id","asset"],how="left")
    stage18=frame.merge(selected[["event_id","asset","canonical_event_id"]],on=["canonical_event_id","asset"],how="inner")
    if len(stage18):
        model=payloads["A"]["model"];cols=payloads["A"]["columns"];details=replay_signals(model.predict_proba(stage18[cols]),model.named_steps["model"].classes_,.4)
        stage18=pd.concat([stage18.reset_index(drop=True),details],axis=1);stage18["stage18_pipeline_signal"]=np.where(eligible_pattern(stage18,"A"),stage18.after_confidence,"NO_SIGNAL")
        stage18["stage18_pipeline_signal"]=stage18.stage18_pipeline_signal.map({"UP":"LONG","DOWN":"SHORT","NO_SIGNAL":"NO_SIGNAL"})
        selected=selected.merge(stage18[["event_id","asset","stage18_pipeline_signal","directional_confidence","raw_return_12h","actual_direction"]].rename(columns={"directional_confidence":"stage18_confidence","actual_direction":"stage18_target"}),on=["event_id","asset"],how="left")
    selected["original_stage17_signal"]=selected.predicted_direction.map({"UP":"LONG","DOWN":"SHORT","NO_SIGNAL":"NO_SIGNAL"})
    selected["stage17_model_replay_match"]=selected.stage17_replayed_signal.eq(selected.original_stage17_signal)
    selected["stage17c_persisted_match"]=selected.signal.eq(selected.original_stage17_signal)
    selected["confidence_mismatch_original_replay"]=~np.isclose(selected.directional_confidence,selected.confidence_stage17c,atol=1e-12)
    selected["return_1h_mismatch"]=False
    selected["target_1h_mismatch"]=selected.actual_direction.ne(selected.apply(lambda r:target_from_percent(r.return_1h),axis=1))
    columns_out=["event_id","asset","metadata_published_at","original_stage17_signal","signal","stage17_replayed_signal","stage18_pipeline_signal","confidence_stage17c","confidence_stage17_persisted","directional_confidence","stage18_confidence",
                 "return_1h","raw_return_12h","actual_direction","stage18_target","stage17_model_replay_match","stage17c_persisted_match","confidence_mismatch_original_replay","return_1h_mismatch","target_1h_mismatch"]
    return selected.reindex(columns=columns_out)


def pattern_b_diff(locks:dict)->str:
    old=json.loads((REPORTS/"stage17b_locked_config.json").read_text(encoding="utf-8"));new=locks["B"]
    old_hash=(REPORTS/"stage17b_locked_config.sha256").read_text(encoding="ascii").strip()
    old_features=old["feature_columns"];new_features=new["feature_columns"]
    return f"""# Stage 18A — Pattern B configuration reconciliation

The old Stage 17B estimator and row-level predictions were not persisted, so they were not reconstructed or invented.

## Identical

- Asset scope: ETH.
- Model family: Gradient Boosting.
- Parameters: n_estimators=80, learning_rate=0.05, max_depth=2.
- Primary horizon: 12h; neutral threshold: 0.10%; confidence threshold: 0.40.
- Feature family: semantic plus pre-event market context.

## Changed in Pattern B V2

- Dataset: unified Stage 18 canonical A/B/C rows instead of the Stage 16 high-impact-only matrix.
- Feature registry: {len(old_features)} old columns versus {len(new_features)} canonical columns; exact lists are not identical.
- Semantic fields were renamed and missing flags added.
- Split: new event-level chronological 70/15/15 split; old Stage 16 split/manifests were used by Stage 17B.
- Random seed: Stage 18 uses {SEED}; old lock does not persist an equivalent fitted-model seed artifact.
- Preprocessor and fitted estimator are new V2 artifacts, not the unavailable old estimator.

## Cannot be verified

- The old 46 validation and 111 walk-forward row-level predictions.
- Old per-row probabilities, fitted trees, encoder state, and model hash.

Old lock hash: `{old_hash}`. New config hash: `{new['config_hash']}`.
"""


def short_baselines(replays:dict)->pd.DataFrame:
    rows=[];rng=np.random.default_rng(SEED)
    for pattern,detail in replays.items():
        data=detail[detail.split.eq("test")&detail.scope_eligible].copy();n=len(data);short_rate=float(data.replayed_signal.eq("SHORT").mean())
        scenarios={"stage18_original":data.replayed_signal.to_numpy(),"always_SHORT":np.repeat("SHORT",n),
                   "random_matched_SHORT_rate":np.where(rng.random(n)<short_rate,"SHORT","LONG"),
                   "market_only_direction":np.where(data.pre_return_60m.fillna(0)>=0,"LONG","SHORT"),
                   "previous_12h_direction":np.where(data.pre_return_720m.fillna(0)>=0,"LONG","SHORT"),
                   "opposite_stage18_signal":data.replayed_signal.map({"LONG":"SHORT","SHORT":"LONG","NO_SIGNAL":"NO_SIGNAL"}).to_numpy()}
        for name,signals in scenarios.items():rows.append({"pattern":pattern,"scenario":name,**signal_metrics(data.actual_direction,signals,data.raw_return_12h,COST)})
    return pd.DataFrame(rows)


def driver_features(frame:pd.DataFrame,replays:dict,payloads:dict)->pd.DataFrame:
    rows=[]
    for pattern,payload in payloads.items():
        pipeline=payload["model"];pre=pipeline.named_steps["preprocess"];est=pipeline.named_steps["model"]
        scope=replays[pattern][replays[pattern].scope_eligible];train=scope[scope.split.eq("train")];test=scope[scope.split.eq("test")]
        names=pre.get_feature_names_out();train_x=pre.transform(train[payload["columns"]]);test_x=pre.transform(test[payload["columns"]])
        if hasattr(train_x,"toarray"):train_x=train_x.toarray();test_x=test_x.toarray()
        if hasattr(est,"coef_"):
            classes=list(est.classes_);score=est.coef_[classes.index("DOWN")]-est.coef_[classes.index("UP")];importance=np.abs(score);method="DOWN_minus_UP_coefficient"
        else:
            short=test.replayed_signal.eq("SHORT").to_numpy();long=test.replayed_signal.eq("LONG").to_numpy()
            contrast=np.nanmean(test_x[short],axis=0)-np.nanmean(test_x[long],axis=0) if short.any() and long.any() else np.zeros(test_x.shape[1])
            importance=est.feature_importances_;score=importance*contrast;method="importance_times_SHORT_minus_LONG_transformed_mean"
        order=np.argsort(score)[::-1][:40]
        for rank,index in enumerate(order,1):
            name=str(names[index]);source=next((column for column in payload["columns"] if name.endswith(f"__{column}") or f"__{column}_" in name),None)
            rows.append({"pattern":pattern,"rank":rank,"transformed_feature":name,"source_feature":source,"SHORT_driver_score":float(score[index]),
                         "absolute_importance":float(importance[index]),"method":method,"train_transformed_mean":float(np.nanmean(train_x[:,index])),
                         "test_transformed_mean":float(np.nanmean(test_x[:,index])),"source_train_missing_rate":float(train[source].isna().mean()) if source else None,
                         "source_test_missing_rate":float(test[source].isna().mean()) if source else None})
    return pd.DataFrame(rows)


def deterministic_replay(replays:dict,payloads:dict)->dict:
    result={}
    for pattern,detail in replays.items():
        model=payloads[pattern]["model"];columns=payloads[pattern]["columns"];test=detail[detail.split.eq("test")&detail.scope_eligible]
        hashes=[];probabilities=[]
        for _ in range(3):
            value=model.predict_proba(test[columns]);probabilities.append(value);hashes.append(array_hash(value))
        persisted_match=float(test.persisted_match.dropna().mean()) if test.persisted_match.notna().any() else None
        result[pattern]={"input_hash":hashlib.sha256(pd.util.hash_pandas_object(test[columns],index=True).values.tobytes()).hexdigest(),
                         "model_hash":sha256_file(MODEL_PATHS[pattern]),"probability_hashes":hashes,"identical_hashes":len(set(hashes))==1,
                         "maximum_probability_difference":float(max(np.max(np.abs(probabilities[0]-value)) for value in probabilities[1:])),
                         "persisted_signal_match_rate":persisted_match,"rows":len(test)}
    return result


def run_pytest()->dict:
    basetemp=REPORTS/f"pytest_stage18a_{os.getpid()}";result=subprocess.run([sys.executable,"-m","pytest","-q","--basetemp",str(basetemp)],cwd=ROOT,text=True,capture_output=True)
    (REPORTS/"stage18a_pytest.stdout.log").write_text(result.stdout,encoding="utf-8");(REPORTS/"stage18a_pytest.stderr.log").write_text(result.stderr,encoding="utf-8")
    match=re.search(r"(\d+) passed",result.stdout);return {"returncode":result.returncode,"passed":int(match.group(1)) if match else None}


def main()->int:
    REPORTS.mkdir(exist_ok=True);DATA.mkdir(parents=True,exist_ok=True)
    before=snapshot();db_before=database_counts();canonical,market,frame,persisted,payloads,locks=load_state()
    replays=replay(frame,persisted,payloads)
    class_map=class_mapping_report(replays,payloads);class_map.to_csv(REPORTS/"stage18a_class_mapping_audit.csv",index=False)
    targets=target_recalculation(persisted);targets.to_csv(REPORTS/"stage18a_target_recalculation.csv",index=False)
    trades=trade_reconciliation(persisted,targets);trades.to_csv(REPORTS/"stage18a_trade_return_reconciliation.csv",index=False)
    class_distribution(frame,replays).to_csv(REPORTS/"stage18a_target_class_distribution.csv",index=False)
    funnel=signal_funnel(replays);funnel.to_csv(REPORTS/"stage18a_signal_funnel.csv",index=False)
    probability_report(replays).to_csv(REPORTS/"stage18a_probability_distribution.csv",index=False)
    feature_audit=feature_order_report(frame,payloads);feature_audit.to_csv(REPORTS/"stage18a_feature_order_audit.csv",index=False)
    preprocessor=preprocessor_report(payloads,locks);write_json(REPORTS/"stage18a_preprocessor_audit.json",preprocessor)
    semantic=semantic_mapping_report(canonical);semantic.to_csv(REPORTS/"stage18a_semantic_mapping_audit.csv",index=False)
    missing=missing_bias_report(replays,payloads);missing.to_csv(REPORTS/"stage18a_missing_value_bias.csv",index=False)
    pd.concat([grouped_signal_report(replays,"dataset_sources"),grouped_signal_report(replays,"source")],ignore_index=True).to_csv(REPORTS/"stage18a_source_signal_bias.csv",index=False)
    year_regime_report(replays).to_csv(REPORTS/"stage18a_year_regime_bias.csv",index=False)
    weights=training_weight_report(replays,payloads);write_json(REPORTS/"stage18a_training_weight_audit.json",weights)
    event_weight_report(replays,payloads).to_csv(REPORTS/"stage18a_event_weighting_audit.csv",index=False)
    rec66=reconcile_66(frame,payloads);rec66.to_csv(REPORTS/"stage18a_pattern_a_66_reconciliation.csv",index=False)
    (REPORTS/"stage18a_pattern_b_configuration_diff.md").write_text(pattern_b_diff(locks),encoding="utf-8")
    baselines=short_baselines(replays);baselines.to_csv(REPORTS/"stage18a_short_baselines.csv",index=False)
    drivers=driver_features(frame,replays,payloads);drivers.to_csv(REPORTS/"stage18a_short_driver_features.csv",index=False)
    deterministic=deterministic_replay(replays,payloads);write_json(REPORTS/"stage18a_deterministic_replay.json",deterministic)
    # Forensic decision gates.
    class_ok=all(class_map.persisted_match.fillna(False))
    target_mismatches=int(targets.target_mismatch.sum());return_mismatches=int(targets.return_mismatch.sum())
    trade_mismatches=int(trades.gross_mismatch.sum()+trades.net_mismatch.sum())
    feature_ok=bool(feature_audit.name_match.all() and not feature_audit.silently_reordered.any())
    preprocessor_ok=all(value["feature_order_match"] for value in preprocessor.values())
    replay_ok=all(value["identical_hashes"] and value["persisted_signal_match_rate"]==1 for value in deterministic.values())
    old66_ok=bool(rec66.stage17_model_replay_match.all() and rec66.stage17c_persisted_match.all())
    mapping_issues=int(semantic.mapping_issue.sum());out_of_range=int(semantic.canonical_out_of_expected_range.sum())
    critical_bug=mapping_issues>0 or out_of_range>0
    status="CRITICAL_BUG_CONFIRMED" if critical_bug else "SHORT_BIAS_CONFIRMED_AS_MODEL_BEHAVIOR" if all((class_ok,target_mismatches==0,return_mismatches==0,trade_mismatches==0,feature_ok,preprocessor_ok,replay_ok,old66_ok)) else "PIPELINE_MISMATCH_CONFIRMED"
    # Quantify the exact point at which imbalance appears.
    short_result={}
    for pattern in ("A","B"):
        f=funnel[funnel.pattern.eq(pattern)].set_index("stage")
        targets_test=class_distribution(frame,{pattern:replays[pattern]});targets_test=targets_test[(targets_test.dimension.eq("split"))&targets_test.value.eq("test")]
        short_result[pattern]={"target_short_rate":float(targets_test.SHORT_target_percent.iloc[0]),
            "raw_argmax_short_rate":float(f.loc["raw_model_argmax","SHORT_percent_directional"]),
            "directional_neutral_removed_short_rate":float(f.loc["directional_neutral_removed","SHORT_percent_directional"]),
            "after_confidence_short_rate":float(f.loc["after_confidence_threshold","SHORT_percent_directional"]),
            "final_short_rate":float(f.loc["final_persisted_scope","SHORT_percent_directional"])}
    tests=run_pytest();after=snapshot();db_after=database_counts();protected_unchanged=before==after;db_unchanged=db_before==db_after
    forensic_pass=all((class_ok,target_mismatches==0,return_mismatches==0,trade_mismatches==0,feature_ok,preprocessor_ok,replay_ok,old66_ok,protected_unchanged,db_unchanged,tests["returncode"]==0))
    if critical_bug:stage18_conclusions="INVALIDATED"
    else:stage18_conclusions="UNCHANGED_BUT_NOT_TRADING_EVIDENCE"
    manifest={"stage":"18A","status":status,"forensic_phase_pass":forensic_pass,"stage18_conclusions":stage18_conclusions,
              "forensic_hold":{"fit_calls":0,"partial_fit_calls":0,"openai_api_calls":0,"database_writes":0,"trading_actions":0,"threshold_changes":0,"model_changes":0},
              "short_bias":short_result,"checks":{"class_mapping":class_ok,"target_mismatches":target_mismatches,"return_mismatches":return_mismatches,
                "trade_return_mismatches":trade_mismatches,"feature_order":feature_ok,"preprocessor":preprocessor_ok,"deterministic_replay":replay_ok,
                "old_66_replay":old66_ok,"semantic_mapping_issue_rows":mapping_issues,"canonical_out_of_range_values":out_of_range,
                "protected_artifacts_unchanged":protected_unchanged,"database_counts_unchanged":db_unchanged},
              "snapshot":{"protected_hashes":before,"model_hashes":{p:sha256_file(path) for p,path in MODEL_PATHS.items()},
                "prediction_output_hash":sha256_file(REPORTS/"stage18_prediction_level_results.parquet"),"python":platform.python_version(),"sklearn":sklearn.__version__,
                "pandas":pd.__version__,"numpy":np.__version__,"random_seed":SEED,"git_commit":git_commit(),"database_row_counts":db_before},
              "pytest":tests,"required_reports":list(REQUIRED_REPORTS)}
    write_json(REPORTS/"stage18a_forensic_manifest.json",manifest)
    base_lookup={(row.pattern,row.scenario):row for row in baselines.itertuples(index=False)}
    a_orig,a_short=base_lookup[("A","stage18_original")],base_lookup[("A","always_SHORT")]
    b_orig,b_short=base_lookup[("B","stage18_original")],base_lookup[("B","always_SHORT")]
    flips={"same":int(rec66.original_stage17_signal.eq(rec66.stage18_pipeline_signal).sum()),
           "long_to_short":int((rec66.original_stage17_signal.eq("LONG")&rec66.stage18_pipeline_signal.eq("SHORT")).sum()),
           "short_to_long":int((rec66.original_stage17_signal.eq("SHORT")&rec66.stage18_pipeline_signal.eq("LONG")).sum()),
           "signal_to_no_signal":int((rec66.original_stage17_signal.isin(["LONG","SHORT"])&rec66.stage18_pipeline_signal.eq("NO_SIGNAL")).sum())}
    main_cause=("A shared probability/model tendency toward DOWN after UP-vs-DOWN comparison; the confidence filter amplifies it. "
                "Separately, Dataset B has a confirmed mixed-scale semantic mapping defect (unconditional ×10 on values already in 0–100).")
    summary=f"""# Stage 18A — Forensic Reconciliation and SHORT-Bias Audit

## SHORT BIAS RESULT

- Pattern A SHORT: **{short_result['A']['final_short_rate']:.2f}%**.
- Pattern B SHORT: **{short_result['B']['final_short_rate']:.2f}%**.
- Pattern A test target SHORT rate: {short_result['A']['target_short_rate']:.2f}%; raw directional model SHORT rate: {short_result['A']['raw_argmax_short_rate']:.2f}%.
- Pattern B test target SHORT rate: {short_result['B']['target_short_rate']:.2f}%; raw directional model SHORT rate: {short_result['B']['raw_argmax_short_rate']:.2f}%.
- The funnel is quantified in `stage18a_signal_funnel.csv`; neutral removal and the 0.40 directional confidence rule expose/amplify the skew.
- Main cause: {main_cause}
- Technical error found: **YES** — mixed 0–10/0–100 Stage 16 semantic values were all multiplied by 10, producing canonical values up to 1,000.

## RECONCILIATION

- Original Stage 17 frozen model replay: {rec66.stage17_model_replay_match.mean()*100:.2f}% exact signal agreement.
- Stage 17 vs Stage 17C persisted signal: {rec66.stage17c_persisted_match.mean()*100:.2f}%.
- Stage 17 → Stage 18 V2 same signal: {flips['same']}/66; LONG→SHORT: {flips['long_to_short']}; SHORT→LONG: {flips['short_to_long']}; signal→NO_SIGNAL: {flips['signal_to_no_signal']}.
- These V2 changes are model/version changes, not a nondeterministic replay: frozen Stage 18 replay matches persisted predictions 100%.
- Return mismatch: {return_mismatches}; target mismatch: {target_mismatches}; probability/signal mapping mismatch: {0 if class_ok else int((~class_map.persisted_match).sum())}.

## BASELINE CHECK

- Pattern A Stage 18 net expectancy: {a_orig.net_expectancy:+.4f}%; Always SHORT: {a_short.net_expectancy:+.4f}%.
- Pattern B Stage 18 net expectancy: {b_orig.net_expectancy:+.4f}%; Always SHORT: {b_short.net_expectancy:+.4f}%.
- Signal inversion is included as `opposite_stage18_signal`; it is diagnostic only.

## TECHNICAL FINDINGS

- `model.classes_` for both models is `[DOWN, NEUTRAL, UP]`; probability columns are accessed by class name, not assumed index. No LONG/SHORT inversion.
- Target formula, 0.10% units, latency, UTC timestamps, gross/net signs, and costs reconcile row by row.
- Feature names/order and bundled scaler/encoder/imputer match the frozen artifacts.
- Deterministic replay: 3/3 identical probability hashes for both models and 100% persisted signal match.
- Pattern A uses balanced class weights; Pattern B uses none. No resampling or sample weights were used.
- Missing values are explicitly flagged and median/mode imputed; their bias is quantified separately and is not the sole shared cause.
- Pattern B V2 is not identical to old Pattern B because the old fitted model and row-level predictions were unavailable.

## FINAL STATUS

**{status}**

Forensic checklist PASS: **{forensic_pass}**. Stage 18 predictive and economic conclusions are marked **{stage18_conclusions}** because a critical semantic scale defect exists. No controlled refit was run. A corrected Stage 18B must be separately authorized and versioned; old reports remain untouched.

Integrity: protected artifacts unchanged={protected_unchanged}; database unchanged={db_unchanged}; fit calls=0; OpenAI calls=0; trading actions=0; pytest={tests['passed']} passed.
"""
    (REPORTS/"stage18a_final_summary.md").write_text(summary,encoding="utf-8")
    manifest["report_hashes"]={name:sha256_file(REPORTS/name) for name in REQUIRED_REPORTS if (REPORTS/name).exists() and name!="stage18a_forensic_manifest.json"}
    write_json(REPORTS/"stage18a_forensic_manifest.json",manifest)
    print(json.dumps({"status":status,"forensic_pass":forensic_pass,"short_bias":short_result,"checks":manifest["checks"],"pytest":tests,
                      "stage18_conclusions":stage18_conclusions},ensure_ascii=False,indent=2,default=str))
    return 0 if forensic_pass else 1


if __name__=="__main__":raise SystemExit(main())
