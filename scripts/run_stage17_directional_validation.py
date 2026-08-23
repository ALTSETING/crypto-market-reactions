"""Select, lock, and evaluate one Stage 17 directional classifier exactly once."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import text

from analysis.stage17_directional import canonical_hash, directional_metrics, directional_target, predictions_from_probabilities
from analysis.stage17_subgroups import PRIMARY_HORIZONS, subgroup_masks
from database.db import engine
from scripts.run_stage17_semantic_subgroups import ROOT, DATA, REPORTS, file_hash, protected_files, pytest_run, snapshot, write_json

LATENCY=1
NEUTRAL_THRESHOLDS=(.10,.25,.50)
CONFIDENCE_THRESHOLDS=(.35,.40,.45,.50,.55,.60)
MODEL_VERSION="stage17_directional_logistic_v1"
LOCK=REPORTS/"stage17_directional_locked_config.json"
LOCK_SHA=REPORTS/"stage17_directional_locked_config.sha256"
MODEL_FILE=DATA/"stage17_directional_model.joblib"
SELECTION=REPORTS/"stage17_directional_model_selection.csv"
VALIDATION=REPORTS/"stage17_directional_validation.json"
WALKFORWARD=REPORTS/"stage17_directional_walkforward.csv"
PREDICTIONS=REPORTS/"stage17_directional_locked_test_predictions.csv"
METRICS=REPORTS/"stage17_directional_locked_test_metrics.json"
BASELINES=REPORTS/"stage17_directional_baselines.csv"
PERIODS=REPORTS/"stage17_directional_period_metrics.csv"


def load_features()->tuple[pd.DataFrame,dict[str,Any]]:
    manifest=json.loads((DATA/"manifest.json").read_text(encoding="utf-8"))
    columns=manifest["feature_columns"]
    frames=[]
    for asset in ("btc","eth","sol"):
        frames.append(pd.read_parquet(DATA/f"{asset}_high_impact.parquet",columns=columns))
    frame=pd.concat(frames,ignore_index=True).sort_values(["metadata_published_at","metadata_event_id","metadata_asset"]).reset_index(drop=True)
    if frame.duplicated(["metadata_event_id","metadata_asset"]).any():raise RuntimeError("duplicate event-asset feature key")
    if frame.groupby("metadata_event_id").metadata_split.nunique().max()!=1:raise RuntimeError("event split contamination")
    forbidden=[column for column in frame if column.startswith(("target_","return_","abnormal_return_","future_"))]
    if forbidden:raise RuntimeError(f"test leakage columns loaded: {forbidden}")
    return frame,manifest


def load_targets(event_ids:list[int],split_name:str)->pd.DataFrame:
    if not event_ids:return pd.DataFrame()
    sql=text("""SELECT event_id,replace(symbol,'USDT','') asset,return_20m,return_40m,return_1h,return_3h,return_5h,return_8h,return_12h
                FROM high_impact_market_reactions WHERE latency_minutes=:latency AND event_id=ANY(:event_ids) ORDER BY event_id,symbol""")
    with engine.connect() as connection:
        result=pd.read_sql(sql,connection,params={"latency":LATENCY,"event_ids":event_ids})
    result["target_query_split"]=split_name
    if result.duplicated(["event_id","asset"]).any():raise RuntimeError("duplicate target query identity")
    return result


def feature_sets(frame:pd.DataFrame)->dict[str,list[str]]:
    semantic_numeric=[c for c in frame if c.startswith("ai_") and pd.api.types.is_numeric_dtype(frame[c]) and c not in {"ai_surprise_level","ai_regulatory_strength"}]
    market_numeric=[c for c in frame if c.startswith("pre_") and pd.api.types.is_numeric_dtype(frame[c])]
    categorical=[c for c in ("metadata_asset","metadata_source","metadata_source_type","metadata_platform","source_event_type",
        "source_information_status","ai_surprise_evidence","ai_first_disclosure","ai_market_scope","ai_temporary_vs_structural",
        "ai_evidence_quality","ai_content_valence","ai_directness","pre_trend_regime","context_btc_state","context_asset_state",
        "context_volatility","context_relative_strength") if c in frame]
    semantic_categorical=[c for c in categorical if not c.startswith(("pre_","context_"))]
    return {"semantic_only":list(dict.fromkeys(semantic_numeric+semantic_categorical)),
            "market_only":list(dict.fromkeys(market_numeric+["metadata_asset"]+[c for c in categorical if c.startswith(("pre_","context_"))])),
            "semantic_market":list(dict.fromkeys(semantic_numeric+market_numeric+categorical))}


def pipeline_for(frame:pd.DataFrame,columns:list[str])->Pipeline:
    numeric=[c for c in columns if pd.api.types.is_numeric_dtype(frame[c])];categorical=[c for c in columns if c not in numeric]
    preprocess=ColumnTransformer([
        ("numeric",Pipeline([("impute",SimpleImputer(strategy="median")),("scale",StandardScaler())]),numeric),
        ("categorical",Pipeline([("impute",SimpleImputer(strategy="most_frequent")),("encode",OneHotEncoder(handle_unknown="ignore"))]),categorical),
    ])
    return Pipeline([("preprocess",preprocess),("model",LogisticRegression(C=1.0,class_weight="balanced",max_iter=3000,solver="lbfgs"))])


def baseline_accuracy(rows:pd.DataFrame,prediction:pd.Series|np.ndarray)->float|None:
    if len(rows)==0:return None
    return float((np.asarray(prediction)==rows.actual_direction.to_numpy()).mean())


def baseline_metrics(rows:pd.DataFrame)->dict[str,float|None]:
    if rows.empty:return {}
    up=np.repeat("UP",len(rows));down=np.repeat("DOWN",len(rows))
    actual=rows.actual_direction
    majority="UP" if int(actual.eq("UP").sum())>=int(actual.eq("DOWN").sum()) else "DOWN"
    previous_1m=np.where(pd.to_numeric(rows.pre_return_1m,errors="coerce")>=0,"UP","DOWN")
    previous_5m=np.where(pd.to_numeric(rows.pre_return_5m,errors="coerce")>=0,"UP","DOWN")
    btc=np.where(pd.to_numeric(rows.pre_btc_return_60m,errors="coerce")>=0,"UP","DOWN")
    predicted_up_share=float(rows.predicted_direction.eq("UP").mean());actual_up=float(actual.eq("UP").mean());actual_down=float(actual.eq("DOWN").mean())
    return {"always_up":baseline_accuracy(rows,up),"always_down":baseline_accuracy(rows,down),
        "majority_class":baseline_accuracy(rows,np.repeat(majority,len(rows))),"previous_1m_direction":baseline_accuracy(rows,previous_1m),
        "previous_5m_direction":baseline_accuracy(rows,previous_5m),"btc_trend_direction":baseline_accuracy(rows,btc),
        "random_same_prediction_ratio_expected":predicted_up_share*actual_up+(1-predicted_up_share)*actual_down}


def prediction_rows(data:pd.DataFrame,model:Pipeline,columns:list[str],horizon:str,neutral:float,confidence_threshold:float,subgroup:str)->pd.DataFrame:
    probabilities=model.predict_proba(data[columns]);classes=list(model.named_steps["model"].classes_)
    predicted,confidence=predictions_from_probabilities(probabilities,classes,confidence_threshold)
    masks={"ALL":pd.Series(True,index=data.index),**subgroup_masks(data)}
    predicted=np.where(masks[subgroup].to_numpy(),predicted,"NO_SIGNAL")
    result=data.copy();result["actual_direction"]=directional_target(result[f"return_{horizon}"],neutral)
    result["predicted_direction"]=predicted;result["confidence"]=confidence
    return result


def choose_configuration(features:pd.DataFrame,targets:pd.DataFrame)->tuple[dict[str,Any],pd.DataFrame,Pipeline,pd.DataFrame]:
    data=features.merge(targets,left_on=["metadata_event_id","metadata_asset"],right_on=["event_id","asset"],how="inner",validate="one_to_one")
    train=data.metadata_split.eq("train");validation=data.metadata_split.eq("validation")
    sets=feature_sets(data);rows=[];models={}
    validation_masks={"ALL":pd.Series(True,index=data.index),**subgroup_masks(data)}
    eligible_subgroups=[name for name,mask in validation_masks.items() if int((mask&validation).sum())>=50]
    for set_name,columns in sets.items():
      for horizon in PRIMARY_HORIZONS:
       for neutral in NEUTRAL_THRESHOLDS:
        y=directional_target(data[f"return_{horizon}"],neutral)
        model=pipeline_for(data,columns);model.fit(data.loc[train,columns],y.loc[train]);models[(set_name,horizon,neutral)]=model
        probabilities=model.predict_proba(data.loc[validation,columns]);classes=list(model.named_steps["model"].classes_)
        val_data=data.loc[validation].copy()
        for confidence_threshold in CONFIDENCE_THRESHOLDS:
          predicted,confidence=predictions_from_probabilities(probabilities,classes,confidence_threshold)
          for subgroup in eligible_subgroups:
            subgroup_mask=validation_masks[subgroup].loc[val_data.index].to_numpy();candidate=val_data.copy()
            candidate["actual_direction"]=y.loc[validation].to_numpy();candidate["predicted_direction"]=np.where(subgroup_mask,predicted,"NO_SIGNAL");candidate["confidence"]=confidence
            metrics=directional_metrics(candidate);signals=candidate[candidate.predicted_direction.isin(["UP","DOWN"])]
            baselines=baseline_metrics(signals);simple=max((baselines.get(k) or 0) for k in ("previous_1m_direction","previous_5m_direction","btc_trend_direction")) if baselines else None
            eligible=metrics["predictions"]>=50 and metrics["coverage"]>=.35 and metrics["up_predictions"]>0 and metrics["down_predictions"]>0 and metrics["max_prediction_class_share"]<=.80
            rows.append({"feature_set":set_name,"horizon":horizon,"neutral_threshold":neutral,"confidence_threshold":confidence_threshold,
                "subgroup":subgroup,**metrics,**{f"baseline_{k}":v for k,v in baselines.items()},"simple_market_baseline":simple,
                "excess_over_simple":metrics["accuracy"]-simple if metrics["accuracy"] is not None and simple is not None else None,
                "validation_eligible":eligible,"test_outcomes_used":False})
    selection=pd.DataFrame(rows);eligible=selection[selection.validation_eligible].copy()
    if eligible.empty:raise RuntimeError("No validation configuration met minimum prediction/coverage/class-balance gates")
    eligible["selection_score"]=eligible.excess_over_simple.fillna(-1)+eligible.accuracy.fillna(0)*.1+eligible.wilson_95_ci_low.fillna(0)*.01
    chosen=eligible.sort_values(["selection_score","predictions"],ascending=False).iloc[0].to_dict()
    columns=sets[chosen["feature_set"]];model=models[(chosen["feature_set"],chosen["horizon"],chosen["neutral_threshold"])]
    return chosen,selection,model,data


def walkforward(data:pd.DataFrame,chosen:dict[str,Any],columns:list[str])->pd.DataFrame:
    prelock=data[data.metadata_split.isin(["train","validation"])].sort_values(["metadata_published_at","metadata_event_id"])
    event_ids=prelock.metadata_event_id.drop_duplicates().to_numpy();cuts=[(.4,.6),(.6,.8),(.8,1.0)];rows=[]
    for fold,(train_end,test_end) in enumerate(cuts,1):
        train_ids=set(event_ids[:int(len(event_ids)*train_end)]);eval_ids=set(event_ids[int(len(event_ids)*train_end):int(len(event_ids)*test_end)])
        train=prelock[prelock.metadata_event_id.isin(train_ids)];evaluate=prelock[prelock.metadata_event_id.isin(eval_ids)]
        y=directional_target(train[f"return_{chosen['horizon']}"],chosen["neutral_threshold"])
        model=pipeline_for(train,columns);model.fit(train[columns],y)
        result=prediction_rows(evaluate,model,columns,chosen["horizon"],chosen["neutral_threshold"],chosen["confidence_threshold"],chosen["subgroup"])
        metrics=directional_metrics(result);signals=result[result.predicted_direction.isin(["UP","DOWN"])]
        baselines=baseline_metrics(signals);simple=max((baselines.get(k) or 0) for k in ("previous_1m_direction","previous_5m_direction","btc_trend_direction")) if baselines else None
        rows.append({"fold":fold,"train_unique_events":len(train_ids),"evaluation_unique_events":len(eval_ids),**metrics,
            "simple_market_baseline":simple,"excess_over_simple":metrics["accuracy"]-simple if metrics["accuracy"] is not None and simple is not None else None})
    return pd.DataFrame(rows)


def period_metrics(rows:pd.DataFrame)->pd.DataFrame:
    output=[];work=rows.copy();work["month"]=pd.to_datetime(work.metadata_published_at,utc=True).dt.to_period("M").astype(str);work["quarter"]=pd.to_datetime(work.metadata_published_at,utc=True).dt.to_period("Q").astype(str)
    for dimension in ("month","quarter","metadata_source","metadata_asset","actual_direction","isolated_event"):
        for value,part in work.groupby(dimension,dropna=False):output.append({"dimension":dimension,"value":value,**directional_metrics(part)})
    return pd.DataFrame(output)


def economic_metrics(signals:pd.DataFrame,horizon:str)->dict[str,Any]:
    if signals.empty:return {}
    sign=np.where(signals.predicted_direction.eq("UP"),1,-1);gross=sign*pd.to_numeric(signals[f"return_{horizon}"],errors="coerce").to_numpy();net=gross-.20
    equity=np.nancumsum(net);peaks=np.maximum.accumulate(np.r_[0,equity])[1:];drawdown=equity-peaks
    profit=np.nansum(net[net>0]);loss=-np.nansum(net[net<0])
    return {"average_gross_return_percent":float(np.nanmean(gross)),"average_net_return_base_cost_percent":float(np.nanmean(net)),
        "net_win_rate":float(np.nanmean(net>0)),"profit_factor":float(profit/loss) if loss>0 else None,
        "cumulative_net_return_percent":float(np.nansum(net)),"maximum_drawdown_percent":float(np.nanmin(drawdown)) if len(drawdown) else None,"base_round_trip_cost_percent":.20}


def synchronize_primary_reports(result:dict[str,Any])->None:
    """Update central Stage 17 aliases from persisted results without rescoring test."""
    flat={key:value for key,value in result.items() if not isinstance(value,(dict,list))}
    flat["test_type"]="directional_prediction";flat["test_used_for_tuning"]=False
    pd.DataFrame([flat]).to_csv(REPORTS/"stage17_test_metrics.csv",index=False)
    if WALKFORWARD.exists():pd.read_csv(WALKFORWARD).to_csv(REPORTS/"stage17_walkforward_metrics.csv",index=False)
    write_json(REPORTS/"stage17_locked_test_assessment.json",{
        "status":result["final_status"],"test_type":"directional_prediction","test_used":True,"test_used_once":True,
        "test_used_for_tuning":False,"rules_changed_after_test":False,"lock_sha256":result["lock_sha256"],
        "predictions":result["predictions"],"coverage":result["coverage"],"accuracy":result["accuracy"],
        "wilson_95_ci":[result["wilson_95_ci_low"],result["wilson_95_ci_high"]]})
    summary_path=REPORTS/"stage17_summary.json"
    if summary_path.exists():
        summary=json.loads(summary_path.read_text(encoding="utf-8"));summary["locked_test_used"]=True
        summary["locked_test_status"]=result["final_status"];summary["locked_test_type"]="directional_prediction"
        write_json(summary_path,summary)


def main()->int:
    # Resume is strictly read-only with respect to the locked test.
    if METRICS.exists() and LOCK.exists() and LOCK_SHA.exists():
        locked=json.loads(LOCK.read_text(encoding="utf-8"));expected=LOCK_SHA.read_text(encoding="ascii").strip()
        if canonical_hash(locked)!=expected:raise RuntimeError("Directional lock hash mismatch")
        result=json.loads(METRICS.read_text(encoding="utf-8"));synchronize_primary_reports(result)
        print(json.dumps({"resume":True,"new_test_evaluation":False,"result":result},indent=2));return 0
    protected=protected_files();before=snapshot(protected)
    features,manifest=load_features();prelock_features=features[features.metadata_split.isin(["train","validation"])].copy()
    prelock_ids=prelock_features.metadata_event_id.drop_duplicates().astype(int).tolist()
    targets=load_targets(prelock_ids,"train_validation_only")
    chosen,selection,_selection_model,prelock_data=choose_configuration(prelock_features,targets)
    columns=feature_sets(prelock_data)[chosen["feature_set"]]
    selection.to_csv(SELECTION,index=False)
    validation_payload={"status":"SELECTED","selection_rows":len(selection),"eligible_rows":int(selection.validation_eligible.sum()),
        "chosen":chosen,"target_query_event_ids":len(prelock_ids),"target_query_splits":["train","validation"],"test_target_rows_read":0,
        "feature_columns":columns,"predictive_feature_fields":[],"leakage":0}
    write_json(VALIDATION,validation_payload)
    folds=walkforward(prelock_data,chosen,columns);folds.to_csv(WALKFORWARD,index=False)
    y=directional_target(prelock_data[f"return_{chosen['horizon']}"],chosen["neutral_threshold"])
    final_model=pipeline_for(prelock_data,columns);final_model.fit(prelock_data[columns],y)
    joblib.dump(final_model,MODEL_FILE);model_sha=file_hash(MODEL_FILE)
    lock={"lock_version":"stage17_directional_lock_v1","locked_before_test_query":True,"model_version":MODEL_VERSION,
        "model_type":"multinomial_logistic_regression","model_parameters":{"C":1.0,"class_weight":"balanced","max_iter":3000},
        "feature_set":chosen["feature_set"],"feature_columns":columns,"subgroup":chosen["subgroup"],"horizon":chosen["horizon"],
        "neutral_threshold":chosen["neutral_threshold"],"latency_minutes":LATENCY,"confidence_threshold":chosen["confidence_threshold"],
        "classification_logic":"argmax UP/DOWN probability; NO_SIGNAL below confidence threshold or outside subgroup",
        "train_validation_event_ids_sha256":hashlib.sha256("\n".join(map(str,sorted(prelock_ids))).encode()).hexdigest(),
        "model_file":str(MODEL_FILE.relative_to(ROOT)),"model_sha256":model_sha,"stage17_manifest_sha256":file_hash(DATA/"manifest.json"),
        "stage16_input_hashes":manifest["input_dataset_hashes"],"test_outcomes_used_for_selection":False,"rules_changed_after_test":False}
    write_json(LOCK,lock);lock_hash=canonical_hash(lock);LOCK_SHA.write_text(lock_hash+"\n",encoding="ascii")
    if canonical_hash(json.loads(LOCK.read_text(encoding="utf-8")))!=lock_hash:raise RuntimeError("Lock persistence verification failed")

    # First and only target query for locked-test IDs occurs after the lock exists.
    test_features=features[features.metadata_split.eq("test")].copy();test_ids=test_features.metadata_event_id.drop_duplicates().astype(int).tolist()
    test_targets=load_targets(test_ids,"locked_test_after_config_lock")
    test_data=test_features.merge(test_targets,left_on=["metadata_event_id","metadata_asset"],right_on=["event_id","asset"],how="inner",validate="one_to_one")
    scored=prediction_rows(test_data,final_model,columns,lock["horizon"],lock["neutral_threshold"],lock["confidence_threshold"],lock["subgroup"])
    contamination=pd.read_parquet(DATA/"stage17_event_contamination.parquet")
    contamination=contamination[contamination.horizon.eq(lock["horizon"])][["event_id","asset","isolated_event","overlapping_event_within_horizon"]]
    scored=scored.merge(contamination,left_on=["metadata_event_id","metadata_asset"],right_on=["event_id","asset"],how="left",suffixes=("","_contamination"),validate="one_to_one")
    export_columns=["metadata_event_id","metadata_asset","metadata_published_at","metadata_source","source_event_type","actual_direction","predicted_direction","confidence",f"return_{lock['horizon']}","isolated_event","overlapping_event_within_horizon"]
    scored[export_columns].to_csv(PREDICTIONS,index=False)
    metrics=directional_metrics(scored);signals=scored[scored.predicted_direction.isin(["UP","DOWN"])].copy();baselines=baseline_metrics(signals)
    simple=max((baselines.get(k) or 0) for k in ("previous_1m_direction","previous_5m_direction","btc_trend_direction")) if baselines else None
    fold_stability=int((folds.excess_over_simple>0).sum());economics=economic_metrics(signals,lock["horizon"])
    if metrics["predictions"]<50 or metrics["coverage"]<.20 or metrics["up_predictions"]==0 or metrics["down_predictions"]==0 or metrics["max_prediction_class_share"]>.80:
        status="INSUFFICIENT_DATA"
    elif metrics["accuracy"]<=.55 or metrics["accuracy"]<=(baselines.get("majority_class") or 0) or metrics["accuracy"]<=(simple or 0):
        status="DIRECTIONAL_PREDICTION_NOT_SUPPORTED"
    elif metrics["wilson_95_ci_low"]<=.50 or fold_stability<2:
        status="PROMISING_BUT_NOT_CONFIRMED"
    else:status="DIRECTIONAL_PREDICTION_SUPPORTED"
    result={"final_status":status,"locked_test_accuracy":metrics["accuracy"],"honest_accuracy_above_55":bool(metrics["accuracy"]>.55) if metrics["accuracy"] is not None else None,
        "selected_horizon":lock["horizon"],"neutral_threshold":lock["neutral_threshold"],"latency_minutes":LATENCY,"confidence_threshold":lock["confidence_threshold"],
        "feature_set":lock["feature_set"],"subgroup":lock["subgroup"],**metrics,"baselines":baselines,"simple_market_baseline":simple,
        "folds_beating_simple_baseline":fold_stability,"folds_total":len(folds),"economic_secondary_metrics":economics,
        "lock_sha256":lock_hash,"model_sha256":model_sha,"test_target_query_after_lock":True,"test_target_rows":len(test_targets),
        "test_used_once":True,"test_used_for_tuning":False,"rules_changed_after_test":False,"leakage":0}
    write_json(METRICS,result)
    synchronize_primary_reports(result)
    pd.DataFrame([{"baseline":name,"accuracy":value} for name,value in baselines.items()]).to_csv(BASELINES,index=False)
    period_metrics(scored).to_csv(PERIODS,index=False)
    tests=pytest_run();after=snapshot(protected);unchanged=before==after

    # Update the central summary and put the directional gate first in the assessment.
    summary=json.loads((REPORTS/"stage17_summary.json").read_text(encoding="utf-8"));summary["directional_prediction"]=result
    summary["status"]="PASS" if summary.get("status")=="PASS" and tests["returncode"]==0 and unchanged else "FAIL"
    summary["research_status"]=status;summary["ml_training"]=True;summary["ml_scope"]="offline directional baseline only"
    summary["pytest_after_directional"]=tests;summary["protected_stage8_16_after_directional"]={"unchanged":unchanged}
    summary["final_questions_24"]={
        "1_data_units":{"unique_events":int(features.metadata_event_id.nunique()),"event_asset_rows":len(features)},
        "2_high_relevance":summary["final_questions"]["1_high_relevance_events_by_asset"],"3_material_high_quality":summary["final_questions"]["2_material_and_high_quality_events"],
        "4_variable_fields":summary["final_questions"]["4_variable_semantic_features"],"5_unusable_fields":summary["final_questions"]["5_unusable_fields"],
        "6_low_source_reliability":"AI score appears to mix message evidence/completeness with authenticity; code verification is authoritative.",
        "7_verified_source_reactions":"descriptive only; all represented sources are verified, leaving no unverified control",
        "8_direct_vs_indirect":"not corrected-significant on the validation primary family","9_confirmed_vs_proposals":"proposal/opinion control is insufficient in this dataset",
        "10_content_valence":"not an automatic direction and no preregistered valence rule passed the semantic gate",
        "11_high_impact_absolute_move":summary["final_questions"]["3_reactions_differ_from_weak_events"],"12_volatility_increase":"descriptive only; not the Stage 17 success criterion",
        "13_isolated_events":"reported separately; no validated effect","14_survives_validation":bool(chosen),
        "15_survives_locked_test":status in {"DIRECTIONAL_PREDICTION_SUPPORTED","PROMISING_BUT_NOT_CONFIRMED"},
        "16_walkforward_stability":f"{fold_stability}/{len(folds)} folds beat the simple market baseline",
        "17_search_adjusted":summary["search_adjusted_permutation"],"18_base_costs":economics,
        "19_directional_edge":status,"20_magnitude_volatility_edge":"not a success criterion under the latest Stage 17 update",
        "21_sol_sufficiency":"insufficient for a strong standalone conclusion","22_source_specific_sufficiency":"SEC/GitHub have coverage; Ethereum Foundation is descriptive only",
        "23_shadow_candidate":"yes" if status=="DIRECTIONAL_PREDICTION_SUPPORTED" and metrics["predictions"]>=50 else "no",
        "24_more_data_needed":status!="DIRECTIONAL_PREDICTION_SUPPORTED"}
    write_json(REPORTS/"stage17_summary.json",summary)
    answer="YES" if result["honest_accuracy_above_55"] and metrics["predictions"]>=50 else "INSUFFICIENT DATA" if metrics["predictions"]<50 else "NO"
    assessment=f"""# Stage 17 — High-Impact Directional Validation

## LOCKED TEST RESULT

**ЧИ ПЕРЕВИЩУЄ ЧЕСНА LOCKED-TEST ACCURACY 55%? {answer}**

- Final status: **{status}**
- Selected horizon: {lock['horizon']}
- Neutral threshold: {lock['neutral_threshold']:.2f}%
- Latency: {LATENCY}m
- Predictions: {metrics['predictions']} / {metrics['total_rows']} (coverage {metrics['coverage']:.2%})
- UP / DOWN / NO_SIGNAL: {metrics['up_predictions']} / {metrics['down_predictions']} / {metrics['no_signal']}
- Correct / incorrect: {metrics['correct']} / {metrics['incorrect']}
- Accuracy: {metrics['accuracy']:.4%}
- Balanced accuracy: {metrics['balanced_accuracy'] if metrics['balanced_accuracy'] is not None else 'N/A'}
- Majority baseline: {baselines.get('majority_class')}
- Strongest simple market baseline: {simple}
- Wilson 95% CI: [{metrics['wilson_95_ci_low']:.4%}, {metrics['wilson_95_ci_high']:.4%}]
- Cluster bootstrap 95% CI: [{metrics['cluster_bootstrap_95_ci_low']:.4%}, {metrics['cluster_bootstrap_95_ci_high']:.4%}]
- Walk-forward folds beating simple baseline: {fold_stability}/{len(folds)}
- Locked configuration SHA-256: `{lock_hash}`

The model was selected using train + validation only. The locked-test target query occurred after the configuration and model hashes were persisted. Test outcomes were not used for feature, horizon, threshold, subgroup, confidence, or model selection.

Magnitude and volatility findings are secondary and do not affect this final directional status. No OpenAI API, paper trading, real trading, production polling, or automatic trade was run.
"""
    (REPORTS/"stage17_final_assessment.md").write_text(assessment,encoding="utf-8")
    print(json.dumps({"status":status,"locked_test_accuracy":metrics["accuracy"],"predictions":metrics["predictions"],"coverage":metrics["coverage"],"wilson_low":metrics["wilson_95_ci_low"],"simple_baseline":simple},indent=2))
    return 0 if summary["status"]=="PASS" else 1


if __name__=="__main__":raise SystemExit(main())
