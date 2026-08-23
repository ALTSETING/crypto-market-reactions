import argparse,json
from collections import Counter
from pathlib import Path
import pandas as pd
from sqlalchemy import text
from database.db import session_scope
from high_impact_sources.config import HORIZONS,REPORTS
from high_impact_sources.datasets.quality_audit import audit
from scripts.import_high_impact_history import availability_audit

def main():
    p=argparse.ArgumentParser();p.add_argument("--tests-passed",type=int,default=0);p.add_argument("--tests-failed",type=int,default=0);args=p.parse_args();REPORTS.mkdir(parents=True,exist_ok=True)
    with session_scope() as session:
        quality=audit(session)
        events=pd.read_sql(text("SELECT * FROM high_impact_events ORDER BY published_at,id"),session.connection())
        assets=pd.read_sql(text("SELECT a.*,e.source,e.published_at,e.time_source,e.time_confidence,e.crypto_relevance,e.event_group_id FROM high_impact_event_assets a JOIN high_impact_events e ON e.id=a.event_id ORDER BY e.published_at,a.event_id,a.asset"),session.connection())
        reactions=pd.read_sql(text("SELECT r.*,e.source,a.asset FROM high_impact_market_reactions r JOIN high_impact_events e ON e.id=r.event_id JOIN high_impact_event_assets a ON a.event_id=r.event_id AND r.symbol=CASE a.asset WHEN 'BTC' THEN 'BTCUSDT' WHEN 'ETH' THEN 'ETHUSDT' ELSE 'SOLUSDT' END ORDER BY e.published_at,r.event_id,r.symbol,r.latency_minutes"),session.connection())
    availability=availability_audit()
    actual=events.groupby("source").agg(actual_events=("id","count"),earliest_actual=("published_at","min"),latest_actual=("published_at","max")).reset_index() if len(events) else pd.DataFrame()
    availability_frame=pd.DataFrame(availability)
    if len(actual):availability_frame=availability_frame.merge(actual,on="source",how="left")
    availability_frame.to_csv(REPORTS/"stage16_source_availability.csv",index=False,encoding="utf-8-sig");(REPORTS/"stage16_source_availability.json").write_text(availability_frame.to_json(orient="records",indent=2,date_format="iso"),encoding="utf-8")
    import_files=[x for x in REPORTS.glob("stage16_import_*.json") if x.name!="stage16_import_stats.json"];import_stats=[json.loads(x.read_text(encoding="utf-8")) for x in import_files]
    aggregate={"sources":import_stats,"database_events_by_source":events.source.value_counts().to_dict() if len(events) else {},"database_status":events.status.value_counts().to_dict() if len(events) else {},"resume_semantics":"unique URL/canonical/content/platform+external constraints and bulk ON CONFLICT"};(REPORTS/"stage16_import_stats.json").write_text(json.dumps(aggregate,indent=2,default=str),encoding="utf-8")
    if len(events):
        source_quality=events.groupby(["source","status"],dropna=False).agg(events=("id","count"),mean_authenticity=("source_authenticity","mean"),mean_relevance=("crypto_relevance","mean"),mean_time_confidence=("time_confidence","mean"),earliest=("published_at","min"),latest=("published_at","max")).reset_index()
        timestamp_quality=events.groupby(["source","time_source"],dropna=False).agg(events=("id","count"),mean_confidence=("time_confidence","mean"),min_confidence=("time_confidence","min"),max_confidence=("time_confidence","max")).reset_index()
    else:source_quality=timestamp_quality=pd.DataFrame()
    source_quality.to_csv(REPORTS/"stage16_source_quality.csv",index=False,encoding="utf-8-sig");timestamp_quality.to_csv(REPORTS/"stage16_timestamp_quality.csv",index=False,encoding="utf-8-sig")
    relevance=assets.groupby(["source","asset"],dropna=False).agg(event_assets=("id","count"),mean_relevance=("relevance","mean"),earliest=("published_at","min"),latest=("published_at","max")).reset_index() if len(assets) else pd.DataFrame(columns=["source","asset","event_assets"])
    relevance.to_csv(REPORTS/"stage16_crypto_relevance.csv",index=False,encoding="utf-8-sig")
    groups=events.groupby("event_group_id",dropna=False).agg(first_information_time=("published_at","min"),first_source=("source","first"),first_source_type=("source_type","first"),source_count=("source","nunique"),event_count=("id","count")).reset_index() if len(events) else pd.DataFrame()
    if len(groups):groups["duplicate_count"]=groups.event_count-1
    groups.to_csv(REPORTS/"stage16_event_groups.csv",index=False,encoding="utf-8-sig")
    source_asset=reactions[reactions.latency_minutes==0].groupby(["source","asset"]).agg(reactions=("id","count"),median_return_1h=("return_1h","median"),median_abs_return_1h=("return_1h",lambda x:x.abs().median()),median_return_12h=("return_12h","median")).reset_index() if len(reactions) else pd.DataFrame()
    source_asset.to_csv(REPORTS/"stage16_source_asset_metrics.csv",index=False,encoding="utf-8-sig")
    horizons=[]
    for label in HORIZONS:
        if len(reactions):
            for (symbol,latency),part in reactions.groupby(["symbol","latency_minutes"]):horizons.append({"symbol":symbol,"latency_minutes":int(latency),"horizon":label,"n":len(part),"mean_return":part[f"return_{label}"].mean(),"median_return":part[f"return_{label}"].median(),"mean_abs_return":part[f"return_{label}"].abs().mean(),"mean_abnormal_return":part[f"abnormal_return_{label}"].mean()})
    pd.DataFrame(horizons).to_csv(REPORTS/"stage16_horizon_metrics.csv",index=False,encoding="utf-8-sig")
    patterns=[]
    base=reactions[reactions.latency_minutes==0] if len(reactions) else reactions
    for (source,asset),part in base.groupby(["source","asset"]):
        n=len(part);values=part.return_1h;patterns.append({"source":source,"asset":asset,"rule":"source_asset_1h","n":n,"mean_return":values.mean(),"win_rate_positive":float((values>0).mean()),"eligible_for_inference":n>=90,"status":"exploratory_only" if n<90 else "requires_chronological_validation"})
    pd.DataFrame(patterns).to_csv(REPORTS/"stage16_pattern_metrics.csv",index=False,encoding="utf-8-sig")
    reaction_stats=json.loads((REPORTS/"stage16_reaction_stats.json").read_text()) if (REPORTS/"stage16_reaction_stats.json").exists() else {"missing_count":None}
    ai=json.loads((REPORTS/"stage16_ai_cost_estimate.json").read_text()) if (REPORTS/"stage16_ai_cost_estimate.json").exists() else {}
    paid=[row["source"] for row in availability if row.get("status")=="blocked"]
    phase_pass=all([quality["events"]>0,quality["accepted"]>0,quality["reactions"]>0,quality["duplicate_url"]==quality["duplicate_canonical"]==quality["duplicate_hash"]==quality["duplicate_identity"]==0,quality["non_utc_timestamps"]==0,ai.get("leakage_violations")==0,args.tests_failed==0,args.tests_passed>0,(REPORTS/"stage16_dataset_manifest.json").exists()])
    summary={"status":"PASS" if phase_pass else "FAIL","quality":quality,"events_by_source":events.source.value_counts().to_dict() if len(events) else {},"accepted_by_source":events[events.status=="accepted"].source.value_counts().to_dict() if len(events) else {},"historical_period":{"earliest":events.published_at.min().isoformat() if len(events) else None,"latest":events.published_at.max().isoformat() if len(events) else None},"assets":assets.asset.value_counts().to_dict() if len(assets) else {},"reactions":quality["reactions"],"reaction_rows_by_symbol":reactions.symbol.value_counts().to_dict() if len(reactions) else {},"missing_candle_windows":reaction_stats.get("missing_count"),"ai_dry_run":ai,"paid_or_blocked_sources":paid,"tests":{"passed":args.tests_passed,"failed":args.tests_failed},"leakage_violations":ai.get("leakage_violations"),"production_polling":False,"paid_api_calls":0,"paper_or_real_trading":False}
    (REPORTS/"stage16_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    assessment=f"""# Stage 16 Phase 1 assessment\n\nStatus: **{summary['status']}**\n\n- Isolated events: {quality['events']} ({quality['accepted']} accepted, {quality['rejected']} rejected)\n- Event-assets: {quality['assets']}\n- Reactions: {quality['reactions']}\n- Missing candle windows: {reaction_stats.get('missing_count')}\n- Duplicate violations: {quality['duplicate_url']+quality['duplicate_canonical']+quality['duplicate_hash']+quality['duplicate_identity']}\n- Leakage violations: {ai.get('leakage_violations')}\n- Paid API calls: 0\n- Tests: {args.tests_passed} passed, {args.tests_failed} failed\n\nAI analysis remains dry-run only. X and Truth Social remain blocked until a separately approved official access path exists. No paper, real, or production polling was started.\n"""
    (REPORTS/"stage16_final_assessment.md").write_text(assessment,encoding="utf-8");print(json.dumps(summary,default=str))
if __name__=="__main__":main()
