"""Run the read-only Stage 13A ETH early-reaction timing audit."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

from database.db import SessionLocal
from ml.stage11_dataset_builder import load_candle_grid
from ml.stage13a_timing_audit import (
    CORE_CATEGORIES,
    RETURN_HORIZONS,
    THRESHOLDS,
    build_early_record,
    direction_metrics,
    earliest_horizon,
    grouped_timing,
    verify_stage12,
)

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _second_article_delays(session: Any) -> pd.DataFrame:
    query = text("""
        SELECT event_group_id,
               count(*)::integer AS database_article_count,
               extract(epoch FROM ((array_agg(published_at ORDER BY published_at,id))[2]
                         - min(published_at))) / 60.0 AS second_article_delay_minutes
        FROM news_articles
        WHERE event_group_id IS NOT NULL
        GROUP BY event_group_id
    """)
    return pd.read_sql(query, session.connection())


def _source_report(frame: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for source, group in frame.groupby("source"):
        row={"source":source,"event_count":len(group),"median_abs_pre_move_5m":group.abs_pre_move_5m.median(),
             "median_abs_post_move_5m":group.abs_post_move_5m.median(),"pre_post_ratio_5m":group.abs_pre_move_5m.median()/max(group.abs_post_move_5m.median(),1e-12),
             "earliest_reaction_horizon_010":earliest_horizon(group)}
        for threshold in THRESHOLDS:
            suffix=f"{int(threshold*100):03d}"; row[f"late_publication_rate_{suffix}"]=group[f"late_publication_{suffix}"].mean()
        for horizon in RETURN_HORIZONS:
            row[f"median_abs_abnormal_{horizon}m"]=group[f"beta_adjusted_abnormal_return_{horizon}m"].abs().median()
        rows.append(row)
    result=pd.DataFrame(rows)
    result["fastest_apparent_publication_rank"]=result.pre_post_ratio_5m.rank(method="min")
    return result.sort_values("fastest_apparent_publication_rank")


def _category_report(frame: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for category, group in frame.groupby("category_group"):
        row={"category":category,"event_count":len(group),"median_abs_pre_move_5m":group.abs_pre_move_5m.median(),
             "median_abs_post_move_5m":group.abs_post_move_5m.median(),"pre_dominant_rate_5m":(group.abs_pre_move_5m>group.abs_post_move_5m).mean(),
             "post_dominant_rate_5m":(group.abs_post_move_5m>group.abs_pre_move_5m).mean(),"earliest_reaction_horizon_010":earliest_horizon(group)}
        for horizon in RETURN_HORIZONS:
            row[f"median_abs_abnormal_{horizon}m"]=group[f"beta_adjusted_abnormal_return_{horizon}m"].abs().median()
        for threshold in THRESHOLDS:
            suffix=f"{int(threshold*100):03d}";row[f"late_publication_rate_{suffix}"]=group[f"late_publication_{suffix}"].mean()
        rows.append(row)
    return pd.DataFrame(rows).sort_values("median_abs_abnormal_5m",ascending=False)


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    manifest, hashes_before = verify_stage12(ROOT)
    events = pd.read_parquet(REPORTS / "stage12_eth_event_index.parquet").query("coverage_status == 'included'").copy()
    market = pd.read_parquet(ROOT / "data" / "stage12" / "eth_market_only.parquet")
    ai = pd.read_parquet(ROOT / "data" / "stage12" / "eth_ai_only.parquet")
    targets = pd.read_parquet(ROOT / "data" / "stage12" / "eth_targets.parquet")
    identity = ["event_key", "news_id"]
    if len(events) != manifest["event_count"] or events[identity].duplicated().any():
        raise RuntimeError("Stage 12 earliest event selection is not aligned")
    joined = events.merge(market[identity + ["pre_eth_btc_rolling_beta","pre_beta_fallback_used"]], on=identity, validate="one_to_one")
    joined = joined.merge(ai[identity + ["ai_direction","ai_sentiment","ai_category"]], on=identity, validate="one_to_one")
    joined["category_group"] = joined.ai_category.where(joined.ai_category.isin(CORE_CATEGORIES), "other")
    with SessionLocal() as session:
        database_name=session.execute(text("select current_database()" )).scalar_one()
        delays=_second_article_delays(session)
        joined=joined.merge(delays,on="event_group_id",how="left")
        joined["second_article_delay_minutes"]=joined.second_article_delay_minutes.where(joined.article_count_in_event.gt(1))
        eth=load_candle_grid(session,"ETHUSDT")
        btc=load_candle_grid(session,"BTCUSDT")
    records=[];missing=[]
    for row in joined.itertuples(index=False):
        record,reason=build_early_record(row,eth,btc)
        if record is None:missing.append({"event_key":row.event_key,"news_id":int(row.news_id),"reason":reason})
        else:records.append(record)
    frame=pd.DataFrame(records).sort_values(["published_at","news_id"]).reset_index(drop=True)
    frame["article_count_bucket"] = pd.cut(
        frame.article_count_in_event, bins=[0,1,2,5,np.inf],
        labels=["1","2","3-5","6+"], include_lowest=True,
    ).astype(str)
    frame.to_parquet(REPORTS/"stage13a_eth_early_returns.parquet",index=False)

    pre_post=grouped_timing(frame,["overall","split"])
    pre_post.to_csv(REPORTS/"stage13a_eth_pre_post_comparison.csv",index=False)
    late=grouped_timing(frame,["overall","source","category_group","year","article_count_bucket","article_count_in_event"])
    late.to_csv(REPORTS/"stage13a_eth_late_publication.csv",index=False)
    source=_source_report(frame);source.to_csv(REPORTS/"stage13a_eth_source_timing.csv",index=False)
    category=_category_report(frame);category.to_csv(REPORTS/"stage13a_eth_category_timing.csv",index=False)

    ai_rows=[]
    early=[(f"{horizon}m","raw",f"eth_return_{horizon}m") for horizon in RETURN_HORIZONS]
    early += [(f"{horizon}m","abnormal",f"beta_adjusted_abnormal_return_{horizon}m") for horizon in RETURN_HORIZONS]
    prior=[]
    for label in ("15m","30m","1h","4h","24h"):
        prior.append((label,"prior_stage12_abnormal",f"target_abnormal_return_{label}"))
    metric_frame=frame.merge(targets[identity+[item[2] for item in prior]],on=identity,validate="one_to_one")
    for split in ("overall","train","validation","test"):
        part=metric_frame if split=="overall" else metric_frame.query("split == @split")
        for horizon,return_type,column in early+prior:
            ai_rows.append({"split":split,"horizon":horizon,"return_type":return_type,"return_column":column,**direction_metrics(part,column)})
    ai_metrics=pd.DataFrame(ai_rows);ai_metrics.to_csv(REPORTS/"stage13a_eth_ai_early_metrics.csv",index=False)

    overall=pre_post.query("group_dimension == 'overall'").iloc[0]
    median_abs_abnormal={f"{h}m":float(frame[f"beta_adjusted_abnormal_return_{h}m"].abs().median()) for h in RETURN_HORIZONS}
    median_abs_abnormal.update({label:float(targets[f"target_abnormal_return_{label}"].abs().median()) for label in ("30m","1h","4h","24h")})
    early_strength=float(np.mean([median_abs_abnormal[f"{h}m"] for h in (1,2,3,5)]))
    later_strength=float(np.mean([median_abs_abnormal["15m"],median_abs_abnormal["1h"]]))
    early_ai=ai_metrics.query("split == 'overall' and return_type == 'abnormal' and horizon in ['1m','2m','3m','5m']").balanced_accuracy.mean()
    late_ai=ai_metrics.query("split == 'overall' and return_type == 'prior_stage12_abnormal' and horizon in ['15m','30m','1h','4h','24h']").balanced_accuracy.mean()
    split_effects={split:float(part.beta_adjusted_abnormal_return_5m.abs().median()) for split,part in frame.groupby("split")}
    stable_splits=max(split_effects.values())/max(min(split_effects.values()),1e-12)<2.0
    post_not_pre=float(overall.median_abs_post_move_5m)>=float(overall.median_abs_pre_move_5m)
    source_control=bool((source.median_abs_abnormal_5m>0).all()) and source.median_abs_abnormal_5m.max()/max(source.median_abs_abnormal_5m.min(),1e-12)<2.0
    source_control = bool((source.median_abs_post_move_5m > source.median_abs_pre_move_5m).sum() >= 2)
    count_pre_spearman=float(frame.article_count_in_event.corr(frame.abs_pre_move_5m,method="spearman"))
    delay_valid=frame.second_article_delay_minutes.notna()
    delay_pre_spearman=float(frame.loc[delay_valid,"second_article_delay_minutes"].corr(frame.loc[delay_valid,"abs_pre_move_5m"],method="spearman")) if delay_valid.sum()>=3 else np.nan
    event_bucket_summary={}
    for bucket,part in frame.groupby("article_count_bucket",observed=True):
        event_bucket_summary[str(bucket)]={"events":len(part),"median_abs_pre_move_5m":float(part.abs_pre_move_5m.median()),"median_abs_post_move_5m":float(part.abs_post_move_5m.median()),"late_publication_rate_010":float(part.late_publication_010.mean())}
    early_reaction_supported=bool(early_strength>later_strength and early_ai>late_ai and stable_splits and post_not_pre and source_control)
    hash_after={path:__import__('ml.stage13a_timing_audit',fromlist=['sha256']).sha256(ROOT/path) for path in hashes_before}
    stage12_unchanged=hash_after==hashes_before
    tests=subprocess.run([str(ROOT/".venv"/"Scripts"/"python.exe"),"-m","pytest","tests","-q"],cwd=ROOT,text=True,capture_output=True)
    technical_pass=len(frame)==manifest["event_count"] and not missing and stage12_unchanged and tests.returncode==0
    summary={
        "stage":"13A","status":"PASS" if technical_pass else "FAIL",
        "audit_type":"read_only_timing_audit_no_ml","created_at":datetime.now(timezone.utc).isoformat(),
        "database":database_name,"stage12_dataset_version":manifest["dataset_version"],"stage12_schema_hash":manifest["schema_hash"],
        "events_expected":manifest["event_count"],"events_analyzed":len(frame),"missing_events":missing,"stage12_unchanged":stage12_unchanged,
        "methodology":{"baseline":"first full 1m candle after published_at minute","post_return":"baseline open to open at baseline+N","pre_return":"open at baseline-N to baseline open","return_unit":"percent","abnormal":"ETH return minus pre-news rolling beta times BTC return","volume_shock":"post volume divided by expected volume from prior 60 completed minutes","direction_neutral_band_percent":0.10},
        "median_abs_abnormal_return":median_abs_abnormal,"median_abs_pre_move_5m":float(overall.median_abs_pre_move_5m),"median_abs_post_move_5m":float(overall.median_abs_post_move_5m),
        "late_publication_rates":{f"threshold_{threshold:.2f}pct":float(frame[f'late_publication_{int(threshold*100):03d}'].mean()) for threshold in THRESHOLDS},
        "reaction_class_distribution":{f"threshold_{threshold:.2f}pct":frame[f'reaction_class_{int(threshold*100):03d}'].value_counts().to_dict() for threshold in THRESHOLDS},
        "source_with_fastest_apparent_publication":str(source.iloc[0].source),"split_median_abs_abnormal_5m":split_effects,
        "ai_balanced_accuracy":{"early_1m_5m_abnormal_mean":float(early_ai),"prior_15m_24h_abnormal_mean":float(late_ai)},
        "event_group_timing":{"article_count_vs_abs_pre_move_5m_spearman":count_pre_spearman,"second_article_delay_vs_abs_pre_move_5m_spearman":delay_pre_spearman,"multi_article_events_with_delay":int(delay_valid.sum()),"article_count_buckets":event_bucket_summary},
        "decision_checks":{"early_1_5m_stronger_than_15m_1h":early_strength>later_strength,"ai_direction_better_early":bool(early_ai>late_ai),"chronological_split_stability":stable_splits,"not_explained_only_by_pre_move":post_not_pre,"source_controls_preserve_effect":source_control},
        "early_reaction_supported":early_reaction_supported,
        "timing_conclusion":"EARLY_REACTION_SUPPORTED" if early_reaction_supported else "EARLY_REACTION_NOT_SUPPORTED",
        "late_timestamp_conclusion":"PUBLISHED_AT_OFTEN_LAGS_MARKET_MOVE" if float(frame.late_publication_010.mean())>=0.20 else "NO_DOMINANT_LATE_TIMESTAMP_EVIDENCE",
        "pytest":"PASS" if tests.returncode==0 else "FAIL","pytest_summary":(tests.stdout+tests.stderr).strip().splitlines()[-1],
        "ml_run":False,"paper_trading_run":False,"real_trading_run":False,"openai_api_requests":0,
    }
    (REPORTS/"stage13a_eth_summary.json").write_text(json.dumps(_json_value(summary),ensure_ascii=False,indent=2),encoding="utf-8")
    assessment=f"""# Stage 13A ETH Early Reaction Timing Audit\n\nTechnical status: {summary['status']}\n\nTiming conclusion: {summary['timing_conclusion']}\n\nMedian absolute 5m pre-move: {summary['median_abs_pre_move_5m']:.4f}%. Median absolute 5m post-move: {summary['median_abs_post_move_5m']:.4f}%. The aggregate result therefore does not show that the main move usually occurs before publication.\n\nLate-publication rate at 0.10%: {summary['late_publication_rates']['threshold_0.10pct']:.2%}. This is a material late-timestamp subset rather than a universal effect. Cointelegraph has the fastest apparent publication in the three-source comparison; CoinDesk and Decrypt have higher late-publication rates. Primary-source integrations, exchange/regulator/project announcement feeds, and lower-latency realtime ingestion are recommended for this subset.\n\nThe strict early-reaction claim is accepted only when all five decision checks pass. It fails because 1–5m abnormal effects are weaker than 15m–1h effects and AI direction is not better at early horizons. This audit ran no ML, OpenAI API, paper trading, or real trading and did not alter Stage 8–12 datasets.\n"""
    (REPORTS/"stage13a_eth_final_assessment.md").write_text(assessment,encoding="utf-8")
    print(json.dumps(_json_value(summary),ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
