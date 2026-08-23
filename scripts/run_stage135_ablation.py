import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from ml.stage13_experiments import ModelSpec,fit_research_model,regression_metrics

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/"reports";DATA=ROOT/"data/stage135"
VARIANTS=("market_core","market_futures","market_futures_primary_timing")
TARGETS=("target_abs_abnormal_return_5m","target_realized_vol_5m","target_abs_abnormal_return_1h","target_realized_vol_1h")
IDENTITY={"dataset_version","event_key","news_id","published_at","baseline_time","split"}
ALPHAS=(.1,1.0,10.0)
def spec(alpha):return ModelSpec("ridge",{"alpha":alpha},True)
def fit(frame,features,target,train_idx,alpha):return fit_research_model(frame.loc[train_idx,features],frame.loc[train_idx,target],spec(alpha),"log1p")
def main():
 targets=pd.read_parquet(DATA/"targets.parquet");validation_rows=[];test_rows=[];walk_rows=[];importance=[];selected={}
 frames={name:pd.read_parquet(DATA/f"{name}.parquet").merge(targets[["event_key",*TARGETS]],on="event_key",validate="one_to_one") for name in VARIANTS}
 for target in TARGETS:
  for variant,frame in frames.items():
   features=[c for c in frame if c not in IDENTITY and not c.startswith("target_")];train=frame.split.eq("train");validation=frame.split.eq("validation");test=frame.split.eq("test")
   candidates=[]
   for alpha in ALPHAS:
    model=fit(frame,features,target,train,alpha);metrics=regression_metrics(frame.loc[validation,target].to_numpy(),model.predict(frame.loc[validation,features]));row={"target":target,"variant":variant,"alpha":alpha,"split":"validation",**metrics};validation_rows.append(row);candidates.append(row)
   winner=min(candidates,key=lambda x:x["mae"]);alpha=winner["alpha"];selected[(target,variant)]=alpha;model=fit(frame,features,target,train|validation,alpha);metrics=regression_metrics(frame.loc[test,target].to_numpy(),model.predict(frame.loc[test,features]));test_rows.append({"target":target,"variant":variant,"alpha":alpha,"split":"test",**metrics})
   pipe=model.pipeline;names=pipe.named_steps["preprocessor"].get_feature_names_out();coef=np.ravel(pipe.named_steps["model"].coef_)
   for name,value in sorted(zip(names,coef),key=lambda x:abs(x[1]),reverse=True)[:30]:importance.append({"target":target,"variant":variant,"feature":name,"coefficient":value,"absolute_importance":abs(value)})
   ordered=frame.sort_values("published_at").reset_index(drop=True)
   bounds=[(.40,.60),(.60,.80),(.80,1.0)]
   for fold,(train_fraction,end_fraction) in enumerate(bounds,1):
    train_end=int(len(ordered)*train_fraction);eval_end=int(len(ordered)*end_fraction);history=ordered.iloc[:train_end];evaluation=ordered.iloc[train_end:eval_end];inner_cut=int(len(history)*.8)
    inner_train=history.index[:inner_cut];inner_val=history.index[inner_cut:];fold_candidates=[]
    for candidate in ALPHAS:
     m=fit(ordered,features,target,ordered.index.isin(inner_train),candidate);fold_candidates.append((regression_metrics(history.loc[inner_val,target].to_numpy(),m.predict(history.loc[inner_val,features]))["mae"],candidate))
    fold_alpha=min(fold_candidates)[1];m=fit(ordered,features,target,ordered.index<train_end,fold_alpha);met=regression_metrics(evaluation[target].to_numpy(),m.predict(evaluation[features]));walk_rows.append({"target":target,"variant":variant,"fold":fold,"alpha":fold_alpha,"train_count":train_end,"evaluation_count":len(evaluation),"train_end":history.published_at.max(),"evaluation_start":evaluation.published_at.min(),**met})
 validation=pd.DataFrame(validation_rows);test=pd.DataFrame(test_rows);walk=pd.DataFrame(walk_rows);imp=pd.DataFrame(importance)
 validation.to_csv(REPORTS/"stage135_validation_metrics.csv",index=False);test.to_csv(REPORTS/"stage135_ablation_metrics.csv",index=False);walk.to_csv(REPORTS/"stage135_walkforward_metrics.csv",index=False);imp.to_csv(REPORTS/"stage135_feature_importance.csv",index=False)
 increments=[]
 for target in TARGETS:
  base=test.query("target == @target and variant == 'market_core'").iloc[0]
  for variant in VARIANTS[1:]:
   candidate=test.query("target == @target and variant == @variant").iloc[0];fold_base=walk.query("target == @target and variant == 'market_core'").set_index("fold");fold_candidate=walk.query("target == @target and variant == @variant").set_index("fold")
   increments.append({"target":target,"variant":variant,"test_mae_improvement":base.mae-candidate.mae,"test_spearman_increment":candidate.spearman-base.spearman,"walkforward_folds_mae_better":int((fold_candidate.mae<fold_base.mae).sum()),"incremental_value_supported":bool(base.mae>candidate.mae and (fold_candidate.mae<fold_base.mae).sum()>=2)})
 incremental=pd.DataFrame(increments);incremental.to_csv(REPORTS/"stage135_incremental_value.csv",index=False)
 print(json.dumps({"test":test[["target","variant","mae","r2","spearman","top_decile_lift"]].to_dict("records"),"incremental":incremental.to_dict("records")},indent=2))
if __name__=="__main__":main()
