"""Pure Stage 17 subgroup, context, and statistical helpers."""
from __future__ import annotations

import hashlib
import itertools
import math
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

HORIZONS=("1m","5m","10m","20m","40m","1h","3h","5h","8h","12h")
PRIMARY_HORIZONS=("1h","3h","12h")
EXPLORATORY_HORIZONS=tuple(h for h in HORIZONS if h not in PRIMARY_HORIZONS)
DIRECTIONAL_HYPOTHESES=("H2","H3")
HOLDINGS=("20m","40m","1h","3h","5h","8h","12h")
STRONG_THRESHOLDS=(.25,.5,1.,2.,3.)
NEUTRAL_BANDS=(.10,.25,.50)
SCORE_COLUMNS=("ai_asset_relevance","ai_importance","ai_novelty","ai_specificity","ai_confidence",
 "ai_source_reliability","ai_actionability","ai_institutional_relevance","ai_retail_relevance",
 "ai_regulatory_strength","ai_economic_significance","ai_technical_significance","ai_security_significance","ai_adoption_significance",
 "ai_execution_certainty","ai_urgency","ai_fundamental_relevance","ai_surprise_level")

SUBGROUP_CONDITIONS={
 "A":"relevance>=60 and directness=direct",
 "B":"relevance>=80 and directness in {direct,market_wide}",
 "C":"importance>=50 and specificity>=50 and relevance>=60",
 "D":"importance>=60 and novelty>=40 and specificity>=60 and relevance>=70 and primary evidence",
 "E":"confirmed_action and actionability>=60 and execution_certainty>=70 and relevance>=60",
 "F":"structural and fundamental_relevance>=60 and relevance>=60",
 "G":"regulatory event and regulatory_strength non-null and relevance>=60",
 "H":"protocol_update and technical_significance>=50 and relevance>=60",
 "I":"institutional_relevance>=60 and relevance>=60",
 "J":"(security_event or security_significance>=60) and relevance>=60",
 "K":"relevance<40 or importance<30",
 "L":"relevance>=70 and importance<30",
}

def subgroup_masks(frame:pd.DataFrame)->dict[str,pd.Series]:
    r=frame.ai_asset_relevance
    primary=frame.ai_evidence_quality.isin(["official_document","official_statement","primary_source"])
    return {
      "A":(r>=60)&frame.ai_directness.eq("direct"),
      "B":(r>=80)&frame.ai_directness.isin(["direct","market_wide"]),
      "C":(frame.ai_importance>=50)&(frame.ai_specificity>=50)&(r>=60),
      "D":(frame.ai_importance>=60)&(frame.ai_novelty>=40)&(frame.ai_specificity>=60)&(r>=70)&primary,
      "E":frame.source_information_status.eq("confirmed_action")&(frame.ai_actionability>=60)&(frame.ai_execution_certainty>=70)&(r>=60),
      "F":frame.ai_temporary_vs_structural.eq("structural")&(frame.ai_fundamental_relevance>=60)&(r>=60),
      "G":frame.source_event_type.isin(["official_decision","legal_action","policy_statement"])&frame.ai_regulatory_strength.notna()&(r>=60),
      "H":frame.source_event_type.eq("protocol_update")&(frame.ai_technical_significance>=50)&(r>=60),
      "I":(frame.ai_institutional_relevance>=60)&(r>=60),
      "J":(frame.source_event_type.eq("security_event")|(frame.ai_security_significance>=60))&(r>=60),
      "K":(r<40)|(frame.ai_importance<30),
      "L":(r>=70)&(frame.ai_importance<30),
    }

def membership(frame:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for subgroup,mask in subgroup_masks(frame).items():
        for event_id,asset,split,matched in zip(frame.metadata_event_id,frame.metadata_asset,frame.metadata_split,mask):
            rows.append({"event_id":int(event_id),"asset":asset,"subgroup_id":subgroup,"matched":bool(matched),"split":split,"conditions_json":SUBGROUP_CONDITIONS[subgroup]})
    return pd.DataFrame(rows)

def verified_primary_source(source:str,url:str|None,platform:str|None,external_id:str|None)->tuple[bool,str]:
    host=(url or "").lower();source=(source or "").lower();platform=(platform or "").lower()
    rules={
      "sec":("sec.gov",),
      "ethereum_foundation":("ethereum.org","blog.ethereum.org"),
      "ethereum_github":("github.com","api.github.com"),
      "elon_musk":("x.com",),
      "donald_trump":("truthsocial.com",),
    }
    domains=rules.get(source,())
    domain_ok=any(domain in host for domain in domains)
    identity_ok=bool(external_id) if source in {"sec","ethereum_github"} else source in rules
    adapter_ok=platform in {"sec","ethereum_foundation","github","x","truth_social"} or source in {"sec","ethereum_foundation","ethereum_github"}
    value=bool(domains and domain_ok and identity_ok and adapter_ok)
    reasons=[]
    if domain_ok:reasons.append("official_domain")
    if identity_ok:reasons.append("official_identity")
    if adapter_ok:reasons.append("valid_adapter")
    return value,"+".join(reasons) if value else "verification_rule_incomplete"

def fit_context_bins(frame:pd.DataFrame)->dict:
    train=frame[frame.metadata_split.eq("train")]
    def q(col,values=(.33,.67)):
        series=pd.to_numeric(train[col],errors="coerce").dropna()
        return [float(series.quantile(x)) for x in values]
    return {"btc_return_1h":q("pre_btc_return_60m"),"asset_return_20m":q("pre_return_20m"),
            "volatility_60m":q("pre_realized_vol_60m"),"relative_strength":q("pre_relative_strength_1h")}

def apply_context_bins(frame:pd.DataFrame,thresholds:dict)->pd.DataFrame:
    out=frame.copy();lo,hi=thresholds["btc_return_1h"]
    # This column is actual BTC context: directly observed for BTC and reconstructed
    # from asset return minus the Stage 16 BTC-relative-strength feature otherwise.
    out["context_btc_state"]=np.select([out.pre_btc_return_60m<=lo,out.pre_btc_return_60m>=hi],["falling","rising"],default="stable")
    alo,ahi=thresholds["asset_return_20m"]
    out["context_asset_state"]=np.select([out.pre_return_20m<=alo,out.pre_return_20m>=ahi],["already_falling","already_rising"],default="stable")
    vlo,vhi=thresholds["volatility_60m"]
    out["context_volatility"]=np.select([out.pre_realized_vol_60m<=vlo,out.pre_realized_vol_60m>=vhi],["low","high"],default="medium")
    rlo,rhi=thresholds["relative_strength"]
    out["context_relative_strength"]=np.select([out.pre_relative_strength_1h<=rlo,out.pre_relative_strength_1h>=rhi],["weak","strong"],default="middle")
    return out

def sample_gate(train:int,validation:int,test:int,total:int)->str:
    if total<20:return "descriptive_only"
    if train>=50 and validation>=20 and test>=20:
        return "strong_candidate" if total>=200 and test>=50 else "candidate"
    return "exploratory"

def bh_adjust(p_values:list[float])->list[float]:
    if not p_values:return []
    p=np.asarray([1. if pd.isna(x) else x for x in p_values],dtype=float);order=np.argsort(p);ranked=p[order]
    adjusted=np.minimum.accumulate((ranked*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]
    result=np.empty(len(p));result[order]=np.clip(adjusted,0,1);return result.tolist()

def wilson(successes:int,n:int,z=1.959963984540054)->tuple[float|None,float|None]:
    if n==0:return None,None
    p=successes/n;den=1+z*z/n;center=(p+z*z/(2*n))/den;margin=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return center-margin,center+margin

def bootstrap_ci(values:pd.Series,seed=17,reps=500)->tuple[float|None,float|None]:
    data=pd.to_numeric(values,errors="coerce").dropna().to_numpy()
    if len(data)<2:return None,None
    rng=np.random.default_rng(seed);means=np.array([rng.choice(data,len(data),replace=True).mean() for _ in range(reps)])
    return float(np.quantile(means,.025)),float(np.quantile(means,.975))

def cluster_bootstrap_ci(frame:pd.DataFrame,value_col:str,cluster_col:str="metadata_event_id",seed=17,reps=100)->tuple[float|None,float|None]:
    """Bootstrap event clusters; all asset rows from a sampled event travel together."""
    clean=frame[[cluster_col,value_col]].dropna()
    grouped=clean.groupby(cluster_col)[value_col].agg(["sum","count"])
    if len(grouped)<2:return None,None
    rng=np.random.default_rng(seed);sampled=rng.integers(0,len(grouped),size=(reps,len(grouped)))
    sums=grouped["sum"].to_numpy(float)[sampled].sum(axis=1)
    counts=grouped["count"].to_numpy(float)[sampled].sum(axis=1)
    means=sums/counts
    return float(np.quantile(means,.025)),float(np.quantile(means,.975))

def cluster_resample(frame:pd.DataFrame,cluster_col:str="metadata_event_id",seed=17)->pd.DataFrame:
    """One auditable event-cluster resample used by tests and diagnostics."""
    ids=frame[cluster_col].drop_duplicates().to_numpy();rng=np.random.default_rng(seed)
    samples=[]
    for draw,key in enumerate(rng.choice(ids,len(ids),replace=True)):
        part=frame[frame[cluster_col].eq(key)].copy();part["cluster_draw"]=draw;samples.append(part)
    return pd.concat(samples,ignore_index=True) if samples else frame.iloc[0:0].copy()

def cluster_permutation_p(frame:pd.DataFrame,mask:pd.Series,value_col:str,cluster_col:str="metadata_event_id",seed=17,reps=100)->float|None:
    """Permute subgroup labels at event level without splitting cross-asset rows."""
    work=frame[[cluster_col,value_col]].copy();work["matched"]=mask.to_numpy();work=work.dropna(subset=[value_col])
    labels=work.groupby(cluster_col).matched.max()
    if labels.sum()<2 or (~labels).sum()<2:return None
    observed=abs(work.loc[work.matched,value_col].mean()-work.loc[~work.matched,value_col].mean())
    clusters,codes=np.unique(work[cluster_col].to_numpy(),return_inverse=True)
    base=labels.reindex(clusters).to_numpy(bool);rng=np.random.default_rng(seed)
    orders=np.argsort(rng.random((reps,len(base))),axis=1);permuted=base[orders][:,codes]
    values=work[value_col].to_numpy(float);valid=np.isfinite(values);values=np.where(valid,values,0.0)
    left_count=(permuted&valid).sum(axis=1);right_count=((~permuted)&valid).sum(axis=1)
    left_sum=(permuted*values).sum(axis=1);right_sum=((~permuted)*values).sum(axis=1)
    diffs=np.abs(left_sum/left_count-right_sum/right_count)
    return (int((diffs>=observed).sum())+1)/(reps+1)

def add_event_contamination(frame:pd.DataFrame)->pd.DataFrame:
    """Add next-event overlap fields for every event-asset-horizon observation."""
    horizon_minutes={"1m":1,"5m":5,"10m":10,"20m":20,"40m":40,"1h":60,"3h":180,"5h":300,"8h":480,"12h":720}
    base=frame[["metadata_event_id","metadata_asset","reaction_baseline_time"]].drop_duplicates().sort_values(["metadata_asset","reaction_baseline_time","metadata_event_id"])
    base["next_high_impact_event_same_asset_at"]=base.groupby("metadata_asset")["reaction_baseline_time"].shift(-1)
    base["minutes_to_next_high_impact_event"]=(base.next_high_impact_event_same_asset_at-base.reaction_baseline_time).dt.total_seconds()/60
    rows=[]
    grouped={asset:group for asset,group in base.groupby("metadata_asset")}
    for row in base.itertuples(index=False):
        times=grouped[row.metadata_asset].reaction_baseline_time
        for horizon,minutes in horizon_minutes.items():
            count=int(((times>row.reaction_baseline_time)&(times<=row.reaction_baseline_time+pd.Timedelta(minutes=minutes))).sum())
            rows.append({"event_id":int(row.metadata_event_id),"asset":row.metadata_asset,"horizon":horizon,
                "next_high_impact_event_same_asset_at":row.next_high_impact_event_same_asset_at,
                "minutes_to_next_high_impact_event":row.minutes_to_next_high_impact_event,
                "overlapping_event_within_horizon":count>0,"overlapping_event_count":count,"isolated_event":count==0})
    return pd.DataFrame(rows)

def permutation_p(left:pd.Series,right:pd.Series,seed=17,reps=500)->float|None:
    a=pd.to_numeric(left,errors="coerce").dropna().to_numpy();b=pd.to_numeric(right,errors="coerce").dropna().to_numpy()
    if len(a)<2 or len(b)<2:return None
    observed=abs(a.mean()-b.mean());pool=np.concatenate([a,b]);rng=np.random.default_rng(seed);count=0
    for _ in range(reps):
        rng.shuffle(pool);count+=abs(pool[:len(a)].mean()-pool[len(a):].mean())>=observed
    return (count+1)/(reps+1)

def comparison_stats(values:pd.Series,rest:pd.Series,seed=17)->dict:
    a=pd.to_numeric(values,errors="coerce").dropna();b=pd.to_numeric(rest,errors="coerce").dropna()
    lo,hi=bootstrap_ci(a,seed);u_p=float(mannwhitneyu(a,b,alternative="two-sided").pvalue) if len(a) and len(b) else None
    pooled=math.sqrt(((len(a)-1)*a.var(ddof=1)+(len(b)-1)*b.var(ddof=1))/(len(a)+len(b)-2)) if len(a)>1 and len(b)>1 else 0
    effect=float((a.mean()-b.mean())/pooled) if pooled and not math.isnan(pooled) else None
    return {"n_subgroup":len(a),"n_rest":len(b),"mean_subgroup":float(a.mean()) if len(a) else None,"mean_rest":float(b.mean()) if len(b) else None,
            "median_subgroup":float(a.median()) if len(a) else None,"median_rest":float(b.median()) if len(b) else None,
            "mean_diff":float(a.mean()-b.mean()) if len(a) and len(b) else None,"standardized_effect":effect,
            "bootstrap_mean_ci_low":lo,"bootstrap_mean_ci_high":hi,"mann_whitney_p":u_p,"permutation_p":permutation_p(a,b,seed)}

def horizon_metrics(part:pd.DataFrame,horizon:str)->dict:
    return_col=f"target_return_{horizon}" if f"target_return_{horizon}" in part else f"return_{horizon}"
    returns=pd.to_numeric(part[return_col],errors="coerce").dropna();n=len(returns)
    result={"n":n,"mean_return":float(returns.mean()) if n else None,"median_return":float(returns.median()) if n else None,
      "mean_absolute_return":float(returns.abs().mean()) if n else None,"median_absolute_return":float(returns.abs().median()) if n else None,
      "positive_rate":float((returns>0).mean()) if n else None,"negative_rate":float((returns<0).mean()) if n else None}
    for threshold in STRONG_THRESHOLDS:result[f"strong_move_rate_{threshold:g}"]=float((returns.abs()>=threshold).mean()) if n else None
    excursion="1h" if horizon in {"1m","5m","10m","20m","40m","1h"} else "12h"
    for name in ("max_favorable","max_adverse","realized_vol"):
        target_col=f"target_{name}_{excursion}";raw_col=f"{name}_{excursion}"
        col=target_col if target_col in part else raw_col
        result[name+"_proxy"]=float(pd.to_numeric(part[col],errors="coerce").mean()) if col in part and part[col].notna().any() else None
    return result

def manual_hypothesis_masks(frame:pd.DataFrame)->dict[str,pd.Series]:
    direct=(frame.ai_asset_relevance>=60)&frame.ai_directness.eq("direct")
    positive=frame.ai_content_valence.eq("positive")&(frame.ai_content_valence_score>0)
    negative=frame.ai_content_valence.eq("negative")&(frame.ai_content_valence_score<0)
    stable=frame.context_btc_state.eq("stable")
    return {
      "H1":frame.verified_primary_source&frame.source_information_status.eq("confirmed_action")&direct&stable,
      "H2":frame.metadata_asset.eq("ETH")&positive&(frame.ai_asset_relevance>=70)&frame.ai_directness.eq("direct")&(frame.ai_importance>=50)&~frame.context_asset_state.eq("already_rising"),
      "H3":negative&(frame.ai_asset_relevance>=60)&frame.source_event_type.isin(["official_decision","legal_action","policy_statement"])&~frame.context_btc_state.eq("rising"),
      "H4":frame.metadata_asset.eq("ETH")&frame.source_event_type.eq("protocol_update")&(frame.ai_technical_significance>=50)&(frame.ai_asset_relevance>=60)&~frame.context_volatility.eq("high"),
      "H5":(frame.ai_institutional_relevance>=60)&(frame.ai_execution_certainty>=70)&(frame.ai_asset_relevance>=60)&frame.context_btc_state.isin(["stable","rising"]),
      "H6":(frame.ai_novelty>=50)&(frame.ai_specificity>=60)&(frame.ai_asset_relevance>=70)&frame.ai_directness.eq("direct"),
      "H7":frame.verified_primary_source&frame.source_information_status.eq("confirmed_action")&frame.ai_temporary_vs_structural.eq("structural")&(frame.ai_fundamental_relevance>=60),
      "H8":(frame.source_event_type.eq("security_event")|(frame.ai_security_significance>=60))&(frame.ai_asset_relevance>=60)&frame.ai_directness.eq("direct"),
      "H9":frame.metadata_source.isin(["elon_musk","donald_trump"])&direct,
      "H10":(frame.ai_asset_relevance>=70)&(frame.ai_importance<30),
      "H11":frame.verified_primary_source&(frame.ai_novelty<20)&(frame.ai_asset_relevance>=40),
      "H12":frame.ai_directness.eq("direct"),
    }

def stable_hashes(paths:list[Path])->dict[str,str]:
    return {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}
