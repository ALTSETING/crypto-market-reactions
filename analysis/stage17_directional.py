"""Pure helpers for honest Stage 17 directional evaluation."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score


def directional_target(returns:pd.Series,neutral_threshold:float)->pd.Series:
    values=pd.to_numeric(returns,errors="coerce")
    return pd.Series(np.select([values>neutral_threshold,values<-neutral_threshold],["UP","DOWN"],default="NEUTRAL"),index=returns.index)


def predictions_from_probabilities(probabilities:np.ndarray,classes:list[str],confidence_threshold:float)->tuple[np.ndarray,np.ndarray]:
    up=probabilities[:,classes.index("UP")];down=probabilities[:,classes.index("DOWN")]
    confidence=np.maximum(up,down);direction=np.where(up>=down,"UP","DOWN").astype(object)
    direction[confidence<confidence_threshold]="NO_SIGNAL"
    return direction,confidence


def wilson_interval(correct:int,n:int,z:float=1.959963984540054)->tuple[float|None,float|None]:
    if n<=0:return None,None
    p=correct/n;den=1+z*z/n;center=(p+z*z/(2*n))/den
    margin=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return center-margin,center+margin


def cluster_accuracy_ci(rows:pd.DataFrame,seed:int=17,reps:int=1000)->tuple[float|None,float|None]:
    signals=rows[rows.predicted_direction.isin(["UP","DOWN"])].copy()
    if signals.event_id.nunique()<2:return None,None
    grouped=signals.assign(correct=signals.predicted_direction.eq(signals.actual_direction).astype(int)).groupby("event_id").correct.agg(["sum","count"])
    rng=np.random.default_rng(seed);draw=rng.integers(0,len(grouped),size=(reps,len(grouped)))
    accuracy=grouped["sum"].to_numpy()[draw].sum(axis=1)/grouped["count"].to_numpy()[draw].sum(axis=1)
    return float(np.quantile(accuracy,.025)),float(np.quantile(accuracy,.975))


def directional_metrics(rows:pd.DataFrame)->dict[str,Any]:
    signals=rows[rows.predicted_direction.isin(["UP","DOWN"])].copy();n=len(signals);total=len(rows)
    correct=int(signals.predicted_direction.eq(signals.actual_direction).sum());incorrect=n-correct
    accuracy=correct/n if n else None;up=int(signals.predicted_direction.eq("UP").sum());down=int(signals.predicted_direction.eq("DOWN").sum())
    actual_directional=signals.actual_direction.isin(["UP","DOWN"])
    balanced=float(balanced_accuracy_score(signals.loc[actual_directional,"actual_direction"],signals.loc[actual_directional,"predicted_direction"])) if actual_directional.any() and signals.loc[actual_directional,"actual_direction"].nunique()==2 else None
    lo,hi=wilson_interval(correct,n);clo,chi=cluster_accuracy_ci(rows)
    actual_counts=signals.actual_direction.value_counts();majority=max(int(actual_counts.get("UP",0)),int(actual_counts.get("DOWN",0)))/n if n else None
    return {"total_rows":total,"predictions":n,"coverage":n/total if total else None,"up_predictions":up,"down_predictions":down,
        "no_signal":total-n,"correct":correct,"incorrect":incorrect,"accuracy":accuracy,"balanced_accuracy":balanced,
        "majority_class_baseline":majority,"wilson_95_ci_low":lo,"wilson_95_ci_high":hi,
        "cluster_bootstrap_95_ci_low":clo,"cluster_bootstrap_95_ci_high":chi,
        "max_prediction_class_share":max(up,down)/n if n else None}


def canonical_hash(value:dict[str,Any])->str:
    payload=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode()
    return hashlib.sha256(payload).hexdigest()
