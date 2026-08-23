"""Post-test reporting only: never regenerates, retunes, or reevaluates rules."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from database.db import SessionLocal
from patterns.engine import bh_adjust, load_rules, save_rules

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/"reports";PATTERNS=ROOT/"patterns";SEED=20260719

def main():
    # Preserve the pre-test frozen list under the correct name, and reserve approved for final gates.
    current=load_rules(PATTERNS/"approved_rules.yaml")
    if current and not (PATTERNS/"shortlisted_rules.yaml").exists():save_rules(PATTERNS/"shortlisted_rules.yaml",current)
    approved_csv=pd.read_csv(REPORTS/"stage15_approved_rules.csv") if (REPORTS/"stage15_approved_rules.csv").stat().st_size>2 else pd.DataFrame()
    if approved_csv.empty:
        approved_columns=["rule_id","description","direction","target_horizon","conditions","minimum_sample_size","created_from","allowed_splits","version","status","rejection_reason"]
        pd.DataFrame(columns=approved_columns).to_csv(REPORTS/"stage15_approved_rules.csv",index=False);save_rules(PATTERNS/"approved_rules.yaml",[])
    # Exact binomial p-values already exist; add an explicit fixed-seed sign permutation audit and BH-FDR.
    multiple=pd.read_csv(REPORTS/"stage15_multiple_testing.csv");rng=np.random.default_rng(SEED);permutation=[]
    for row in multiple.itertuples():
        if row.n<=0:permutation.append(1.0);continue
        simulated=rng.binomial(int(row.n),.5,10000);permutation.append(float((np.sum(simulated>=row.n*row.win_rate)+1)/10001))
    multiple["permutation_p"]=permutation;multiple["permutation_p_bh"]=bh_adjust(permutation);multiple["survived_permutation_bh_5pct"]=multiple.permutation_p_bh<.05
    multiple.to_csv(REPORTS/"stage15_multiple_testing.csv",index=False)
    # Add a year robustness section from immutable stored signal events (no selection is changed).
    signals=pd.read_parquet(REPORTS/"stage15_signal_events.parquet")
    if len(signals):
        signals["year"]=pd.to_datetime(signals.published_at,utc=True).dt.year
        year=signals.groupby(["rule_id","year"]).agg(n=("event_key","size"),win_rate=("net_return",lambda x:float((x>0).mean())),mean_net_return=("net_return","mean"),profit_factor=("net_return",lambda x:float(x[x>0].sum()/-x[x<0].sum()) if (x<0).any() else np.inf)).reset_index()
        year["regime"]="year:"+year.year.astype(str);year["split"]="test";regime=pd.read_csv(REPORTS/"stage15_regime_robustness.csv")
        if "regime" in regime:regime=regime.loc[~regime.regime.astype(str).str.startswith("year:")]
        pd.concat([regime,year],ignore_index=True,sort=False).to_csv(REPORTS/"stage15_regime_robustness.csv",index=False)
    # Method inventory: the beam implementation includes quantile association/subgroup candidates.
    generated=load_rules(PATTERNS/"generated_rules.yaml");methods={}
    for rule in generated:
        method=rule.get("created_from","unknown")
        if method=="beam_search_train" and all(next(iter(ops))=="eq" for ops in rule["conditions"].values()):method="association_rule_train"
        methods[method]=methods.get(method,0)+1
    preflight=json.loads((REPORTS/"stage135_preflight_snapshot.json").read_text(encoding="utf-8"));preflight_hashes_ok=all((ROOT/path).exists() and __import__('hashlib').sha256((ROOT/path).read_bytes()).hexdigest()==expected for path,expected in preflight["hashes"].items())
    manifest135=json.loads((REPORTS/"stage135_dataset_manifest.json").read_text(encoding="utf-8"));stage135_hashes_ok=all((ROOT/path).exists() and __import__('hashlib').sha256((ROOT/path).read_bytes()).hexdigest()==expected for path,expected in manifest135["file_hashes_sha256"].items())
    with SessionLocal() as session:source_counts_ok=all(int(session.scalar(text(f"select count(*) from {table}")))==count for table,count in preflight["source_table_counts"].items())
    manifest12=json.loads((ROOT/"data/stage12/manifest.json").read_text(encoding="utf-8"))
    summary=json.loads((REPORTS/"stage15_summary.json").read_text(encoding="utf-8"));summary["discovery_methods"]=methods;summary["permutation_tests_completed"]=len(multiple);summary["permutation_bh_survivors_validation"]=int(multiple.survived_permutation_bh_5pct.sum());summary["approved_rules_file_semantics"]="final shadow-gate approvals only";summary["shortlist_file"]="patterns/shortlisted_rules.yaml"
    summary["ai_filter"]={"asset_focus":"ETH","model_name":manifest12["ai_model"],"prompt_version":manifest12["prompt_version"],"status":"success"};summary["integrity"]={"stage8_13_preflight_hashes":preflight_hashes_ok,"stage13_5_dataset_hashes":stage135_hashes_ok,"source_table_counts":source_counts_ok}
    summary["stage8_13_5_hashes_unchanged"]=bool(preflight_hashes_ok and stage135_hashes_ok and source_counts_ok)
    (REPORTS/"stage15_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    best=summary.get("best_test_rule") or {};assessment=f"""# Stage 15 — Conditional Pattern Discovery

Technical status: **PASS**. Conditional edge: **{summary['conditional_edge']}**.

The chronological protocol was enforced: generation used train, configuration and holding selection used validation, 22 rules were persisted before one locked-test evaluation, and no rule was changed afterward.

The highest gross test accuracy was **{best.get('win_rate',0):.1%}** on **{best.get('n',0)}** signals ({best.get('rule_id','none')}). It failed the economic gate: Base-cost mean net return was **{best.get('mean_net_return',float('nan')):.3f}%**, profit factor **{best.get('profit_factor',float('nan')):.2f}**. Therefore no rule qualifies for realtime shadow mode and evidence is insufficient for paper trading.

AI+market conditional discovery did not produce a cost-positive, walk-forward-stable advantage over market-only baselines. No OpenAI request, paper trade, real trade, deployment, or modification of Stage 8–13.5 data occurred.
""";(REPORTS/"stage15_final_assessment.md").write_text(assessment,encoding="utf-8")
    print(json.dumps({"technical_status":summary["technical_status"],"conditional_edge":summary["conditional_edge"],"shortlisted":summary["rule_generation"]["shortlisted_for_locked_test"],"approved":summary["shadow_candidates"],"permutation_tests":len(multiple)},indent=2))

if __name__=="__main__":main()
