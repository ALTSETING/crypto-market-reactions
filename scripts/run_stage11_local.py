"""Run authorized local-only Stage 11 steps 1-6 and stop before paid enrichment."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analysis.stage11_enrichment import write_enrichment_dry_run
from analysis.stage11_models import run_ablation, run_walkforward
from app.config import settings
from database.db import session_scope
from ml.stage11_dataset_builder import build_dataset_a, load_analysis_rows, select_earliest_events

ROOT=Path(__file__).resolve().parents[1]; REPORTS=ROOT/"reports"


def comparison_summary(path: Path, walkforward_path: Path) -> dict:
    data=pd.read_csv(path); test=data[(data.split=="test") & data.feature_set.isin(["A_market_only","B_stage9_ai_only","C_market_plus_stage9_ai"])]
    comparisons=[]
    for (model,target),group in test.groupby(["model","target"]):
        indexed=group.set_index("feature_set")
        if "A_market_only" not in indexed.index or "C_market_plus_stage9_ai" not in indexed.index:continue
        task=indexed.loc["A_market_only","task"]
        if task=="classification":
            a=float(indexed.loc["A_market_only","balanced_accuracy"]); c=float(indexed.loc["C_market_plus_stage9_ai","balanced_accuracy"]); metric="balanced_accuracy"; delta=c-a
        else:
            a=float(indexed.loc["A_market_only","mae"]); c=float(indexed.loc["C_market_plus_stage9_ai","mae"]); metric="mae_reduction_fraction"; delta=(a-c)/a if a else 0
        comparisons.append({"model":model,"target":target,"task":task,"metric":metric,"market_only":a,"market_plus_ai":c,"ai_increment":delta,"c_beats_a":delta>0})
    walk=pd.read_csv(walkforward_path); pairs=[]
    for (fold,model,target),group in walk.groupby(["fold","model","target"]):
        indexed=group.set_index("feature_set")
        if "A_market_only" not in indexed.index or "C_market_plus_stage9_ai" not in indexed.index:continue
        task=indexed.loc["A_market_only","task"]
        delta=(float(indexed.loc["C_market_plus_stage9_ai","balanced_accuracy"])-float(indexed.loc["A_market_only","balanced_accuracy"])) if task=="classification" else ((float(indexed.loc["A_market_only","mae"])-float(indexed.loc["C_market_plus_stage9_ai","mae"]))/float(indexed.loc["A_market_only","mae"]))
        pairs.append(delta>0)
    return {"test_comparisons":len(comparisons),"test_c_beats_a":sum(row["c_beats_a"] for row in comparisons),"test_c_win_rate":sum(row["c_beats_a"] for row in comparisons)/len(comparisons) if comparisons else 0,
            "walkforward_comparisons":len(pairs),"walkforward_c_beats_a":sum(pairs),"walkforward_c_win_rate":sum(pairs)/len(pairs) if pairs else 0,"details":comparisons}


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--resume",action="store_true"); args=parser.parse_args()
    REPORTS.mkdir(parents=True,exist_ok=True)
    if args.resume and (REPORTS/"stage11_eth_dataset_a.parquet").exists():
        dataset=pd.read_parquet(REPORTS/"stage11_eth_dataset_a.parquet")
        schema=json.loads((REPORTS/"stage11_eth_dataset_schema.json").read_text(encoding="utf-8"))
        build={"source_rows":7065,"event_rows":schema["event_selection_rows"],"dataset_rows":schema["rows"],"features":len(schema["features"]),"targets":len(schema["targets"]),"beta_fallbacks":int(dataset.metadata_beta_fallback_used.sum()),"missing_events":schema["missing_events"]}
    else:
        with session_scope() as session:
            dataset,build=build_dataset_a(session,REPORTS)
    splits=json.loads((REPORTS/"stage11_eth_splits.json").read_text(encoding="utf-8"))
    if args.resume and (REPORTS/"stage11_eth_ablation_metrics.csv").exists():
        ablation_frame=pd.read_csv(REPORTS/"stage11_eth_ablation_metrics.csv"); ablation={"rows":len(ablation_frame),"resumed":True}
    else: ablation=run_ablation(dataset,REPORTS)
    if args.resume and (REPORTS/"stage11_eth_walkforward_metrics.csv").exists():
        walk_frame=pd.read_csv(REPORTS/"stage11_eth_walkforward_metrics.csv"); walkforward={"rows":len(walk_frame),"folds":int(walk_frame.fold.nunique()),"resumed":True}
    else: walkforward=run_walkforward(dataset,splits,REPORTS)
    with session_scope() as session:
        selected,_=select_earliest_events(load_analysis_rows(session))
    enrichment=write_enrichment_dry_run(selected,REPORTS,settings.openai_max_article_tokens)
    comparison=comparison_summary(REPORTS/"stage11_eth_ablation_metrics.csv",REPORTS/"stage11_eth_walkforward_metrics.csv")
    required=["stage11_eth_event_selection.csv","stage11_eth_abnormal_returns.parquet","stage11_eth_market_features.parquet","stage11_eth_dataset_a.parquet","stage11_eth_dataset_a_sample.csv","stage11_eth_dataset_schema.json","stage11_eth_feature_list.csv","stage11_eth_splits.json","stage11_eth_ablation_metrics.csv","stage11_eth_walkforward_metrics.csv","stage11_eth_target_metrics.csv","stage11_eth_feature_importance.csv","stage11_eth_enrichment_selection.json","stage11_eth_enrichment_cost_estimate.json","stage11_eth_enrichment_input_preview.json","stage11_eth_enrichment_model_comparison.json"]
    summary={"phase_status":"LOCAL_STEPS_1_6_PASS" if all((REPORTS/name).exists() and (REPORTS/name).stat().st_size>0 for name in required) else "LOCAL_STEPS_1_6_FAIL",
             "overall_stage11_status":"PENDING_USER_CONFIRMATION_FOR_PAID_ENRICHMENT","created_at":datetime.now(timezone.utc).isoformat(),"api_requests_made":0,"paid_enrichment_run":False,"dataset_b_created":False,"real_trading_run":False,"paper_trading_run":False,
             "build":build,"ablation":ablation,"walkforward":walkforward,"ablation_comparison":comparison,"enrichment_dry_run":enrichment,"required_local_reports":required,
             "limitations":["Seven Stage 9 events lie outside complete candle coverage and are documented.","Dataset B and model D require paid enrichment and were not created.","Signal simulation, full robustness, and final predictive claim are deferred until after the enrichment decision.","Local A/B/C results are baseline experiments, not a production model or trading proof."]}
    summary_path=REPORTS/"stage11_eth_summary.json"
    if args.resume and summary_path.exists():
        previous=json.loads(summary_path.read_text(encoding="utf-8"))
        for key in ["pytest","local_audit","walkforward_family_summary","gate","deferred_by_instruction","predictive_hypothesis_local_abc"]:
            if key in previous: summary[key]=previous[key]
    summary_path.write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    assessment=f"""# Stage 11 local pre-enrichment assessment

- Local steps 1-6: **{summary['phase_status']}**
- Overall Stage 11: **PENDING** — paid enrichment was not authorized or called.
- Event selection: {build['event_rows']:,}; Dataset A rows: {build['dataset_rows']:,}; features: {build['features']}; targets: {build['targets']}.
- API requests: 0. Dataset B/model D: not created.
- On chronological test, market+Stage9 AI beats market-only in {comparison['test_c_beats_a']}/{comparison['test_comparisons']} fixed model/target comparisons.
- Across walk-forward folds it wins {comparison['walkforward_c_beats_a']}/{comparison['walkforward_comparisons']} comparisons.

These counts alone do not establish a predictive edge; practical effect size and consistency must be reviewed after the dry-run gate and, only with separate approval, enrichment A/B. No paper or real trading was run.
"""
    assessment_path=REPORTS/"stage11_eth_final_assessment.md"
    if not args.resume or not assessment_path.exists():
        assessment_path.write_text(assessment,encoding="utf-8")
    print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__=="__main__":main()
