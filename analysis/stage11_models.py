"""Controlled Stage 11 A/B/C baseline ablations with chronological evaluation."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, brier_score_loss, confusion_matrix,
    f1_score, matthews_corrcoef, mean_absolute_error, mean_squared_error,
    precision_score, recall_score, r2_score, roc_auc_score, average_precision_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler, label_binarize

from analysis.stage10_evaluator import correlation
from ml.stage11_dataset_builder import HORIZONS, VOL_WINDOWS

RANDOM_SEED = 20260718


def feature_sets(frame: pd.DataFrame) -> dict[str, list[str]]:
    market = sorted(column for column in frame if column.startswith(("pre_", "metadata_")) and pd.api.types.is_numeric_dtype(frame[column]))
    ai = sorted(column for column in frame if column.startswith("ai9_") and pd.api.types.is_numeric_dtype(frame[column]))
    forbidden = [column for column in [*market, *ai] if column.startswith(("target_", "future_"))]
    if forbidden:
        raise ValueError(f"Target leakage in features: {forbidden}")
    return {"A_market_only": market, "B_stage9_ai_only": ai, "C_market_plus_stage9_ai": sorted(set(market + ai))}


def classification_metrics(y_true: np.ndarray, y_pred: np.ndarray, probabilities: np.ndarray | None, classes: np.ndarray) -> dict[str, Any]:
    result = {
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "precision_macro": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "mcc": float(matthews_corrcoef(y_true, y_pred)),
        "confusion_matrix": json.dumps(confusion_matrix(y_true, y_pred, labels=classes).tolist()),
    }
    result["roc_auc"] = None; result["pr_auc"] = None; result["brier_score"] = None
    if probabilities is not None and len(classes) > 1:
        try:
            if len(classes) == 2:
                binary = (y_true == classes[1]).astype(int)
                result["roc_auc"] = float(roc_auc_score(binary, probabilities[:, 1]))
                result["pr_auc"] = float(average_precision_score(binary, probabilities[:, 1]))
                result["brier_score"] = float(brier_score_loss(binary, probabilities[:, 1]))
            else:
                binary = label_binarize(y_true, classes=classes)
                result["roc_auc"] = float(roc_auc_score(binary, probabilities, average="macro", multi_class="ovr"))
                result["pr_auc"] = float(average_precision_score(binary, probabilities, average="macro"))
                result["brier_score"] = float(np.mean(np.sum((probabilities - binary) ** 2, axis=1)))
        except ValueError:
            pass
    return result


def regression_metrics(y_true: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    count = max(1, int(len(y_true) * .10)); top = np.argsort(prediction)[-count:]
    overall = float(np.mean(y_true)); top_mean = float(np.mean(y_true[top]))
    return {
        "mae": float(mean_absolute_error(y_true, prediction)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, prediction))),
        "r2": float(r2_score(y_true, prediction)),
        "spearman": correlation(y_true, prediction, "spearman"),
        "directional_accuracy": float(np.mean(np.sign(y_true) == np.sign(prediction))),
        "top_decile_lift": top_mean / overall if overall else None,
    }


def _classification_models() -> dict[str, Any]:
    return {
        "logistic_regression": Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("model", LogisticRegression(max_iter=500, class_weight="balanced", random_state=RANDOM_SEED))]),
        "hist_gradient_boosting": Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", HistGradientBoostingClassifier(max_iter=100, learning_rate=.06, max_leaf_nodes=15, random_state=RANDOM_SEED, class_weight="balanced"))]),
    }


def _regression_models() -> dict[str, Any]:
    return {
        "ridge": Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("model", Ridge(alpha=10.0))]),
        "hist_gradient_boosting": Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", HistGradientBoostingRegressor(max_iter=100, learning_rate=.06, max_leaf_nodes=15, random_state=RANDOM_SEED))]),
    }


def target_specs() -> list[dict[str, str]]:
    specs=[]
    for horizon in HORIZONS:
        specs.append({"family":"abnormal_direction","target":f"target_abnormal_direction_{horizon}_band_025","task":"classification"})
        specs.append({"family":"strong_abnormal_move","target":f"target_strong_abnormal_{horizon}_100","task":"classification"})
        specs.append({"family":"absolute_abnormal_return","target":f"target_abs_abnormal_return_{horizon}","task":"regression"})
    for horizon in VOL_WINDOWS:
        specs.append({"family":"future_volatility","target":f"target_future_realized_vol_{horizon}","task":"regression"})
    return specs


def _fit_evaluate(train: pd.DataFrame, evaluation: pd.DataFrame, features: list[str], spec: dict[str, str], model_name: str, model: Any) -> tuple[dict[str, Any], Any]:
    clean_train = train.dropna(subset=[spec["target"]]); clean_eval = evaluation.dropna(subset=[spec["target"]])
    X_train, X_eval = clean_train[features], clean_eval[features]
    if spec["task"] == "classification":
        encoder=LabelEncoder(); y_train=encoder.fit_transform(clean_train[spec["target"]].astype(str)); y_eval=encoder.transform(clean_eval[spec["target"]].astype(str))
        model.fit(X_train,y_train); prediction=model.predict(X_eval); probabilities=model.predict_proba(X_eval) if hasattr(model,"predict_proba") else None
        metrics=classification_metrics(y_eval,prediction,probabilities,np.arange(len(encoder.classes_)))
        metrics["class_names"]=json.dumps(encoder.classes_.tolist())
    else:
        y_train=clean_train[spec["target"]].to_numpy(float); y_eval=clean_eval[spec["target"]].to_numpy(float)
        model.fit(X_train,y_train); prediction=model.predict(X_eval); metrics=regression_metrics(y_eval,prediction)
    return {"n_train":len(clean_train),"n_eval":len(clean_eval),**metrics},model


def _baseline_rows(frame: pd.DataFrame, specs: list[dict[str, str]]) -> list[dict[str, Any]]:
    train=frame[frame.metadata_split=="train"]; rows=[]; rng=np.random.default_rng(RANDOM_SEED)
    for spec in specs:
        for split in ["validation","test"]:
            evaluation=frame[frame.metadata_split==split].dropna(subset=[spec["target"]]); y=evaluation[spec["target"]]
            if spec["task"]=="classification":
                classes=np.sort(train[spec["target"]].dropna().astype(str).unique()); actual=y.astype(str).to_numpy()
                majority=train[spec["target"]].astype(str).mode().iat[0]
                predictions={"baseline_majority":np.full(len(actual),majority),"baseline_random":rng.choice(classes,len(actual)),}
                if spec["family"]=="abnormal_direction":
                    predictions["baseline_always_neutral"]=np.full(len(actual),"neutral")
                    horizon=spec["target"].split("direction_")[1].split("_band")[0]
                    predictions["baseline_btc_adjusted_momentum"]=np.where(evaluation[f"pre_eth_btc_relative_return_{horizon}"]>.25,"positive",np.where(evaluation[f"pre_eth_btc_relative_return_{horizon}"]<-.25,"negative","neutral"))
                    predictions["baseline_eth_momentum"]=np.where(evaluation[f"pre_eth_return_{horizon}"]>.25,"positive",np.where(evaluation[f"pre_eth_return_{horizon}"]<-.25,"negative","neutral"))
                for name,prediction in predictions.items():
                    result=classification_metrics(actual,np.asarray(prediction),None,classes)
                    rows.append({"feature_set":name,"model":"rule","target_family":spec["family"],"target":spec["target"],"task":spec["task"],"split":split,"n_train":len(train),"n_eval":len(evaluation),**result})
            else:
                actual=y.to_numpy(float)
                for name,prediction in {"baseline_zero":np.zeros(len(actual)),"baseline_train_mean":np.full(len(actual),float(train[spec["target"]].mean()))}.items():
                    rows.append({"feature_set":name,"model":"rule","target_family":spec["family"],"target":spec["target"],"task":spec["task"],"split":split,"n_train":len(train),"n_eval":len(evaluation),**regression_metrics(actual,prediction)})
    return rows


def run_ablation(frame: pd.DataFrame, reports_dir: Path) -> dict[str, Any]:
    sets=feature_sets(frame); specs=target_specs(); train=frame[frame.metadata_split=="train"]; rows=[]; importances=[]
    for feature_set,features in sets.items():
        for spec in specs:
            models=_classification_models() if spec["task"]=="classification" else _regression_models()
            for model_name,model in models.items():
                fitted=None
                for split in ["validation","test"]:
                    metrics,fitted=_fit_evaluate(train,frame[frame.metadata_split==split],features,spec,model_name,model)
                    rows.append({"feature_set":feature_set,"model":model_name,"target_family":spec["family"],"target":spec["target"],"task":spec["task"],"split":split,**metrics})
                if model_name in {"logistic_regression","ridge"} and fitted is not None:
                    coefficients=np.asarray(fitted.named_steps["model"].coef_)
                    values=np.mean(np.abs(coefficients),axis=0) if coefficients.ndim>1 else np.abs(coefficients)
                    for feature,value in zip(features,values):
                        importances.append({"feature_set":feature_set,"model":model_name,"target_family":spec["family"],"target":spec["target"],"feature":feature,"importance":float(value)})
    rows.extend(_baseline_rows(frame,specs))
    pd.DataFrame(rows).to_csv(reports_dir/"stage11_eth_ablation_metrics.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(importances).to_csv(reports_dir/"stage11_eth_feature_importance.csv",index=False,encoding="utf-8-sig")
    target_rows=[]
    for spec in specs:
        for split,group in frame.groupby("metadata_split"):
            values=group[spec["target"]].dropna()
            target_rows.append({"target_family":spec["family"],"target":spec["target"],"task":spec["task"],"split":split,"count":len(values),"mean":float(values.mean()) if spec["task"]=="regression" else None,"std":float(values.std()) if spec["task"]=="regression" else None,"distribution":json.dumps(values.astype(str).value_counts().to_dict()) if spec["task"]=="classification" else None})
    pd.DataFrame(target_rows).to_csv(reports_dir/"stage11_eth_target_metrics.csv",index=False,encoding="utf-8-sig")
    return {"rows":len(rows),"feature_sets":{key:len(value) for key,value in sets.items()},"target_specs":len(specs)}


def run_walkforward(frame: pd.DataFrame, splits: dict[str, Any], reports_dir: Path) -> dict[str, Any]:
    sets=feature_sets(frame); specs=target_specs(); rows=[]
    indexed=frame.set_index("metadata_news_id",drop=False)
    for fold in splits["walk_forward_folds"]:
        train=indexed.loc[indexed.index.intersection(fold["train_news_ids"])]
        evaluation=indexed.loc[indexed.index.intersection(fold["test_news_ids"])]
        for feature_set,features in sets.items():
            for spec in specs:
                model_name="logistic_regression" if spec["task"]=="classification" else "ridge"
                model=_classification_models()[model_name] if spec["task"]=="classification" else _regression_models()[model_name]
                metrics,_=_fit_evaluate(train,evaluation,features,spec,model_name,model)
                rows.append({"fold":fold["fold"],"feature_set":feature_set,"model":model_name,"target_family":spec["family"],"target":spec["target"],"task":spec["task"],**metrics})
    pd.DataFrame(rows).to_csv(reports_dir/"stage11_eth_walkforward_metrics.csv",index=False,encoding="utf-8-sig")
    return {"rows":len(rows),"folds":len(splits["walk_forward_folds"])}
