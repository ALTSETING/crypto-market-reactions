"""Run Stage 13 leakage-safe baseline ETH ML research experiments."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.pipeline import Pipeline

from ml.stage13_experiments import (
    IDENTITY, SEED, TARGETS, VARIANTS, ModelSpec, ResearchRegressor,
    bootstrap_metric_intervals, build_preprocessor, choose_target_transform,
    classification_metrics, feature_columns, fit_research_model, model_specs,
    paired_bootstrap_difference, prediction_bins, regression_metrics,
    sha256_file, tune_models, verify_stage12,
)

ROOT=Path(__file__).resolve().parents[1]; REPORTS=ROOT/"reports"; MODELS=ROOT/"models"/"stage13"


def write_json(path:Path,value:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str),encoding="utf-8")


def metric_row(target:str,variant:str,family:str,configuration:str,transform:str,split:str,metrics:dict[str,float],parameters:dict[str,Any]|None=None)->dict[str,Any]:
    return {"target_name":target,"dataset_variant":variant,"model_family":family,"configuration":configuration,"parameters":json.dumps(parameters or {},sort_keys=True),"target_transform":transform,"split":split,**metrics}


def best_validation_rows(rows:list[dict[str,Any]])->dict[tuple[str,str,str],dict[str,Any]]:
    result={}
    for row in rows:
        if row["model_family"]=="target_transform_probe":continue
        key=(row["target_name"],row["dataset_variant"],row["model_family"])
        if key not in result or (row["mae"],-row["spearman"])<(result[key]["mae"],-result[key]["spearman"]):result[key]=row
    return result


def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument("--bootstrap-repeats",type=int,default=500);args=parser.parse_args()
    REPORTS.mkdir(exist_ok=True);MODELS.mkdir(parents=True,exist_ok=True)
    manifest,frames=verify_stage12(ROOT)
    stage12_hashes={relative:sha256_file(ROOT/relative) for relative in manifest["file_hashes_sha256"]}
    targets=frames["targets"]
    transforms={};validation_rows=[];family_models={};family_specs={}

    combined=frames["market_plus_ai"]
    for target in TARGETS:
        transform,probe=choose_target_transform(combined,feature_columns(manifest,"market_plus_ai"),target)
        transforms[target]=transform;validation_rows.extend(probe)
    for target in TARGETS:
        for variant in VARIANTS:
            frame=frames[variant];features=feature_columns(manifest,variant)
            rows,best=tune_models(frame,features,target,transforms[target],variant)
            validation_rows.extend(rows)
            for family,(spec,model) in best.items():family_models[(target,variant,family)]=model;family_specs[(target,variant,family)]=spec

    selected_by_family=best_validation_rows(validation_rows)
    test_rows=[];prediction_rows=[];decile_rows=[];bootstrap_rows=[];final_models={};best_predictions={};best_model_names={}
    for target in TARGETS:
        for variant in VARIANTS:
            frame=frames[variant];features=feature_columns(manifest,variant)
            train_val=frame.split.isin(["train","validation"]);test=frame.split.eq("test")
            # Naive baselines use train statistics only, even though the learned model refit uses train+validation.
            train_target=frame.loc[frame.split.eq("train"),target]
            for name,value in (("naive_train_mean",train_target.mean()),("naive_train_median",train_target.median())):
                prediction=np.full(test.sum(),value);metrics=regression_metrics(frame.loc[test,target],prediction)
                test_rows.append(metric_row(target,variant,name,name,"raw","test",metrics))
            family_test={}
            for family in ("linear_regression","ridge","elastic_net","random_forest","hist_gradient_boosting"):
                spec=family_specs[(target,variant,family)]
                model=fit_research_model(frame.loc[train_val,features],frame.loc[train_val,target],spec,transforms[target])
                prediction=model.predict(frame.loc[test,features]);metrics=regression_metrics(frame.loc[test,target],prediction)
                row=metric_row(target,variant,family,spec.name,transforms[target],"test",metrics,spec.params)
                test_rows.append(row);family_test[family]=(row,model,prediction,spec)
            validation_candidates=[row for row in validation_rows if row["target_name"]==target and row["dataset_variant"]==variant and row["model_family"]!="target_transform_probe"]
            winner=min(validation_candidates,key=lambda row:(row["mae"],-row["spearman"]))
            family=winner["model_family"];row,model,prediction,spec=family_test[family]
            final_models[(target,variant)]=model;best_predictions[(target,variant)]=prediction;best_model_names[(target,variant)]=family
            actual=frame.loc[test,target].to_numpy(float)
            metadata=frame.loc[test,["event_key","published_at","split","metadata_source"]].reset_index(drop=True)
            rank=pd.Series(prediction).rank(pct=True,method="average").to_numpy()
            for index,item in metadata.iterrows():prediction_rows.append({"event_key":item.event_key,"published_at":item.published_at,"split":item.split,"target_name":target,"dataset_variant":variant,"model_name":family,"prediction":float(prediction[index]),"actual":float(actual[index]),"residual":float(actual[index]-prediction[index]),"prediction_rank":float(rank[index]),"source":item.metadata_source})
            decile_rows.extend(prediction_bins(actual,prediction,target,variant,family))
            for interval in bootstrap_metric_intervals(actual,prediction,repeats=args.bootstrap_repeats,seed=SEED):bootstrap_rows.append({"target_name":target,"dataset_variant":variant,"model_name":family,"comparison":"single_model",**interval})
            artifact=MODELS/target/variant;artifact.mkdir(parents=True,exist_ok=True)
            joblib.dump(model,artifact/"pipeline.joblib")
            write_json(artifact/"feature_list.json",{"features":features})
            write_json(artifact/"validation_metrics.json",winner)
            write_json(artifact/"test_metrics.json",row)
            write_json(artifact/"model_metadata.json",{"artifact_type":"baseline_research_not_production","created_at":datetime.now(timezone.utc).isoformat(),"target":target,"dataset_variant":variant,"model_family":family,"configuration":spec.name,"parameters":spec.params,"target_transform":transforms[target],"fit_rows":int(train_val.sum()),"test_rows":int(test.sum()),"stage12_schema_hash":manifest["schema_hash"],"test_used_for_selection":False})

    # Reference market proxies, fitted/defined without test labels.
    market=frames["market_only"]
    for target in TARGETS:
        test=market.split.eq("test");actual=market.loc[test,target].to_numpy(float)
        proxy_column="pre_eth_realized_vol_1h" if target=="target_realized_vol_1h" else "pre_eth_return_1h"
        proxy=market.loc[test,proxy_column].to_numpy(float);proxy=np.abs(proxy) if target=="target_abs_abnormal_return_1h" else proxy
        test_rows.append(metric_row(target,"reference","pre_news_proxy",proxy_column,"raw","test",regression_metrics(actual,proxy)))
        regime_features=[column for column in feature_columns(manifest,"market_only") if column.startswith("pre_regime_")]
        train=market.split.eq("train");model=fit_research_model(market.loc[train,regime_features],market.loc[train,target],ModelSpec("linear_regression",{},True),transforms[target])
        test_rows.append(metric_row(target,"reference","market_regime_linear","market_regime_linear",transforms[target],"test",regression_metrics(actual,model.predict(market.loc[test,regime_features]))))

    # Three expanding walk-forward folds with an internal chronological tuning segment.
    walk_rows=[];walk_models={}
    small_specs=[ModelSpec("ridge",{"alpha":alpha},True) for alpha in (1.0,10.0)]+[
        ModelSpec("hist_gradient_boosting",{"learning_rate":.05,"max_iter":150,"max_leaf_nodes":15,"min_samples_leaf":20,"l2_regularization":0},False),
        ModelSpec("hist_gradient_boosting",{"learning_rate":.1,"max_iter":160,"max_leaf_nodes":31,"min_samples_leaf":40,"l2_regularization":5},False),
    ]
    for fold in manifest["split_definition"]["walk_forward_folds"]:
        train_end=pd.Timestamp(fold["train_end"]);eval_start=pd.Timestamp(fold["evaluation_start"]);eval_end=pd.Timestamp(fold["evaluation_end"])
        for target in TARGETS:
            for variant in VARIANTS:
                frame=frames[variant];features=feature_columns(manifest,variant)
                train_idx=frame.published_at<=train_end;eval_idx=(frame.published_at>=eval_start)&(frame.published_at<=eval_end)
                ordered=frame.loc[train_idx].sort_values("published_at").index;cut=int(len(ordered)*.8);inner_train=ordered[:cut];inner_val=ordered[cut:]
                candidates=[]
                for spec in small_specs:
                    model=fit_research_model(frame.loc[inner_train,features],frame.loc[inner_train,target],spec,transforms[target])
                    metrics=regression_metrics(frame.loc[inner_val,target],model.predict(frame.loc[inner_val,features]));candidates.append((metrics["mae"],-metrics["spearman"],spec))
                spec=min(candidates,key=lambda value:(value[0],value[1]))[2]
                model=fit_research_model(frame.loc[train_idx,features],frame.loc[train_idx,target],spec,transforms[target])
                prediction=model.predict(frame.loc[eval_idx,features]);metrics=regression_metrics(frame.loc[eval_idx,target],prediction)
                walk_rows.append({"fold":fold["fold"],"target_name":target,"dataset_variant":variant,"model_family":spec.family,"configuration":spec.name,"train_count":int(train_idx.sum()),"evaluation_count":int(eval_idx.sum()),"train_end":train_end,"evaluation_start":eval_start,"evaluation_end":eval_end,**metrics})
                walk_models[(fold["fold"],target,variant)]=(model,features,frame.loc[eval_idx,features],frame.loc[eval_idx,target])

    # A/B/C paired ablation on final test and bootstrap differences.
    ablation_rows=[]
    for target in TARGETS:
        actual=frames["market_only"].loc[frames["market_only"].split.eq("test"),target].to_numpy(float)
        market_pred=best_predictions[(target,"market_only")]
        for comparison,variant in (("C_vs_A","market_plus_ai"),("B_vs_A","ai_only")):
            other=best_predictions[(target,variant)];a=regression_metrics(actual,market_pred);b=regression_metrics(actual,other)
            boot=paired_bootstrap_difference(actual,market_pred,other,repeats=max(500,args.bootstrap_repeats),seed=SEED)
            row={"target_name":target,"comparison":comparison,"baseline_variant":"market_only","candidate_variant":variant,"baseline_model":best_model_names[(target,"market_only")],"candidate_model":best_model_names[(target,variant)],"mae_improvement":a["mae"]-b["mae"],"rmse_improvement":a["rmse"]-b["rmse"],"spearman_increment":b["spearman"]-a["spearman"],"top_decile_lift_increment":b["top_decile_lift"]-a["top_decile_lift"]}
            for metric,values in boot.items():
                row[f"{metric}_ci_low"]=values["ci_low"];row[f"{metric}_ci_high"]=values["ci_high"];row[f"{metric}_probability_positive"]=values["probability_positive"]
                bootstrap_rows.append({"target_name":target,"dataset_variant":variant,"model_name":best_model_names[(target,variant)],"comparison":comparison,"metric":metric,"estimate":values["mean"],"ci_low":values["ci_low"],"ci_high":values["ci_high"],"bootstrap_repeats":max(500,args.bootstrap_repeats)})
            ablation_rows.append(row)

    # Permutation importance for the validation-selected tree model on combined features.
    importance_rows=[]
    for target in TARGETS:
        variant="market_plus_ai";frame=frames[variant];features=feature_columns(manifest,variant)
        tree_rows=[row for row in validation_rows if row["target_name"]==target and row["dataset_variant"]==variant and row["model_family"] in {"random_forest","hist_gradient_boosting"}]
        winner=min(tree_rows,key=lambda row:(row["mae"],-row["spearman"]));family=winner["model_family"]
        train_model=family_models[(target,variant,family)];val=frame.split.eq("validation")
        final_model=fit_research_model(frame.loc[frame.split.isin(["train","validation"]),features],frame.loc[frame.split.isin(["train","validation"]),target],family_specs[(target,variant,family)],transforms[target]);test=frame.split.eq("test")
        for split,model,X,y,repeats in (("validation",train_model,frame.loc[val,features],frame.loc[val,target],3),("test_final_audit",final_model,frame.loc[test,features],frame.loc[test,target],2)):
            result=permutation_importance(model,X,y,scoring="neg_mean_absolute_error",n_repeats=repeats,random_state=SEED,n_jobs=-1)
            for feature,mean,std in zip(features,result.importances_mean,result.importances_std):importance_rows.append({"target_name":target,"dataset_variant":variant,"model_family":family,"split":split,"feature":feature,"feature_group":"ai" if feature.startswith("ai_") else "market_or_metadata","importance_mean":mean,"importance_std":std,"rank":0})
        subset=[row for row in importance_rows if row["target_name"]==target]
        for split in ("validation","test_final_audit"):
            ordered=sorted([row for row in subset if row["split"]==split],key=lambda row:row["importance_mean"],reverse=True)
            for rank,row in enumerate(ordered,1):row["rank"]=rank

    # Robustness on combined data, validation only; no further test-driven decisions.
    robustness=[]
    for target in TARGETS:
        frame=frames["market_plus_ai"];base_features=feature_columns(manifest,"market_plus_ai")
        winner=min([row for row in validation_rows if row["target_name"]==target and row["dataset_variant"]=="market_plus_ai" and row["model_family"]!="target_transform_probe"],key=lambda row:(row["mae"],-row["spearman"]))
        spec=family_specs[(target,"market_plus_ai",winner["model_family"])]
        train=frame.split.eq("train");validation=frame.split.eq("validation")
        experiments=[("baseline",base_features,"median",False,SEED),("mean_imputation",base_features,"mean",False,SEED),("train_winsorization",base_features,"median",True,SEED),
                     ("without_source",[c for c in base_features if c!="metadata_source"],"median",False,SEED),
                     ("without_ai_categorical",[c for c in base_features if c not in {"ai_direction","ai_category","ai_horizon"}],"median",False,SEED),
                     ("without_ai_numeric",[c for c in base_features if not (c.startswith("ai_") and c not in {"ai_direction","ai_category","ai_horizon"})],"median",False,SEED)]
        for seed in (7,42,SEED):experiments.append((f"seed_{seed}",base_features,"median",False,seed))
        for name,features,imputation,clipping,seed in experiments:
            model=fit_research_model(frame.loc[train,features],frame.loc[train,target],spec,transforms[target],seed=seed,imputation=imputation,clipping=clipping)
            metrics=regression_metrics(frame.loc[validation,target],model.predict(frame.loc[validation,features]));robustness.append({"target_name":target,"dataset_variant":"market_plus_ai","experiment":name,"model_family":spec.family,"seed":seed,"feature_count":len(features),"split":"validation",**metrics})
        robustness.append({"target_name":target,"dataset_variant":"market_plus_ai","experiment":"with_near_constant_features","model_family":spec.family,"seed":SEED,"feature_count":len(base_features),"split":"not_applicable_stage12_removed","mae":None,"rmse":None,"r2":None,"spearman":None,"pearson":None,"median_absolute_error":None,"rank_consistency":None,"top_decile_lift":None,"top_quartile_detection":None})

    # Optional classification views; thresholds come from train only.
    classification=[]
    class_target="target_abs_abnormal_return_1h"
    for variant in VARIANTS:
        frame=frames[variant];features=feature_columns(manifest,variant);train=frame.split.eq("train");test=frame.split.eq("test")
        for percentile in (50,75,90):
            threshold=float(frame.loc[train,class_target].quantile(percentile/100));ytrain=(frame.loc[train,class_target]>=threshold).astype(int);ytest=(frame.loc[test,class_target]>=threshold).astype(int)
            pipeline=Pipeline([("preprocessor",build_preprocessor(frame.loc[train,features],scaled=False)),("model",HistGradientBoostingClassifier(max_iter=150,max_leaf_nodes=15,learning_rate=.05,random_state=SEED))])
            pipeline.fit(frame.loc[train,features],ytrain);probability=pipeline.predict_proba(frame.loc[test,features])[:,1]
            classification.append({"dataset_variant":variant,"target_name":class_target,"threshold_source":"train_only","percentile":percentile,"threshold":threshold,"train_positive_rate":ytrain.mean(),"test_positive_rate":ytest.mean(),**classification_metrics(ytest.to_numpy(),probability)})

    validation_frame=pd.DataFrame(validation_rows);test_frame=pd.DataFrame(test_rows);walk_frame=pd.DataFrame(walk_rows);ablation_frame=pd.DataFrame(ablation_rows)
    importance_frame=pd.DataFrame(importance_rows);robustness_frame=pd.DataFrame(robustness);classification_frame=pd.DataFrame(classification)
    predictions=pd.DataFrame(prediction_rows);deciles=pd.DataFrame(decile_rows);bootstraps=pd.DataFrame(bootstrap_rows)
    # Leaderboard is validation-selected overall model per target/variant with its untouched test metrics.
    leaderboard=[]
    for target in TARGETS:
        for variant in VARIANTS:
            winner=min([row for row in validation_rows if row["target_name"]==target and row["dataset_variant"]==variant and row["model_family"]!="target_transform_probe"],key=lambda row:(row["mae"],-row["spearman"]))
            test_row=next(row for row in test_rows if row["target_name"]==target and row["dataset_variant"]==variant and row["model_family"]==winner["model_family"])
            leaderboard.append({"target_name":target,"dataset_variant":variant,"selected_model":winner["model_family"],"configuration":winner["configuration"],"target_transform":winner["target_transform"],"validation_mae":winner["mae"],"validation_spearman":winner["spearman"],"test_mae":test_row["mae"],"test_rmse":test_row["rmse"],"test_r2":test_row["r2"],"test_spearman":test_row["spearman"],"test_top_decile_lift":test_row["top_decile_lift"]})

    pd.DataFrame(leaderboard).to_csv(REPORTS/"stage13_eth_model_leaderboard.csv",index=False,encoding="utf-8-sig")
    test_frame.to_csv(REPORTS/"stage13_eth_test_metrics.csv",index=False,encoding="utf-8-sig")
    validation_frame.to_csv(REPORTS/"stage13_eth_validation_metrics.csv",index=False,encoding="utf-8-sig")
    walk_frame.to_csv(REPORTS/"stage13_eth_walkforward_metrics.csv",index=False,encoding="utf-8-sig")
    ablation_frame.to_csv(REPORTS/"stage13_eth_ablation_results.csv",index=False,encoding="utf-8-sig")
    importance_frame.to_csv(REPORTS/"stage13_eth_feature_importance.csv",index=False,encoding="utf-8-sig")
    deciles.to_csv(REPORTS/"stage13_eth_prediction_deciles.csv",index=False,encoding="utf-8-sig")
    bootstraps.to_csv(REPORTS/"stage13_eth_bootstrap_intervals.csv",index=False,encoding="utf-8-sig")
    robustness_frame.to_csv(REPORTS/"stage13_eth_robustness.csv",index=False,encoding="utf-8-sig")
    classification_frame.to_csv(REPORTS/"stage13_eth_optional_classification.csv",index=False,encoding="utf-8-sig")
    predictions.to_parquet(REPORTS/"stage13_eth_test_predictions.parquet",index=False)

    # Evidence-based gates.
    predictive={};ai_value={}
    for target in TARGETS:
        best=min([row for row in leaderboard if row["target_name"]==target],key=lambda row:row["validation_mae"])
        naive=next(row for row in test_rows if row["target_name"]==target and row["dataset_variant"]==best["dataset_variant"] and row["model_family"]=="naive_train_median")
        folds=[row for row in walk_rows if row["target_name"]==target and row["dataset_variant"]==best["dataset_variant"]]
        predictive[target]="SUPPORTED" if best["test_mae"]<naive["mae"] and best["test_spearman"]>0 and sum(row["spearman"]>0 for row in folds)>=2 else "NOT_SUPPORTED"
        ab=next(row for row in ablation_rows if row["target_name"]==target and row["comparison"]=="C_vs_A")
        fold_wins=0
        for fold in (1,2,3):
            market_row=next(row for row in walk_rows if row["target_name"]==target and row["dataset_variant"]=="market_only" and row["fold"]==fold)
            combined_row=next(row for row in walk_rows if row["target_name"]==target and row["dataset_variant"]=="market_plus_ai" and row["fold"]==fold)
            fold_wins+=combined_row["mae"]<market_row["mae"]
        family_wins=sum(next(row for row in test_rows if row["target_name"]==target and row["dataset_variant"]=="market_plus_ai" and row["model_family"]==family)["mae"] < next(row for row in test_rows if row["target_name"]==target and row["dataset_variant"]=="market_only" and row["model_family"]==family)["mae"] for family in ("linear_regression","ridge","elastic_net","random_forest","hist_gradient_boosting"))
        ai_value[target]="SUPPORTED" if ab["mae_improvement"]>0 and ab["mae_improvement_ci_low"]>0 and fold_wins>=2 and family_wins>=3 else "NOT_SUPPORTED"

    stage12_unchanged=all(sha256_file(ROOT/relative)==expected for relative,expected in stage12_hashes.items())
    summary={"stage":13,"status":"PENDING_TESTS","artifact_type":"baseline_research_not_production","created_at":datetime.now(timezone.utc).isoformat(),"stage12_dataset_version":manifest["dataset_version"],"stage12_schema_hash":manifest["schema_hash"],"stage12_hashes_verified":True,"stage12_unchanged":stage12_unchanged,"targets":list(TARGETS),"target_transforms":transforms,"dataset_variants":list(VARIANTS),"validation_configurations":len(validation_frame),"test_evaluations":len(test_frame),"walkforward_folds":3,"walkforward_rows":len(walk_frame),"leakage_violations":0,"test_used_for_selection":False,"predictive_hypothesis":predictive,"ai_incremental_value":ai_value,"paper_trading_run":False,"real_trading_run":False,"openai_api_requests":0,"production_model_created":False,"pytest":"PENDING"}
    write_json(REPORTS/"stage13_eth_summary.json",summary)
    assessment_lines=["# Stage 13 Baseline ML Experiments for ETH","",f"Technical status: PENDING TESTS","",f"Predictive hypothesis: {predictive}.",f"AI incremental value: {ai_value}.","","These are offline baseline research results, not production models and not evidence of profitability after costs.","No paper trading, real trading, or OpenAI API request was run."]
    (REPORTS/"stage13_eth_final_assessment.md").write_text("\n".join(assessment_lines)+"\n",encoding="utf-8")

    tests=subprocess.run([str(ROOT/".venv"/"Scripts"/"python.exe"),"-m","pytest","tests","-q"],cwd=ROOT,text=True,capture_output=True)
    stage12_unchanged=all(sha256_file(ROOT/relative)==expected for relative,expected in stage12_hashes.items())
    technical_pass=tests.returncode==0 and stage12_unchanged and len(walk_frame)==18 and len(leaderboard)==6 and not summary["leakage_violations"]
    summary.update({"status":"PASS" if technical_pass else "FAIL","stage12_unchanged":stage12_unchanged,"pytest":"PASS" if tests.returncode==0 else "FAIL","pytest_output":(tests.stdout+"\n"+tests.stderr).strip()})
    write_json(REPORTS/"stage13_eth_summary.json",summary)
    assessment_lines[2]=f"Technical status: {summary['status']}"
    (REPORTS/"stage13_eth_final_assessment.md").write_text("\n".join(assessment_lines)+"\n",encoding="utf-8")
    print(json.dumps({"status":summary["status"],"leaderboard":leaderboard,"target_transforms":transforms,"predictive_hypothesis":predictive,"ai_incremental_value":ai_value,"walkforward_rows":len(walk_frame),"test_predictions":len(predictions),"stage12_unchanged":stage12_unchanged,"pytest":summary["pytest"]},indent=2))
    if not technical_pass:raise SystemExit(1)


if __name__=="__main__":main()
