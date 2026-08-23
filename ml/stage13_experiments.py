"""Leakage-safe baseline ML utilities for Stage 13 ETH research experiments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, pearsonr, spearmanr
from sklearn.base import BaseEstimator, RegressorMixin, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, LinearRegression, Ridge
from sklearn.metrics import (
    average_precision_score, balanced_accuracy_score, mean_absolute_error,
    mean_squared_error, median_absolute_error, precision_score, r2_score,
    recall_score, roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

SEED = 20260718
TARGETS = ("target_abs_abnormal_return_1h", "target_realized_vol_1h")
VARIANTS = {
    "market_only": "eth_market_only.parquet",
    "ai_only": "eth_ai_only.parquet",
    "market_plus_ai": "eth_market_plus_ai.parquet",
}
IDENTITY = ("dataset_version", "event_key", "news_id", "published_at", "baseline_time", "split")


class NumericWinsorizer(BaseEstimator, TransformerMixin):
    def __init__(self, lower: float = .005, upper: float = .995):
        self.lower = lower; self.upper = upper

    def fit(self, X: Any, y: Any = None) -> "NumericWinsorizer":
        values=np.asarray(X,dtype=float)
        self.lower_bounds_=np.nanquantile(values,self.lower,axis=0)
        self.upper_bounds_=np.nanquantile(values,self.upper,axis=0)
        return self

    def transform(self, X: Any) -> np.ndarray:
        return np.clip(np.asarray(X,dtype=float),self.lower_bounds_,self.upper_bounds_)


class ResearchRegressor(BaseEstimator, RegressorMixin):
    """Serializable research-only wrapper that inverses train-selected target transforms."""
    def __init__(self, pipeline: Pipeline, target_transform: str = "raw"):
        self.pipeline=pipeline; self.target_transform=target_transform

    def fit(self, X: pd.DataFrame, y: Any) -> "ResearchRegressor":
        values=np.asarray(y,dtype=float)
        if self.target_transform=="log1p": transformed=np.log1p(np.maximum(values,0))
        elif self.target_transform=="winsorized":
            self.target_lower_=float(np.quantile(values,.005)); self.target_upper_=float(np.quantile(values,.995))
            transformed=np.clip(values,self.target_lower_,self.target_upper_)
        else: transformed=values
        self.pipeline.fit(X,transformed); return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        predictions=np.asarray(self.pipeline.predict(X),dtype=float)
        if self.target_transform=="log1p": predictions=np.expm1(predictions)
        return np.maximum(predictions,0)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_stage12(root: Path) -> tuple[dict[str,Any],dict[str,pd.DataFrame]]:
    data=root/"data"/"stage12"; manifest=json.loads((data/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_version")!="stage12_eth_v1": raise ValueError("Unexpected Stage 12 dataset version")
    mismatches=[relative for relative,expected in manifest["file_hashes_sha256"].items() if not (root/relative).exists() or sha256_file(root/relative)!=expected]
    if mismatches: raise ValueError(f"Stage 12 hash mismatch: {mismatches}")
    frames={name:pd.read_parquet(data/filename) for name,filename in VARIANTS.items()}
    targets=pd.read_parquet(data/"eth_targets.parquet"); frames["targets"]=targets
    expected=targets.event_key.tolist()
    for name,frame in frames.items():
        if frame.event_key.tolist()!=expected or frame.event_key.duplicated().any(): raise ValueError(f"Event alignment failure: {name}")
        if frame.split.value_counts().to_dict()!={"train":4110,"test":1371,"validation":1370}: raise ValueError(f"Split changed: {name}")
    return manifest,frames


def feature_columns(manifest: dict[str,Any],variant: str) -> list[str]:
    filename=VARIANTS[variant]
    columns=list(manifest["split_definition"] and manifest["feature_list"])
    if variant=="market_only": columns=[c for c in columns if not c.startswith("ai_")]
    elif variant=="ai_only": columns=[c for c in columns if c.startswith(("ai_","metadata_"))]
    if any(c.startswith("target_") for c in columns): raise ValueError("Target leaked into feature list")
    return columns


def build_preprocessor(X: pd.DataFrame, *, scaled: bool, imputation: str = "median", clipping: bool = False) -> ColumnTransformer:
    numeric=X.select_dtypes(include=[np.number,"bool"]).columns.tolist()
    categorical=[column for column in X.columns if column not in numeric]
    numeric_steps=[]
    if clipping: numeric_steps.append(("winsor",NumericWinsorizer()))
    numeric_steps.append(("imputer",SimpleImputer(strategy=imputation if imputation in {"median","mean"} else "constant",fill_value=0,add_indicator=True)))
    if scaled: numeric_steps.append(("scaler",StandardScaler()))
    numeric_pipeline=Pipeline(numeric_steps)
    categorical_pipeline=Pipeline([
        ("imputer",SimpleImputer(strategy="constant",fill_value="__missing__")),
        ("onehot",OneHotEncoder(handle_unknown="ignore",sparse_output=False)),
    ])
    return ColumnTransformer([("numeric",numeric_pipeline,numeric),("categorical",categorical_pipeline,categorical)],remainder="drop")


@dataclass(frozen=True)
class ModelSpec:
    family: str
    params: dict[str,Any]
    scaled: bool

    @property
    def name(self) -> str:
        suffix="_".join(f"{key}-{value}" for key,value in sorted(self.params.items()))
        return self.family+("__"+suffix if suffix else "")


def model_specs() -> list[ModelSpec]:
    specs=[ModelSpec("linear_regression",{},True)]
    specs += [ModelSpec("ridge",{"alpha":alpha},True) for alpha in (.1,1.0,10.0,100.0)]
    specs += [ModelSpec("elastic_net",{"alpha":alpha,"l1_ratio":ratio,"max_iter":5000},True) for alpha,ratio in ((.001,.1),(.01,.5),(.1,.9))]
    specs += [ModelSpec("random_forest",{"n_estimators":100,"max_depth":depth,"min_samples_leaf":leaf,"max_features":.7},False) for depth,leaf in ((6,2),(10,2),(14,5),(None,8))]
    specs += [ModelSpec("hist_gradient_boosting",{"learning_rate":rate,"max_iter":iterations,"max_leaf_nodes":leaves,"min_samples_leaf":leaf,"l2_regularization":l2},False) for rate,iterations,leaves,leaf,l2 in ((.05,150,15,20,0),(.05,200,31,20,1),(.1,120,15,30,1),(.1,160,31,40,5))]
    return specs


def estimator(spec: ModelSpec, seed: int = SEED) -> Any:
    params=dict(spec.params)
    if spec.family=="linear_regression": return LinearRegression()
    if spec.family=="ridge": return Ridge(**params)
    if spec.family=="elastic_net": return ElasticNet(random_state=seed,**params)
    if spec.family=="random_forest": return RandomForestRegressor(random_state=seed,n_jobs=-1,**params)
    if spec.family=="hist_gradient_boosting": return HistGradientBoostingRegressor(random_state=seed,**params)
    raise ValueError(spec.family)


def fit_research_model(X: pd.DataFrame,y: pd.Series,spec:ModelSpec,transform:str,*,seed:int=SEED,imputation:str="median",clipping:bool=False) -> ResearchRegressor:
    pipeline=Pipeline([("preprocessor",build_preprocessor(X,scaled=spec.scaled,imputation=imputation,clipping=clipping)),("model",estimator(spec,seed))])
    return ResearchRegressor(pipeline,target_transform=transform).fit(X,y)


def safe_correlation(function: Any,y:np.ndarray,prediction:np.ndarray) -> float:
    if np.std(y)==0 or np.std(prediction)==0:return 0.0
    value=function(y,prediction).statistic
    return float(value) if np.isfinite(value) else 0.0


def regression_metrics(y:Any,prediction:Any) -> dict[str,float]:
    actual=np.asarray(y,dtype=float); predicted=np.asarray(prediction,dtype=float)
    count=max(1,int(np.ceil(len(actual)*.10))); top=np.argsort(predicted)[-count:]
    overall=float(np.mean(actual)); tau=kendalltau(actual,predicted).statistic
    return {
        "mae":float(mean_absolute_error(actual,predicted)),"rmse":float(mean_squared_error(actual,predicted)**.5),
        "r2":float(r2_score(actual,predicted)),"spearman":safe_correlation(spearmanr,actual,predicted),
        "pearson":safe_correlation(pearsonr,actual,predicted),"median_absolute_error":float(median_absolute_error(actual,predicted)),
        "rank_consistency":float((tau+1)/2) if np.isfinite(tau) else .5,
        "top_decile_lift":float(np.mean(actual[top])/overall) if overall else 0.0,
        "top_quartile_detection":float(np.mean(actual[np.argsort(predicted)[-max(1,int(np.ceil(len(actual)*.25))):]]>=np.quantile(actual,.75))),
    }


def prediction_bins(y:Any,prediction:Any,target:str,variant:str,model:str) -> list[dict[str,Any]]:
    frame=pd.DataFrame({"actual":np.asarray(y,float),"prediction":np.asarray(prediction,float)})
    frame["decile"]=pd.qcut(frame.prediction.rank(method="first"),10,labels=False)+1
    rows=[]
    for decile,part in frame.groupby("decile"):
        rows.append({"target_name":target,"dataset_variant":variant,"model_name":model,"group_type":"prediction_decile","group":int(decile),"count":len(part),"prediction_mean":part.prediction.mean(),"actual_mean":part.actual.mean(),"actual_median":part.actual.median(),"lift_vs_overall":part.actual.mean()/frame.actual.mean()})
    for percentage in (5,10,20):
        count=max(1,int(np.ceil(len(frame)*percentage/100))); part=frame.nlargest(count,"prediction")
        rows.append({"target_name":target,"dataset_variant":variant,"model_name":model,"group_type":"top_rank","group":f"top_{percentage}pct","count":len(part),"prediction_mean":part.prediction.mean(),"actual_mean":part.actual.mean(),"actual_median":part.actual.median(),"lift_vs_overall":part.actual.mean()/frame.actual.mean()})
    return rows


def choose_target_transform(frame:pd.DataFrame,features:list[str],target:str) -> tuple[str,list[dict[str,Any]]]:
    train=frame.split.eq("train"); validation=frame.split.eq("validation")
    Xtrain=frame.loc[train,features]; Xvalidation=frame.loc[validation,features]
    spec=ModelSpec("ridge",{"alpha":10.0},True); rows=[]
    for transform in ("raw","log1p","winsorized"):
        model=fit_research_model(Xtrain,frame.loc[train,target],spec,transform)
        metrics=regression_metrics(frame.loc[validation,target],model.predict(Xvalidation))
        rows.append({"target_name":target,"dataset_variant":"market_plus_ai","model_family":"target_transform_probe","configuration":spec.name,"target_transform":transform,"split":"validation",**metrics})
    winner=min(rows,key=lambda row:(row["mae"],-row["spearman"]))["target_transform"]
    return str(winner),rows


def tune_models(frame:pd.DataFrame,features:list[str],target:str,transform:str,variant:str) -> tuple[list[dict[str,Any]],dict[str,tuple[ModelSpec,ResearchRegressor]]]:
    train=frame.split.eq("train"); validation=frame.split.eq("validation")
    Xtrain=frame.loc[train,features]; Xvalidation=frame.loc[validation,features]
    rows=[]; best:dict[str,tuple[ModelSpec,ResearchRegressor]]={}
    for spec in model_specs():
        model=fit_research_model(Xtrain,frame.loc[train,target],spec,transform)
        metrics=regression_metrics(frame.loc[validation,target],model.predict(Xvalidation))
        row={"target_name":target,"dataset_variant":variant,"model_family":spec.family,"configuration":spec.name,"parameters":json.dumps(spec.params,sort_keys=True),"target_transform":transform,"split":"validation",**metrics}
        rows.append(row)
        current=best.get(spec.family)
        if current is None:
            best[spec.family]=(spec,model)
        else:
            current_row=next(item for item in rows if item["configuration"]==current[0].name)
            if (row["mae"],-row["spearman"])<(current_row["mae"],-current_row["spearman"]):best[spec.family]=(spec,model)
    return rows,best


def bootstrap_metric_intervals(y:np.ndarray,prediction:np.ndarray,*,repeats:int=500,seed:int=SEED) -> list[dict[str,Any]]:
    rng=np.random.default_rng(seed); values={"mae":[],"spearman":[],"top_decile_lift":[]}
    for _ in range(repeats):
        index=rng.integers(0,len(y),len(y)); metrics=regression_metrics(y[index],prediction[index])
        for name in values:values[name].append(metrics[name])
    return [{"metric":name,"estimate":regression_metrics(y,prediction)[name],"ci_low":float(np.quantile(series,.025)),"ci_high":float(np.quantile(series,.975)),"bootstrap_repeats":repeats} for name,series in values.items()]


def paired_bootstrap_difference(y:np.ndarray,pred_a:np.ndarray,pred_b:np.ndarray,*,repeats:int=1000,seed:int=SEED) -> dict[str,Any]:
    """Positive MAE/RMSE differences mean B improves on A; positive rank/lift means B improves."""
    rng=np.random.default_rng(seed); series={name:[] for name in ("mae_improvement","rmse_improvement","spearman_increment","top_decile_lift_increment")}
    for _ in range(repeats):
        idx=rng.integers(0,len(y),len(y)); a=regression_metrics(y[idx],pred_a[idx]); b=regression_metrics(y[idx],pred_b[idx])
        series["mae_improvement"].append(a["mae"]-b["mae"]);series["rmse_improvement"].append(a["rmse"]-b["rmse"])
        series["spearman_increment"].append(b["spearman"]-a["spearman"]);series["top_decile_lift_increment"].append(b["top_decile_lift"]-a["top_decile_lift"])
    result={}
    for name,values in series.items():result[name]={"mean":float(np.mean(values)),"ci_low":float(np.quantile(values,.025)),"ci_high":float(np.quantile(values,.975)),"probability_positive":float(np.mean(np.asarray(values)>0))}
    return result


def classification_metrics(y:np.ndarray,probability:np.ndarray,threshold:float=.5) -> dict[str,float]:
    prediction=(probability>=threshold).astype(int); top=max(1,int(np.ceil(len(y)*.1))); top_idx=np.argsort(probability)[-top:]
    return {"pr_auc":float(average_precision_score(y,probability)),"roc_auc":float(roc_auc_score(y,probability)),"balanced_accuracy":float(balanced_accuracy_score(y,prediction)),"precision_top10pct":float(np.mean(y[top_idx])),"lift":float(np.mean(y[top_idx])/np.mean(y)),"recall":float(recall_score(y,prediction,zero_division=0))}
