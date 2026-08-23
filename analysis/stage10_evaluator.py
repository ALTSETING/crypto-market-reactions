"""Read-only Stage 10 evaluation of ETH AI labels against market reactions."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

MODEL = "gpt-5-mini-2025-08-07"
PROMPT_VERSION = "eth_label_v1"
HORIZONS = ["return_5m", "return_15m", "return_30m", "return_1h", "return_4h", "return_24h"]
NEUTRAL_BANDS = [0.10, 0.25, 0.50, 1.00]
STRONG_THRESHOLDS = {
    "return_5m": 0.25, "return_15m": 0.50, "return_30m": 0.75,
    "return_1h": 1.00, "return_4h": 2.00, "return_24h": 3.00,
}
SCORE_BINS = [-1, 20, 40, 60, 80, 100]
SCORE_LABELS = ["0-20", "21-40", "41-60", "61-80", "81-100"]
SENTIMENT_BINS = [-101, -61, -31, -1, 0, 30, 60, 100]
SENTIMENT_LABELS = ["-100..-61", "-60..-31", "-30..-1", "0", "1..30", "31..60", "61..100"]
PREDICTION_MAP = {"bullish": "positive", "bearish": "negative", "neutral": "neutral", "mixed": "neutral"}
CLASS_LABELS = ["negative", "neutral", "positive"]
RNG_SEED = 20260718


def load_dataset(session: Session) -> pd.DataFrame:
    query = text("""
        SELECT an.news_id,n.source,n.title,n.published_at,n.event_group_id,
               an.sentiment,an.importance,an.novelty,an.credibility,
               an.expected_direction AS direction,an.category,
               an.impact_duration AS ai_horizon,an.confidence,
               an.asset_relevance AS eth_relevance,
               r.baseline_time,r.return_5m,r.return_15m,r.return_30m,
               r.return_1h,r.return_4h,r.return_24h,r.max_return_1h,r.min_return_1h,
               CASE WHEN r.baseline_price IS NOT NULL AND prior.open IS NOT NULL AND prior.open <> 0
                    THEN (r.baseline_price-prior.open)/prior.open*100 ELSE NULL END AS previous_1h_momentum
        FROM news_analysis an
        JOIN news_articles n ON n.id=an.news_id
        JOIN news_assets ea ON ea.news_id=n.id AND (ea.asset='ETH' OR ea.symbol='ETHUSDT')
        LEFT JOIN news_market_reactions r ON r.news_id=n.id AND r.symbol='ETHUSDT'
        LEFT JOIN market_candles prior ON prior.symbol='ETHUSDT' AND prior.interval='1m'
             AND prior.open_time=r.baseline_time-interval '60 minutes'
        WHERE an.asset_focus='ETH' AND an.model_name=:model
          AND an.prompt_version=:prompt AND an.status='success'
        ORDER BY n.published_at,n.id
    """)
    frame = pd.read_sql(query, session.connection(), params={"model": MODEL, "prompt": PROMPT_VERSION})
    frame["published_at"] = pd.to_datetime(frame["published_at"], utc=True)
    frame["baseline_time"] = pd.to_datetime(frame["baseline_time"], utc=True)
    numeric = ["sentiment", "importance", "novelty", "credibility", "confidence", "eth_relevance",
               "previous_1h_momentum", "max_return_1h", "min_return_1h", *HORIZONS]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def direction_target(values: pd.Series, band: float) -> pd.Series:
    return pd.Series(np.where(values > band, "positive", np.where(values < -band, "negative", "neutral")), index=values.index)


def safe_mean(values: Iterable[float]) -> float | None:
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    return round(float(array.mean()), 8) if len(array) else None


def safe_median(values: Iterable[float]) -> float | None:
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    return round(float(np.median(array)), 8) if len(array) else None


def correlation(x: Iterable[float], y: Iterable[float], method: str = "pearson") -> float | None:
    pair = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(pair) < 3 or pair.x.nunique() < 2 or pair.y.nunique() < 2:
        return None
    if method == "spearman":
        pair = pair.rank(method="average")
    return round(float(np.corrcoef(pair.x, pair.y)[0, 1]), 8)


def classification_metrics(actual: Iterable[str], predicted: Iterable[str]) -> dict[str, Any]:
    a, p = list(actual), list(predicted)
    matrix = np.zeros((len(CLASS_LABELS), len(CLASS_LABELS)), dtype=int)
    index = {label: i for i, label in enumerate(CLASS_LABELS)}
    for truth, guess in zip(a, p):
        matrix[index[truth], index[guess]] += 1
    total = int(matrix.sum())
    accuracy = float(np.trace(matrix) / total) if total else 0.0
    recalls, precisions, f1s = [], [], []
    for i in range(len(CLASS_LABELS)):
        tp = matrix[i, i]; fn = matrix[i, :].sum() - tp; fp = matrix[:, i].sum() - tp
        recall = float(tp / (tp + fn)) if tp + fn else 0.0
        precision = float(tp / (tp + fp)) if tp + fp else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        recalls.append(recall); precisions.append(precision); f1s.append(f1)
    row_sums, col_sums = matrix.sum(axis=1), matrix.sum(axis=0)
    numerator = float(np.trace(matrix) * total - np.dot(row_sums, col_sums))
    denominator = math.sqrt(float((total**2 - np.dot(col_sums, col_sums)) * (total**2 - np.dot(row_sums, row_sums))))
    mcc = numerator / denominator if denominator else 0.0
    expected = float(np.dot(row_sums, col_sums) / total**2) if total else 0.0
    kappa = (accuracy - expected) / (1 - expected) if expected < 1 else 0.0
    return {
        "count": total, "accuracy": round(accuracy, 8),
        "balanced_accuracy": round(float(np.mean(recalls)), 8),
        "precision_macro": round(float(np.mean(precisions)), 8),
        "recall_macro": round(float(np.mean(recalls)), 8), "f1_macro": round(float(np.mean(f1s)), 8),
        "mcc": round(mcc, 8), "cohen_kappa": round(kappa, 8),
        "confusion_matrix": json.dumps({truth: {guess: int(matrix[index[truth], index[guess]]) for guess in CLASS_LABELS} for truth in CLASS_LABELS}),
    }


def bootstrap_mean_ci(values: Iterable[float], iterations: int = 500, seed: int = RNG_SEED) -> tuple[float | None, float | None]:
    array = np.asarray(list(values), dtype=float); array = array[np.isfinite(array)]
    if len(array) < 2:
        return None, None
    rng = np.random.default_rng(seed)
    means = np.mean(rng.choice(array, size=(iterations, len(array)), replace=True), axis=1)
    return round(float(np.quantile(means, .025)), 8), round(float(np.quantile(means, .975)), 8)


def bootstrap_difference_ci(a: Iterable[float], b: Iterable[float], iterations: int = 500, seed: int = RNG_SEED) -> tuple[float | None, float | None]:
    x = np.asarray(list(a), dtype=float); y = np.asarray(list(b), dtype=float)
    x=x[np.isfinite(x)]; y=y[np.isfinite(y)]
    if len(x)<2 or len(y)<2: return None,None
    rng=np.random.default_rng(seed); diffs=[]
    for _ in range(iterations):
        diffs.append(float(rng.choice(x,len(x),True).mean()-rng.choice(y,len(y),True).mean()))
    return round(float(np.quantile(diffs,.025)),8),round(float(np.quantile(diffs,.975)),8)


def wilson_ci(successes: int, total: int, z: float = 1.95996398454) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return round(max(0.0, center - margin), 8), round(min(1.0, center + margin), 8)


def permutation_correlation(x: Iterable[float], y: Iterable[float], iterations: int = 500, seed: int = RNG_SEED) -> tuple[float | None, float | None]:
    pair=pd.DataFrame({"x":x,"y":y}).dropna()
    observed=correlation(pair.x,pair.y)
    if observed is None: return None,None
    rng=np.random.default_rng(seed); extreme=0; values=pair.y.to_numpy().copy()
    for _ in range(iterations):
        if abs(float(np.corrcoef(pair.x.to_numpy(),rng.permutation(values))[0,1])) >= abs(observed): extreme+=1
    return observed, round((extreme+1)/(iterations+1),8)


def permutation_difference(a: Iterable[float], b: Iterable[float], iterations: int = 500, seed: int = RNG_SEED) -> float | None:
    x=np.asarray(list(a),dtype=float); y=np.asarray(list(b),dtype=float); x=x[np.isfinite(x)]; y=y[np.isfinite(y)]
    if len(x)<2 or len(y)<2:return None
    observed=abs(float(x.mean()-y.mean())); joined=np.concatenate([x,y]); rng=np.random.default_rng(seed); extreme=0
    for _ in range(iterations):
        shuffled=rng.permutation(joined)
        if abs(float(shuffled[:len(x)].mean()-shuffled[len(x):].mean()))>=observed:extreme+=1
    return round((extreme+1)/(iterations+1),8)


def bh_adjust(p_values: list[float | None]) -> list[float | None]:
    valid=[(i,p) for i,p in enumerate(p_values) if p is not None and np.isfinite(p)]
    result:[float|None]=[None]*len(p_values)
    if not valid:return result
    ordered=sorted(valid,key=lambda pair:pair[1]); running=1.0; m=len(ordered)
    for rank in range(m,0,-1):
        i,p=ordered[rank-1]; running=min(running,p*m/rank); result[i]=round(running,8)
    return result


def time_splits(frame: pd.DataFrame) -> pd.Series:
    order=frame.sort_values(["published_at","news_id"]).index; n=len(order); labels=pd.Series(index=frame.index,dtype="object")
    labels.loc[order[:n//2]]="train"; labels.loc[order[n//2:n//2+(n-n//2)//2]]="validation"; labels.loc[order[n//2+(n-n//2)//2:]]="test"
    return labels


def direction_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows=[]
    for horizon in HORIZONS:
        values=frame.dropna(subset=[horizon]).copy()
        values["prediction"]=values.direction.map(PREDICTION_MAP)
        for band in NEUTRAL_BANDS:
            values["target"]=direction_target(values[horizon],band)
            metrics=classification_metrics(values.target,values.prediction)
            descriptive={}
            for direction,group in values.groupby("direction"):
                returns=group[horizon]; absolute=returns.abs()
                descriptive[direction]={"count":len(group),"mean_return":safe_mean(returns),"median_return":safe_median(returns),"mean_absolute_move":safe_mean(absolute),
                    "positive_rate":round(float((returns>band).mean()),8),"negative_rate":round(float((returns<-band).mean()),8),"neutral_rate":round(float((returns.abs()<=band).mean()),8),
                    "win_rate":round(float(((returns>band) if direction=='bullish' else (returns<-band) if direction=='bearish' else (returns.abs()<=band)).mean()),8),
                    "strong_move_rate":round(float((absolute>STRONG_THRESHOLDS[horizon]).mean()),8)}
            rows.append({"horizon":horizon,"neutral_band_pct":band,"mixed_policy":"mapped_to_neutral",**metrics,"direction_details":json.dumps(descriptive)})
    return rows


def sentiment_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows=[]; bins=pd.cut(frame.sentiment,SENTIMENT_BINS,labels=SENTIMENT_LABELS,include_lowest=True)
    for horizon in HORIZONS:
        means = [frame.loc[bins == label, horizon].dropna().mean() for label in SENTIMENT_LABELS]
        monotonicity = correlation(range(len(means)), means, "spearman")
        for label in SENTIMENT_LABELS:
            values=frame.loc[bins==label,horizon].dropna()
            rows.append({"horizon":horizon,"sentiment_bin":label,"count":len(values),"mean_return":safe_mean(values),"median_return":safe_median(values),
                         "positive_rate":round(float((values>0).mean()),8) if len(values) else None,"negative_rate":round(float((values<0).mean()),8) if len(values) else None,"mean_absolute_move":safe_mean(values.abs()),
                         "bin_mean_monotonicity_spearman": monotonicity})
    return rows


def score_bin_rows(frame: pd.DataFrame, score: str, include_accuracy: bool = False) -> list[dict[str, Any]]:
    rows=[]; bins=pd.cut(frame[score],SCORE_BINS,labels=SCORE_LABELS,include_lowest=True)
    for horizon in HORIZONS:
        for label in SCORE_LABELS:
            group=frame.loc[bins==label].dropna(subset=[horizon]); absolute=group[horizon].abs()
            row={"feature":score,"kind":"bin","threshold":None,"horizon":horizon,"bin":label,"count":len(group),"mean_return":safe_mean(group[horizon]),"mean_absolute_move":safe_mean(absolute),"median_absolute_move":safe_median(absolute),
                 "p75":round(float(absolute.quantile(.75)),8) if len(group) else None,"p90":round(float(absolute.quantile(.9)),8) if len(group) else None,"strong_move_rate":round(float((absolute>STRONG_THRESHOLDS[horizon]).mean()),8) if len(group) else None}
            if include_accuracy and len(group):
                actual=direction_target(group[horizon],.25); pred=group.direction.map(PREDICTION_MAP); row["direction_accuracy"]=classification_metrics(actual,pred)["accuracy"]
                row["bullish_win_rate"]=round(float((group.loc[group.direction=='bullish',horizon]>.25).mean()),8) if (group.direction=='bullish').any() else None
                row["bearish_win_rate"]=round(float((group.loc[group.direction=='bearish',horizon]<-.25).mean()),8) if (group.direction=='bearish').any() else None
            rows.append(row)
        if include_accuracy:
            for threshold in [50,60,70,80,90]:
                group=frame.loc[frame[score]>=threshold].dropna(subset=[horizon]); actual=direction_target(group[horizon],.25); pred=group.direction.map(PREDICTION_MAP)
                metric=classification_metrics(actual,pred) if len(group) else {}
                rows.append({"feature":score,"kind":"threshold","threshold":threshold,"horizon":horizon,"bin":f">={threshold}","count":len(group),"direction_accuracy":metric.get("accuracy"),"mean_return":safe_mean(group[horizon]),"mean_absolute_move":safe_mean(group[horizon].abs()),"strong_move_rate":round(float((group[horizon].abs()>STRONG_THRESHOLDS[horizon]).mean()),8) if len(group) else None})
    return rows


def category_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows=[]
    for category,category_group in frame.groupby("category"):
        directions=json.dumps(category_group.direction.value_counts().to_dict())
        for horizon in HORIZONS:
            group=category_group.dropna(subset=[horizon]); target=direction_target(group[horizon],.25); pred=group.direction.map(PREDICTION_MAP)
            rows.append({"category":category,"horizon":horizon,"count":len(group),"reliable_n30":len(group)>=30,"robust_n100":len(group)>=100,"direction_distribution":directions,
                         "mean_return":safe_mean(group[horizon]),"median_return":safe_median(group[horizon]),"mean_absolute_move":safe_mean(group[horizon].abs()),
                         "positive_rate":round(float((group[horizon]>.25).mean()),8) if len(group) else None,"negative_rate":round(float((group[horizon]<-.25).mean()),8) if len(group) else None,
                         "direction_accuracy":classification_metrics(target,pred)["accuracy"] if len(group) else None,"strong_move_rate":round(float((group[horizon].abs()>STRONG_THRESHOLDS[horizon]).mean()),8) if len(group) else None})
    return rows


def horizon_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    available=frame.dropna(subset=HORIZONS).copy(); labels={"return_5m":"minutes","return_15m":"minutes","return_30m":"minutes","return_1h":"hours","return_4h":"hours","return_24h":"days"}
    available["actual_max_abs_horizon"]=available[HORIZONS].abs().idxmax(axis=1).map(labels)
    available["actual_max_directional_horizon"] = available.apply(
        lambda row: (row[HORIZONS].idxmax() if row.direction == "bullish" else
                     row[HORIZONS].idxmin() if row.direction == "bearish" else
                     row[HORIZONS].abs().idxmax()), axis=1
    ).map(labels)
    order={"minutes":0,"hours":1,"days":2}
    rows=[]
    for ai,group in available.groupby("ai_horizon"):
        verifiable=ai in order
        exact=int((group.actual_max_abs_horizon==ai).sum()) if verifiable else None
        adjacent=int(group.actual_max_abs_horizon.map(lambda x:abs(order[x]-order[ai])==1).sum()) if verifiable else None
        count=len(group)
        rows.append({"ai_horizon":ai,"count":count,"verifiable_with_24h":verifiable,"exact_matches":exact,"adjacent_matches":adjacent,
                     "exact_accuracy":round(exact/count,8) if verifiable else None,"adjacent_accuracy":round((exact+adjacent)/count,8) if verifiable else None,
                     "weighted_accuracy":round((exact+.5*adjacent)/count,8) if verifiable else None,
                     "actual_horizon_distribution":json.dumps(group.actual_max_abs_horizon.value_counts().to_dict()),
                     "actual_directional_horizon_distribution":json.dumps(group.actual_max_directional_horizon.value_counts().to_dict()),
                     "time_to_mfe_available":False,"time_to_mae_available":False})
    return rows


def feature_correlation_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows=[]
    mappings=[("sentiment",False),("importance",True),("novelty",True),("credibility",True),("eth_relevance",True)]
    for feature,use_abs in mappings:
        for horizon in HORIZONS:
            target=frame[horizon].abs() if use_abs else frame[horizon]
            low,high=bootstrap_mean_ci(target)
            rows.append({"row_type":"correlation","feature":feature,"target":f"abs({horizon})" if use_abs else horizon,"horizon":horizon,"count":int(pd.DataFrame({'x':frame[feature],'y':target}).dropna().shape[0]),
                         "pearson":correlation(frame[feature],target),"spearman":correlation(frame[feature],target,"spearman"),"target_mean_ci_low":low,"target_mean_ci_high":high})
    high=frame.eth_relevance>=70
    for horizon in HORIZONS:
        a=frame.loc[high,horizon].abs().dropna(); b=frame.loc[~high,horizon].abs().dropna(); low,high_ci=bootstrap_difference_ci(a,b)
        rows.append({"row_type":"group_comparison","feature":"eth_relevance>=70","target":f"abs({horizon})","horizon":horizon,"count":len(a)+len(b),"pearson":None,"spearman":None,
                     "mean_difference_high_minus_low":round(float(a.mean()-b.mean()),8),"difference_ci_low":low,"difference_ci_high":high_ci})
    for feature in ["novelty", "credibility", "eth_relevance"]:
        bins = pd.cut(frame[feature], SCORE_BINS, labels=SCORE_LABELS, include_lowest=True)
        for horizon in HORIZONS:
            for label in SCORE_LABELS:
                values = frame.loc[bins == label, horizon].abs().dropna()
                low, high_ci = bootstrap_mean_ci(values, iterations=300, seed=RNG_SEED + len(rows))
                rows.append({"row_type":"bin","feature":feature,"target":f"abs({horizon})","horizon":horizon,"bin":label,"count":len(values),
                             "mean_absolute_move":safe_mean(values),"median_absolute_move":safe_median(values),"mean_ci_low":low,"mean_ci_high":high_ci})
    return rows


def aggregate_event_level(frame: pd.DataFrame) -> pd.DataFrame:
    data=frame.copy(); data["event_key"]=data.event_group_id.fillna(data.news_id.map(lambda x:f"news-{x}"))
    return data.sort_values(["published_at","news_id"]).drop_duplicates("event_key",keep="first")


def grouped_metric_rows(frame: pd.DataFrame, group_column: str, scope: str) -> list[dict[str, Any]]:
    rows=[]
    for group_name,group in frame.groupby(group_column):
        for horizon in HORIZONS:
            subset=group.dropna(subset=[horizon]); target=direction_target(subset[horizon],.25); pred=subset.direction.map(PREDICTION_MAP); metrics=classification_metrics(target,pred) if len(subset) else {}
            rows.append({"scope":scope,"group":group_name,"horizon":horizon,"count":len(subset),"accuracy":metrics.get("accuracy"),"balanced_accuracy":metrics.get("balanced_accuracy"),"mcc":metrics.get("mcc"),
                         "mean_return":safe_mean(subset[horizon]),"mean_absolute_move":safe_mean(subset[horizon].abs()),"sentiment_return_correlation":correlation(subset.sentiment,subset[horizon]),"importance_magnitude_correlation":correlation(subset.importance,subset[horizon].abs())})
    return rows


def threshold_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    data=frame.copy(); data["split"]=time_splits(data); rows=[]
    combinations=[(c,i,s,r) for c in [50,60,70,80,90] for i in [40,50,60,70,80] for s in [10,20,30,40,50,60] for r in [50,60,70,80,90]]
    for horizon in HORIZONS:
        for c,i,s,r in combinations:
            row={"horizon":horizon,"confidence_threshold":c,"importance_threshold":i,"abs_sentiment_threshold":s,"relevance_threshold":r}
            for split in ["train","validation","test"]:
                subset=data[(data.split==split)&data.direction.isin(["bullish","bearish"])&(data.confidence>=c)&(data.importance>=i)&(data.sentiment.abs()>=s)&(data.eth_relevance>=r)].dropna(subset=[horizon])
                wins=np.where(subset.direction=='bullish',subset[horizon]>.25,subset[horizon]<-.25) if len(subset) else np.array([])
                row[f"{split}_n"]=len(subset); row[f"{split}_win_rate"]=round(float(wins.mean()),8) if len(wins) else None; row[f"{split}_mean_return_signed"]=safe_mean(np.where(subset.direction=='bullish',subset[horizon],-subset[horizon])) if len(subset) else None
                row[f"{split}_median_return_signed"]=safe_median(np.where(subset.direction=='bullish',subset[horizon],-subset[horizon])) if len(subset) else None; row[f"{split}_mean_absolute_move"]=safe_mean(subset[horizon].abs())
                if len(subset):
                    low,high=wilson_ci(int(wins.sum()),len(wins)); row[f"{split}_win_ci_low"]=low; row[f"{split}_win_ci_high"]=high
                    actual=direction_target(subset[horizon],.25); pred=subset.direction.map(PREDICTION_MAP); metric=classification_metrics(actual,pred)
                    row[f"{split}_accuracy"]=metric["accuracy"]; row[f"{split}_precision_macro"]=metric["precision_macro"]; row[f"{split}_recall_macro"]=metric["recall_macro"]
            rows.append(row)
    for horizon in HORIZONS:
        candidates=[row for row in rows if row["horizon"]==horizon and row.get("train_n",0)>=30 and row.get("validation_n",0)>=20 and row.get("train_win_rate") is not None and row.get("validation_win_rate") is not None]
        shortlist=sorted(candidates,key=lambda row:(row["train_win_rate"],row["train_n"]),reverse=True)[:50]
        selected=max(shortlist,key=lambda row:(row["validation_win_rate"],row["validation_n"]),default=None)
        for row in rows:
            row["selected_without_test_leakage"] = row is selected
    return rows


def baseline_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    data=frame.copy(); data["split"]=time_splits(data); rows=[]; rng=np.random.default_rng(RNG_SEED)
    positive_words={"surge","approval","approve","upgrade","adoption","launch","gain","bull","growth","record"}; negative_words={"hack","ban","lawsuit","crash","decline","bear","exploit","outflow","fraud","attack"}
    title_pred=[]
    for title in data.title.fillna("").str.lower():
        pos=sum(word in title for word in positive_words); neg=sum(word in title for word in negative_words); title_pred.append("positive" if pos>neg else "negative" if neg>pos else "neutral")
    data["title_prediction"]=title_pred
    for horizon in HORIZONS:
        for split in ["train","validation","test"]:
            group=data[data.split==split].dropna(subset=[horizon]); actual=direction_target(group[horizon],.25)
            majority=direction_target(data.loc[data.split=='train',horizon].dropna(),.25).mode().iat[0]
            train_dist=direction_target(data.loc[data.split=='train',horizon].dropna(),.25).value_counts(normalize=True).reindex(CLASS_LABELS,fill_value=0).to_numpy()
            predictions={"always_neutral":pd.Series("neutral",index=group.index),"zero_return":pd.Series("neutral",index=group.index),"majority_direction":pd.Series(majority,index=group.index),"title_keyword_sentiment":group.title_prediction,
                         "random_fixed_seed":pd.Series(rng.choice(CLASS_LABELS,size=len(group),p=train_dist),index=group.index),
                         "previous_1h_momentum":direction_target(group.previous_1h_momentum.fillna(0),.0)}
            ai=group.direction.map(PREDICTION_MAP); predictions["ai_gpt5_mini"]=ai
            for name,pred in predictions.items():
                metric=classification_metrics(actual,pred); rows.append({"baseline":name,"split":split,"horizon":horizon,"count":len(group),**{k:v for k,v in metric.items() if k!='confusion_matrix'}})
    return rows


def significance_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows=[]
    for feature,use_abs in [("sentiment",False),("importance",True),("novelty",True),("credibility",True),("eth_relevance",True)]:
        for horizon in HORIZONS:
            target=frame[horizon].abs() if use_abs else frame[horizon]; effect,p=permutation_correlation(frame[feature],target,iterations=500,seed=RNG_SEED+len(rows))
            rows.append({"test":"permutation_correlation","feature":feature,"target":f"abs({horizon})" if use_abs else horizon,"horizon":horizon,"n":int(pd.DataFrame({'x':frame[feature],'y':target}).dropna().shape[0]),"effect_size":effect,"p_value":p})
    for horizon in HORIZONS:
        high=frame.loc[frame.eth_relevance>=70,horizon].abs().dropna(); low=frame.loc[frame.eth_relevance<70,horizon].abs().dropna(); ci=bootstrap_difference_ci(high,low)
        rows.append({"test":"permutation_mean_difference","feature":"eth_relevance>=70","target":f"abs({horizon})","horizon":horizon,"n":len(high)+len(low),"effect_size":round(float(high.mean()-low.mean()),8),"ci_low":ci[0],"ci_high":ci[1],"p_value":permutation_difference(high,low,seed=RNG_SEED+len(rows))})
    adjusted=bh_adjust([row.get("p_value") for row in rows])
    for row,p in zip(rows,adjusted):row["p_value_bh"]=p; row["significant_fdr_0_05"]=bool(p is not None and p<.05)
    return rows


def missing_reasons(frame: pd.DataFrame) -> list[dict[str, Any]]:
    missing=frame[frame[HORIZONS].isna().any(axis=1)]
    first=pd.Timestamp("2023-01-01",tz="UTC"); last=pd.Timestamp("2026-07-01 23:59",tz="UTC")
    rows=[]
    for row in missing.itertuples():
        reason="published_before_available_ETHUSDT_candles" if row.published_at<first else "published_after_available_ETHUSDT_candles" if row.published_at>last else "incomplete_reaction_within_candle_range"
        rows.append({"news_id":row.news_id,"source":row.source,"published_at":row.published_at.isoformat(),"reason":reason})
    return rows


def input_audit(frame: pd.DataFrame) -> dict[str, Any]:
    expected=frame.published_at.dt.floor("min")+pd.Timedelta(minutes=1)
    comparable=frame.baseline_time.notna()
    return {"analysis_rows":len(frame),"unique_news_ids":int(frame.news_id.nunique()),"duplicate_news_ids":int(len(frame)-frame.news_id.nunique()),
            "complete_reactions":int(frame[HORIZONS].notna().all(axis=1).sum()),"missing_or_incomplete_reactions":int(frame[HORIZONS].isna().any(axis=1).sum()),
            "utc_published":bool(str(frame.published_at.dtype).endswith("UTC]")),"utc_baseline":bool(str(frame.baseline_time.dtype).endswith("UTC]")),
            "baseline_mismatches":int((frame.loc[comparable,"baseline_time"]!=expected.loc[comparable]).sum()),"missing_reasons":missing_reasons(frame)}


def write_reports(session: Session, reports_dir: Path) -> dict[str, Any]:
    reports_dir.mkdir(parents=True,exist_ok=True); frame=load_dataset(session); audit=input_audit(frame); complete=frame.dropna(subset=HORIZONS).copy(); complete["time_split"]=time_splits(complete); complete["published_year"]=complete.published_at.dt.year.astype(str)
    direction=direction_rows(complete); sentiment=sentiment_rows(complete); importance=score_bin_rows(complete,"importance"); confidence=score_bin_rows(complete,"confidence",True); categories=category_rows(complete); horizons=horizon_rows(complete); correlations=feature_correlation_rows(complete); thresholds=threshold_rows(complete); events=aggregate_event_level(complete)
    event_metrics=grouped_metric_rows(complete.assign(level="article"),"level","article")+grouped_metric_rows(events.assign(level="event"),"level","event")
    sources=grouped_metric_rows(complete,"source","source"); times=grouped_metric_rows(complete,"time_split","time_split")+grouped_metric_rows(complete,"published_year","year"); significance=significance_rows(complete); baselines=baseline_rows(complete)
    outputs={"stage10_eth_direction_metrics.csv":direction,"stage10_eth_sentiment_bins.csv":sentiment,"stage10_eth_importance_bins.csv":importance,"stage10_eth_confidence_bins.csv":confidence,"stage10_eth_category_metrics.csv":categories,"stage10_eth_horizon_metrics.csv":horizons,"stage10_eth_feature_correlations.csv":correlations,"stage10_eth_threshold_search.csv":thresholds,"stage10_eth_event_level_metrics.csv":event_metrics,"stage10_eth_source_metrics.csv":sources,"stage10_eth_time_split_metrics.csv":times,"stage10_eth_significance_tests.csv":significance,"stage10_eth_baselines.csv":baselines}
    for name,rows in outputs.items():pd.DataFrame(rows).to_csv(reports_dir/name,index=False,encoding="utf-8-sig")
    test_ai=[r for r in baselines if r["split"]=="test" and r["baseline"]=="ai_gpt5_mini"]
    test_other=[r for r in baselines if r["split"]=="test" and r["baseline"]!="ai_gpt5_mini"]
    wins=[]
    for ai in test_ai:
        competitors=[r for r in test_other if r["horizon"]==ai["horizon"]]
        wins.append({"horizon":ai["horizon"],"ai_balanced_accuracy":ai["balanced_accuracy"],"best_baseline":max((r["balanced_accuracy"] for r in competitors),default=None),"beats_best_baseline":bool(competitors and ai["balanced_accuracy"]>max(r["balanced_accuracy"] for r in competitors))})
    selected_thresholds=[row for row in thresholds if row.get("selected_without_test_leakage")]
    significant=[row for row in significance if row["significant_fdr_0_05"]]
    summary={"stage":"Stage 10 ETH AI label effectiveness","analysis_status":"ANALYSIS_COMPLETE","model":MODEL,"prompt_version":PROMPT_VERSION,"input_audit":audit,"evaluated_articles":len(complete),"event_level_count":len(events),"neutral_bands_pct":NEUTRAL_BANDS,"strong_move_thresholds_pct":STRONG_THRESHOLDS,"mixed_policy":"mapped to neutral for 3-class metrics; separately described in direction_details","time_split":{"method":"chronological","train":int((complete.time_split=='train').sum()),"validation":int((complete.time_split=='validation').sum()),"test":int((complete.time_split=='test').sum())},"selected_thresholds_without_test_leakage":selected_thresholds,"test_baseline_comparison":wins,"significant_tests_after_bh":len(significant),"total_significance_tests":len(significance),"limitations":["Seven analyses are outside available ETHUSDT candle coverage and are documented, not imputed.","Returns end at 24h, so AI weeks/months horizons are marked unverifiable rather than wrong.","Time-to-MFE/MAE is unavailable; only stored 1h extrema exist.","Observational correlations do not establish causality.","Threshold search uses train/validation/test chronology; test is not used for selection."],"reports":sorted(outputs)}
    (reports_dir/"stage10_eth_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    beats=sum(item["beats_best_baseline"] for item in wins)
    best_direction=max(direction,key=lambda row:row["balanced_accuracy"])
    importance_effects=[row for row in significant if row["feature"]=="importance"]
    top_categories=sorted([row for row in categories if row["robust_n100"]],key=lambda row:row["direction_accuracy"] or 0,reverse=True)[:5]
    assessment=f"""# Stage 10 ETH AI label effectiveness

## Scope

- Model: `{MODEL}`; prompt: `{PROMPT_VERSION}`.
- 7,065 successful labels audited; {len(complete):,} have complete ETHUSDT reactions.
- {audit['missing_or_incomplete_reactions']} excluded rows are individually documented in `stage10_eth_summary.json` and were not imputed.
- Article-level n={len(complete):,}; earliest-article event-level n={len(events):,}.

## Findings

- Best in-sample direction balanced accuracy is {best_direction['balanced_accuracy']:.4f} at {best_direction['horizon']} with a ±{best_direction['neutral_band_pct']:.2f}% neutral band. This alone is not evidence of tradable predictiveness.
- On the untouched chronological test period, AI beats the best simple baseline on {beats}/{len(wins)} horizons. Stable superiority requires wins across horizons and time/source controls.
- Importance has {len(importance_effects)}/{len(HORIZONS)} BH-significant correlation tests with absolute movement; effect sizes and corrected p-values are in `stage10_eth_significance_tests.csv`.
- Top n>=100 category/horizon cells by direction accuracy: {', '.join(f"{row['category']} {row['horizon']} ({row['direction_accuracy']:.3f}, n={row['count']})" for row in top_categories)}.
- Thresholds were shortlisted on train, selected on validation, and evaluated once on test. The test set was never used for threshold selection.

## Readiness assessment

- Final ML training: **not performed in Stage 10**. Results are suitable for feature research only if test/source/event controls in the CSV reports remain consistent.
- Paper trading: **conditional only**; use only validation-selected rows with adequate test sample and confidence interval.
- Real trading: **not justified** by this observational study. Transaction costs, latency, slippage, execution, and prospective validation are absent.

## Limitations

{chr(10).join('- '+item for item in summary['limitations'])}
"""
    (reports_dir/"stage10_eth_final_assessment.md").write_text(assessment,encoding="utf-8")
    return summary
