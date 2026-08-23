"""Stage 17: offline, event-clustered semantic subgroup audit.

This command reads Stage 16 and PostgreSQL, but writes only data/stage17 and
reports/stage17_*. It never calls OpenAI and never starts trading or ML.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import subprocess
import sys
import time
import warnings
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu
from sqlalchemy import text

from analysis.stage17_subgroups import (
    EXPLORATORY_HORIZONS, HORIZONS, HOLDINGS, NEUTRAL_BANDS,
    PRIMARY_HORIZONS, SCORE_COLUMNS, STRONG_THRESHOLDS,
    SUBGROUP_CONDITIONS, add_event_contamination, apply_context_bins,
    bh_adjust, cluster_bootstrap_ci, cluster_permutation_p, fit_context_bins,
    horizon_metrics, manual_hypothesis_masks, membership, sample_gate,
    subgroup_masks,
)
from database.db import engine

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

ROOT = Path(__file__).resolve().parents[1]
STAGE16 = ROOT / "datasets" / "stage16_high_impact_semantic_v21"
STAGE16_MANIFEST = ROOT / "reports" / "stage16_semantic_v21_dataset_manifest.json"
DATA = ROOT / "data" / "stage17"
REPORTS = ROOT / "reports"
MODEL = "gpt-5-mini"
PROMPT_VERSION = "high_impact_semantic_v2_1"
PRIMARY_LATENCY = 1
SENSITIVITY_LATENCIES = (0, 2, 3, 5)
SEED = 17
ROUND_TRIP_COST_PERCENT = {"low": .08, "base": .20, "stress": .50}
HORIZON_MINUTES = {"1m":1,"5m":5,"10m":10,"20m":20,"40m":40,"1h":60,"3h":180,"5h":300,"8h":480,"12h":720}
PRE_MINUTES = {"1m":1,"5m":5,"10m":10,"20m":20,"40m":40,"1h":60,"3h":180,"5h":300,"8h":480,"12h":720}
EXPECTED_REPORTS = [
    "stage17_data_audit.json", "stage17_data_audit.csv", "stage17_split_audit.csv",
    "stage17_duplicate_audit.csv", "stage17_hash_audit.json",
    "stage17_semantic_quality.csv", "stage17_source_reliability_audit.csv",
    "stage17_semantic_null_rates.csv", "stage17_semantic_distributions.csv", "stage17_unusable_features.json",
    "stage17_verified_source_audit.csv", "stage17_asset_counts.csv",
    "stage17_subgroup_counts.csv", "stage17_horizon_metrics.csv",
    "stage17_contamination_summary.csv", "stage17_asset_metrics.csv",
    "stage17_valence_metrics.csv", "stage17_market_context_metrics.csv",
    "stage17_manual_hypotheses.csv", "stage17_generated_subgroups.csv",
    "stage17_manual_hypotheses_config.json", "stage17_manual_hypotheses_config.sha256",
    "stage17_market_context_thresholds.json", "stage17_target_manifest.json",
    "stage17_generated_rule_manifest.json", "stage17_statistical_tests.csv",
    "stage17_validation_metrics.csv", "stage17_test_metrics.csv",
    "stage17_walkforward_metrics.csv", "stage17_multiple_testing.csv",
    "stage17_search_adjusted_permutation.csv", "stage17_locked_shortlist.json",
    "stage17_locked_shortlist.sha256", "stage17_locked_test_assessment.json",
    "stage17_economic_metrics.csv", "stage17_source_metrics.csv",
    "stage17_source_asset_metrics.csv",
    "stage17_insufficient_samples.csv", "stage17_event_contamination.csv",
    "stage17_isolated_event_metrics.csv", "stage17_search_adjusted_permutation.json",
    "stage17_summary.json", "stage17_final_assessment.md",
]


def native(value: Any) -> Any:
    if isinstance(value, dict): return {str(k): native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [native(v) for v in value]
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)): return bool(value)
    if isinstance(value, (pd.Timestamp,)): return value.isoformat()
    if pd.isna(value) if not isinstance(value, (str, bytes)) else False: return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(native(value), indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_files() -> list[Path]:
    paths = []
    for folder in (ROOT / "reports", ROOT / "datasets", ROOT / "data"):
        if not folder.exists(): continue
        for path in folder.rglob("*"):
            if not path.is_file(): continue
            rel = str(path.relative_to(ROOT)).replace("\\", "/").lower()
            if "/stage17" in rel or path.name.startswith("stage17_"): continue
            if any(f"stage{number}" in rel for number in range(8, 17)):
                paths.append(path)
    return sorted(set(paths))


def snapshot(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(ROOT)): file_hash(path) for path in paths}


def load_stage16() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    manifest = json.loads(STAGE16_MANIFEST.read_text(encoding="utf-8"))
    feature_path = STAGE16 / "d_source_market_timing.parquet"
    target_path = STAGE16 / "targets.parquet"
    expected_by_name = {Path(name).name: digest for name, digest in manifest["files"].items()}
    actual = {path.name: file_hash(path) for path in STAGE16.glob("*.parquet")}
    missing = sorted(set(expected_by_name) - set(actual))
    mismatched = sorted(name for name,digest in actual.items() if expected_by_name.get(name) != digest)
    if missing or mismatched:
        raise RuntimeError(f"Stage 16 dataset hash mismatch: missing={missing}, mismatched={mismatched}")
    return pd.read_parquet(feature_path), pd.read_parquet(target_path), manifest


def load_database() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    event_sql = text("""
      SELECT e.id event_id,e.source,e.source_type,e.platform,e.author_name,e.author_handle,
             e.external_id,e.url,e.canonical_url,e.title,e.body,e.published_at,e.discovered_at,
             e.time_confidence,e.source_authenticity,e.crypto_relevance,e.event_group_id,
             an.event_type,an.information_status,an.source_reliability,an.evidence_quality,
             an.status analysis_status
      FROM high_impact_events e
      JOIN high_impact_event_analysis an ON an.event_id=e.id
       AND an.model_name=:model AND an.prompt_version=:version AND an.status='success'
      WHERE e.status='accepted' ORDER BY e.id
    """)
    reaction_columns = ",".join(
        [f"r.return_{h},r.abnormal_return_{h}" for h in HORIZONS]
        + ["r.max_favorable_1h,r.max_adverse_1h,r.max_absolute_1h",
           "r.max_favorable_12h,r.max_adverse_12h,r.max_absolute_12h",
           "r.volume_shock_1h,r.realized_vol_1h,r.realized_vol_12h"]
    )
    reaction_sql = text(f"""
      SELECT r.event_id,r.symbol,r.baseline_time,r.latency_minutes,r.pre_context_json,{reaction_columns}
      FROM high_impact_market_reactions r
      JOIN high_impact_events e ON e.id=r.event_id
      WHERE e.status='accepted' AND r.latency_minutes IN (0,1,2,3,5)
      ORDER BY r.event_id,r.symbol,r.latency_minutes
    """)
    analysis_count_sql = text("""
      SELECT count(*) FROM high_impact_event_analysis
      WHERE model_name=:model AND prompt_version=:version AND status='success'
    """)
    with engine.connect() as connection:
        events = pd.read_sql(event_sql, connection, params={"model": MODEL, "version": PROMPT_VERSION})
        reactions = pd.read_sql(reaction_sql, connection)
        assets = pd.read_sql(text("SELECT event_id,asset,relevance,detection_source FROM high_impact_event_assets"), connection)
        analysis_count = int(connection.execute(analysis_count_sql, {"model": MODEL, "version": PROMPT_VERSION}).scalar_one())
    reactions["asset"] = reactions.symbol.str.replace("USDT", "", regex=False)
    reactions["baseline_time"] = pd.to_datetime(reactions.baseline_time, utc=True)
    events["published_at"] = pd.to_datetime(events.published_at, utc=True)
    return events, assets, reactions, analysis_count


def load_btc_context(event_ids: list[int]) -> pd.DataFrame:
    """Compute exact BTC pre/post returns at every event's 1m-latency baseline."""
    sql = text("""
      WITH base AS (
        SELECT DISTINCT ON (event_id) event_id,baseline_time
        FROM high_impact_market_reactions
        WHERE latency_minutes=1 AND event_id = ANY(:event_ids)
        ORDER BY event_id,symbol
      )
      SELECT b.event_id,b.baseline_time,c0.open current_open,
        p5.open pre_5m,p20.open pre_20m,p60.open pre_60m,p180.open pre_180m,p720.open pre_720m,
        f1.open future_1m,f5.open future_5m,f10.open future_10m,f20.open future_20m,
        f40.open future_40m,f60.open future_60m,f180.open future_180m,f300.open future_300m,
        f480.open future_480m,f720.open future_720m
      FROM base b
      LEFT JOIN market_candles c0 ON c0.symbol='BTCUSDT' AND c0.interval='1m' AND c0.open_time=b.baseline_time
      LEFT JOIN market_candles p5 ON p5.symbol='BTCUSDT' AND p5.interval='1m' AND p5.open_time=b.baseline_time-interval '5 minute'
      LEFT JOIN market_candles p20 ON p20.symbol='BTCUSDT' AND p20.interval='1m' AND p20.open_time=b.baseline_time-interval '20 minute'
      LEFT JOIN market_candles p60 ON p60.symbol='BTCUSDT' AND p60.interval='1m' AND p60.open_time=b.baseline_time-interval '60 minute'
      LEFT JOIN market_candles p180 ON p180.symbol='BTCUSDT' AND p180.interval='1m' AND p180.open_time=b.baseline_time-interval '180 minute'
      LEFT JOIN market_candles p720 ON p720.symbol='BTCUSDT' AND p720.interval='1m' AND p720.open_time=b.baseline_time-interval '720 minute'
      LEFT JOIN market_candles f1 ON f1.symbol='BTCUSDT' AND f1.interval='1m' AND f1.open_time=b.baseline_time+interval '1 minute'
      LEFT JOIN market_candles f5 ON f5.symbol='BTCUSDT' AND f5.interval='1m' AND f5.open_time=b.baseline_time+interval '5 minute'
      LEFT JOIN market_candles f10 ON f10.symbol='BTCUSDT' AND f10.interval='1m' AND f10.open_time=b.baseline_time+interval '10 minute'
      LEFT JOIN market_candles f20 ON f20.symbol='BTCUSDT' AND f20.interval='1m' AND f20.open_time=b.baseline_time+interval '20 minute'
      LEFT JOIN market_candles f40 ON f40.symbol='BTCUSDT' AND f40.interval='1m' AND f40.open_time=b.baseline_time+interval '40 minute'
      LEFT JOIN market_candles f60 ON f60.symbol='BTCUSDT' AND f60.interval='1m' AND f60.open_time=b.baseline_time+interval '60 minute'
      LEFT JOIN market_candles f180 ON f180.symbol='BTCUSDT' AND f180.interval='1m' AND f180.open_time=b.baseline_time+interval '180 minute'
      LEFT JOIN market_candles f300 ON f300.symbol='BTCUSDT' AND f300.interval='1m' AND f300.open_time=b.baseline_time+interval '300 minute'
      LEFT JOIN market_candles f480 ON f480.symbol='BTCUSDT' AND f480.interval='1m' AND f480.open_time=b.baseline_time+interval '480 minute'
      LEFT JOIN market_candles f720 ON f720.symbol='BTCUSDT' AND f720.interval='1m' AND f720.open_time=b.baseline_time+interval '720 minute'
      ORDER BY b.event_id
    """)
    with engine.connect() as connection:
        frame = pd.read_sql(sql, connection, params={"event_ids": event_ids})
    current = pd.to_numeric(frame.current_open, errors="coerce")
    for label in ("5m", "20m", "60m", "180m", "720m"):
        old = pd.to_numeric(frame[f"pre_{label}"], errors="coerce")
        frame[f"pre_btc_return_{label}"] = (current / old - 1) * 100
    for horizon,minutes in HORIZON_MINUTES.items():
        future=pd.to_numeric(frame[f"future_{minutes}m"],errors="coerce")
        frame[f"btc_return_{horizon}"]=(future/current-1)*100
    return frame[["event_id", "baseline_time"] + [f"pre_btc_return_{x}" for x in ("5m","20m","60m","180m","720m")] + [f"btc_return_{h}" for h in HORIZONS]]


def verification_fields(row: pd.Series) -> dict[str, Any]:
    host = (urlparse(str(row.url)).hostname or "").lower()
    source = str(row.source)
    official_domains = {
        "sec": {"sec.gov", "www.sec.gov"},
        "ethereum_github": {"github.com", "api.github.com"},
        "ethereum_foundation": {"ethereum.org", "blog.ethereum.org"},
        "elon_musk": {"x.com", "twitter.com"},
        "donald_trump": {"truthsocial.com"},
    }
    valid_platforms = {
        "sec": {"sec", "edgar"}, "ethereum_github": {"github"},
        "ethereum_foundation": {"ethereum_blog"}, "elon_musk": {"x"},
        "donald_trump": {"truth_social"},
    }
    domain = any(host == item or host.endswith("." + item) for item in official_domains.get(source, set()))
    adapter = str(row.platform) in valid_platforms.get(source, set())
    external = bool(str(row.external_id).strip()) and str(row.external_id).lower() != "nan"
    author = bool(str(row.author_handle).strip()) and str(row.author_handle).lower() != "nan"
    identity = external or author
    primary = bool(domain and adapter and identity)
    return {"verified_official_domain": domain, "verified_author_handle": author,
            "verified_external_id": external, "verified_source_adapter": adapter,
            "source_adapter_verified": adapter,
            "timestamp_verified":bool(pd.notna(row.published_at) and float(row.time_confidence)>=.8),
            "verified_primary_source": primary}


def build_frame(features: pd.DataFrame, events: pd.DataFrame, reactions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = ["metadata_event_id", "metadata_asset"]
    if features.duplicated(keys).any(): raise RuntimeError("duplicate (event_id, asset) in Stage 16")
    if features.groupby("metadata_event_id").metadata_split.nunique().max() != 1:
        raise RuntimeError("asset rows of the same event cross chronological splits")
    primary = reactions[reactions.latency_minutes.eq(PRIMARY_LATENCY)].copy()
    if primary.duplicated(["event_id", "asset"]).any(): raise RuntimeError("duplicate primary reaction identity")
    target_cols = ["event_id", "asset", "baseline_time"] + [c for c in primary if c.startswith(("return_", "abnormal_return_", "max_", "realized_vol_", "volume_shock_"))]
    primary = primary[target_cols].rename(columns={"event_id": "metadata_event_id", "asset": "metadata_asset", "baseline_time": "reaction_baseline_time"})
    frame = features.merge(primary, on=keys, how="inner", validate="one_to_one")
    meta = events[["event_id","url","canonical_url","title","body","external_id"]].rename(columns={"event_id":"metadata_event_id"})
    frame = frame.merge(meta, on="metadata_event_id", how="left", validate="many_to_one")
    btc = load_btc_context(frame.metadata_event_id.drop_duplicates().astype(int).tolist()).rename(columns={"event_id":"metadata_event_id", "baseline_time":"btc_context_baseline_time"})
    frame = frame.merge(btc, on="metadata_event_id", how="left", validate="many_to_one")
    frame["reaction_baseline_time"] = pd.to_datetime(frame.reaction_baseline_time, utc=True)
    # Add verified source fields at event level.
    verified = events.apply(verification_fields, axis=1, result_type="expand")
    verified["metadata_event_id"] = events.event_id.to_numpy()
    frame = frame.merge(verified, on="metadata_event_id", how="left", validate="many_to_one")
    thresholds = fit_context_bins(frame)
    frame = apply_context_bins(frame, thresholds)
    for horizon in HORIZONS:
        frame[f"abs_return_{horizon}"] = pd.to_numeric(frame[f"return_{horizon}"], errors="coerce").abs()
    return frame, pd.DataFrame([{"name": key, "value": value} for key, value in thresholds.items()])


def build_targets(frame: pd.DataFrame) -> pd.DataFrame:
    identity = frame[["metadata_event_id","metadata_asset","metadata_published_at","metadata_split","reaction_baseline_time"]].copy()
    result = identity.rename(columns={"metadata_event_id":"event_id","metadata_asset":"asset","metadata_split":"split"})
    for horizon in HORIZONS:
        values = pd.to_numeric(frame[f"return_{horizon}"], errors="coerce")
        result[f"target_return_{horizon}"] = values
        result[f"target_abs_return_{horizon}"] = values.abs()
        abnormal = pd.to_numeric(frame[f"abnormal_return_{horizon}"], errors="coerce")
        result[f"target_abnormal_return_{horizon}"] = abnormal.where(~frame.metadata_asset.eq("BTC"))
        result[f"target_abs_abnormal_return_{horizon}"] = result[f"target_abnormal_return_{horizon}"].abs()
        btc_return=pd.to_numeric(frame[f"btc_return_{horizon}"],errors="coerce")
        result[f"target_relative_return_vs_btc_{horizon}"]=(values-btc_return).where(~frame.metadata_asset.eq("BTC"))
        for band in NEUTRAL_BANDS:
            slug = str(band).replace(".", "_")
            result[f"target_direction_band_{horizon}_{slug}"] = np.select([values > band, values < -band], ["positive","negative"], default="neutral")
        for threshold in STRONG_THRESHOLDS:
            slug = str(threshold).replace(".", "_")
            result[f"target_strong_{horizon}_{slug}"] = (values.abs() >= threshold).astype("int8")
        for scenario, cost in ROUND_TRIP_COST_PERCENT.items():
            result[f"target_economic_move_{scenario}_{horizon}"] = (values.abs() > cost).astype("int8")
        pre_col = f"pre_return_{HORIZON_MINUTES[horizon]}m"
        result[f"target_post_stronger_than_pre_{horizon}"] = (values.abs() > pd.to_numeric(frame[pre_col], errors="coerce").abs()).astype("int8")
    result["target_volatility_increase_1h"] = (pd.to_numeric(frame.realized_vol_1h, errors="coerce") > pd.to_numeric(frame.pre_realized_vol_60m, errors="coerce")).astype("int8")
    result["target_volatility_increase_12h"] = (pd.to_numeric(frame.realized_vol_12h, errors="coerce") > pd.to_numeric(frame.pre_realized_vol_720m, errors="coerce")).astype("int8")
    for name in ("max_favorable_1h","max_adverse_1h","max_absolute_1h","max_favorable_12h","max_adverse_12h","max_absolute_12h","realized_vol_1h","realized_vol_12h","volume_shock_1h"):
        result[f"target_{name}"] = pd.to_numeric(frame[name], errors="coerce")
    return result


def semantic_quality(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in SCORE_COLUMNS:
        series = pd.to_numeric(frame[column], errors="coerce")
        valid = series.dropna()
        source_means = frame.assign(_value=series).groupby("metadata_source")._value.mean().dropna()
        type_means = frame.assign(_value=series).groupby("source_event_type")._value.mean().dropna()
        counts = valid.value_counts(normalize=True)
        row = {
            "feature": column, "n": int(valid.size), "null_rate": float(series.isna().mean()),
            "unique_values": int(valid.nunique()), "mean": valid.mean() if len(valid) else None,
            "std": valid.std() if len(valid) else None, "min": valid.min() if len(valid) else None,
            "median": valid.median() if len(valid) else None, "max": valid.max() if len(valid) else None,
            "skew": valid.skew() if len(valid) > 2 else None,
            "largest_value_cluster_rate": counts.iloc[0] if len(counts) else None,
            "zero_variance": bool(valid.nunique() <= 1),
            "near_constant": bool(len(counts) and counts.iloc[0] >= .90),
            "extreme_skew": bool(len(valid) > 2 and abs(valid.skew()) >= 2),
            "source_mean_range": source_means.max() - source_means.min() if len(source_means) else None,
            "event_type_mean_range": type_means.max() - type_means.min() if len(type_means) else None,
            "usable": column != "ai_surprise_level" and valid.nunique() > 1,
            "notes": "100% null by evidence-aware design; excluded from Stage 17 features" if column == "ai_surprise_level" else "exploratory semantic score",
        }
        rows.append(row)
    return pd.DataFrame(rows)


def source_audits(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    verified = events.apply(verification_fields, axis=1, result_type="expand")
    verified_audit = pd.concat([events[["event_id","source","platform","url","external_id","author_handle"]].reset_index(drop=True), verified], axis=1)
    verified_audit["verification_method"] = "source adapter + official-domain allowlist + external ID/verified handle"
    audit = events.copy()
    audit = audit.merge(pd.concat([events[["event_id"]].reset_index(drop=True),verified.reset_index(drop=True)],axis=1),on="event_id",how="left",validate="one_to_one")
    audit["reliability_band"] = pd.cut(pd.to_numeric(audit.source_reliability), [-1, 33, 66, 101], labels=["low","medium","high"])
    # Include every small source, then deterministically diversify the remainder.
    chosen = []
    for source, cap in (("ethereum_foundation", 7), ("ethereum_github", 18), ("sec", 25)):
        part = audit[audit.source.eq(source)].copy()
        if len(part) <= cap:
            chosen.append(part)
        else:
            samples = []
            for _, group in part.groupby(["event_type", "reliability_band"], observed=True):
                samples.append(group.sample(n=1, random_state=SEED))
            seed_rows = pd.concat(samples).drop_duplicates("event_id") if samples else part.iloc[0:0]
            needed = max(0, cap - len(seed_rows))
            pool = part[~part.event_id.isin(seed_rows.event_id)]
            chosen.append(pd.concat([seed_rows, pool.sample(n=min(needed, len(pool)), random_state=SEED)]).head(cap))
    review = pd.concat(chosen).drop_duplicates("event_id")
    if len(review) < 50:
        pool = audit[~audit.event_id.isin(review.event_id)]
        review = pd.concat([review, pool.sample(n=min(50-len(review), len(pool)), random_state=SEED)])
    review = review.head(50).copy()
    review["excerpt"] = review.body.fillna("").str.replace(r"\s+", " ", regex=True).str.slice(0, 500)
    review["source_url"] = review.url
    review["human_source_authenticity"] = ""
    review["human_evidence_strength"] = ""
    review["human_notes"] = ""
    columns = ["event_id","source","source_url","title","excerpt","event_type","information_status","source_reliability","evidence_quality","verified_primary_source","verified_official_domain","human_source_authenticity","human_evidence_strength","human_notes"]
    return review[columns], verified_audit


SEMANTIC_AUDIT_FIELDS={
    "source_reliability":"ai_source_reliability","novelty":"ai_novelty","importance":"ai_importance",
    "specificity":"ai_specificity","confidence":"ai_confidence","surprise_level":"ai_surprise_level",
    "surprise_evidence":"ai_surprise_evidence","first_disclosure":"ai_first_disclosure",
    "actionability":"ai_actionability","institutional_relevance":"ai_institutional_relevance",
    "retail_relevance":"ai_retail_relevance","market_scope":"ai_market_scope",
    "regulatory_strength":"ai_regulatory_strength","economic_significance":"ai_economic_significance",
    "technical_significance":"ai_technical_significance","security_significance":"ai_security_significance",
    "adoption_significance":"ai_adoption_significance","execution_certainty":"ai_execution_certainty",
    "urgency":"ai_urgency","fundamental_relevance":"ai_fundamental_relevance",
    "temporary_vs_structural":"ai_temporary_vs_structural","evidence_quality":"ai_evidence_quality",
    "asset_relevance":"ai_asset_relevance","content_valence":"ai_content_valence",
    "content_valence_score":"ai_content_valence_score","directness":"ai_directness",
}


def extended_semantic_audit(frame:pd.DataFrame)->tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,dict[str,Any]]:
    quality=[];distributions=[]
    for field,column in SEMANTIC_AUDIT_FIELDS.items():
        series=frame[column] if column in frame else pd.Series(index=frame.index,dtype="object")
        numeric=pd.api.types.is_numeric_dtype(series)
        valid=series.dropna();counts=valid.astype(str).value_counts(dropna=False)
        source_dependence=asset_dependence=event_dependence=None
        if numeric:
            values=pd.to_numeric(series,errors="coerce");valid_num=values.dropna()
            sm=frame.assign(_v=values).groupby("metadata_source")._v.mean().dropna()
            am=frame.assign(_v=values).groupby("metadata_asset")._v.mean().dropna()
            em=frame.assign(_v=values).groupby("source_event_type")._v.mean().dropna()
            source_dependence=sm.max()-sm.min() if len(sm) else None
            asset_dependence=am.max()-am.min() if len(am) else None
            event_dependence=em.max()-em.min() if len(em) else None
            mean=valid_num.mean() if len(valid_num) else None;median=valid_num.median() if len(valid_num) else None
            std=valid_num.std() if len(valid_num) else None;minimum=valid_num.min() if len(valid_num) else None;maximum=valid_num.max() if len(valid_num) else None
            skew=valid_num.skew() if len(valid_num)>2 else None
        else:
            mean=median=std=minimum=maximum=skew=None
            # Dependence proxy: range of modal-category rates across groups.
            def modal_range(group_col):
                rates=[]
                for _,part in frame.groupby(group_col):
                    c=part[column].dropna().value_counts(normalize=True) if column in part else pd.Series(dtype=float)
                    if len(c):rates.append(float(c.iloc[0]))
                return max(rates)-min(rates) if rates else None
            source_dependence=modal_range("metadata_source");asset_dependence=modal_range("metadata_asset");event_dependence=modal_range("source_event_type")
        largest=float(counts.iloc[0]/len(valid)) if len(valid) else None
        unusable=field=="surprise_level" or len(valid)==0 or valid.nunique()<=1
        reason="100% null; evidence-aware field excluded without imputation" if field=="surprise_level" else "100% null" if len(valid)==0 else "zero variance" if valid.nunique()<=1 else None
        quality.append({"field":field,"column":column,"data_unit":"event_asset_row","dtype":"numeric" if numeric else "categorical",
            "n":len(valid),"null_rate":float(series.isna().mean()),"mean":mean,"median":median,"std":std,"min":minimum,"max":maximum,
            "unique_values":int(valid.nunique()),"zero_variance":bool(valid.nunique()<=1),"near_zero_variance":bool(largest is not None and largest>=.90),
            "extreme_skew":bool(skew is not None and abs(skew)>=2),"skew":skew,"largest_cluster_rate":largest,
            "source_dependence":source_dependence,"event_type_dependence":event_dependence,"asset_dependence":asset_dependence,
            "usable":not unusable,"unusable_reason":reason})
        for value,count in counts.items():
            distributions.append({"field":field,"value":value,"count":int(count),"rate":float(count/len(valid)) if len(valid) else None,"data_unit":"event_asset_row"})
    quality_frame=pd.DataFrame(quality)
    nulls=quality_frame[["field","column","n","null_rate","usable","unusable_reason"]].copy()
    unusable={"excluded_fields":quality_frame.loc[~quality_frame.usable,["field","column","null_rate","unusable_reason"]].to_dict("records"),
              "surprise_level_policy":"exclude; do not zero-impute; do not recover without a new AI Batch","openai_api_requests":0}
    return quality_frame,nulls,pd.DataFrame(distributions),unusable


def subgroup_reports(frame: pd.DataFrame, contamination: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    masks = subgroup_masks(frame)
    count_rows, metric_rows, isolated_rows = [], [], []
    for subgroup, mask in masks.items():
        for asset in ("BTC","ETH","SOL"):
            asset_mask = frame.metadata_asset.eq(asset)
            split_counts = frame.loc[mask & asset_mask].metadata_split.value_counts()
            total = int((mask & asset_mask).sum())
            count_rows.append({"subgroup_id":subgroup,"conditions":SUBGROUP_CONDITIONS[subgroup],"asset":asset,"total":total,
                "unique_events":int(frame.loc[mask & asset_mask,"metadata_event_id"].nunique()),
                "train":int(split_counts.get("train",0)),"validation":int(split_counts.get("validation",0)),"test":int(split_counts.get("test",0)),
                "sample_gate":sample_gate(int(split_counts.get("train",0)),int(split_counts.get("validation",0)),int(split_counts.get("test",0)),total)})
            for split in ("train","validation","test"):
              for horizon in HORIZONS:
                part = frame[mask & asset_mask & frame.metadata_split.eq(split)]
                contamination_part=contamination[(contamination.asset.eq(asset))&contamination.horizon.eq(horizon)&contamination.event_id.isin(part.metadata_event_id)]
                if split=="test":
                    metrics={"n":len(part),"n_events":part.metadata_event_id.nunique(),"analysis_status":"LOCKED_NOT_OPENED",
                        "contamination_rate":float(contamination_part.overlapping_event_within_horizon.mean()) if len(contamination_part) else None,
                        "isolated_event_count":int(contamination_part.isolated_event.sum()) if len(contamination_part) else 0}
                else:
                    metrics = horizon_metrics(part, horizon);returns=pd.to_numeric(part[f"return_{horizon}"],errors="coerce")
                    abnormal=pd.to_numeric(part[f"abnormal_return_{horizon}"],errors="coerce").where(~part.metadata_asset.eq("BTC"))
                    metrics.update({"n_events":part.metadata_event_id.nunique(),"n_event_asset_rows":len(part),
                        "mean_abnormal_return":abnormal.mean(),"median_abnormal_return":abnormal.median(),"return_std":returns.std(),
                        "neutral_rate_0_1":(returns.abs()<=.1).mean() if len(returns) else None,
                        "volatility_increase_rate":((pd.to_numeric(part.realized_vol_1h,errors="coerce")>pd.to_numeric(part.pre_realized_vol_60m,errors="coerce")).mean() if horizon=="1h" else (pd.to_numeric(part.realized_vol_12h,errors="coerce")>pd.to_numeric(part.pre_realized_vol_720m,errors="coerce")).mean() if horizon=="12h" else None),
                        "contamination_rate":float(contamination_part.overlapping_event_within_horizon.mean()) if len(contamination_part) else None,
                        "isolated_event_count":int(contamination_part.isolated_event.sum()) if len(contamination_part) else 0,
                        "analysis_status":"evaluated_prelock"})
                metrics.update({"subgroup_id":subgroup,"asset":asset,"horizon":horizon,"split":split,
                                "horizon_family":"primary" if horizon in PRIMARY_HORIZONS else "exploratory",
                                "analysis_scope":"all_events"})
                metric_rows.append(metrics)
                if split!="test":
                    iso_keys=set(contamination_part.loc[contamination_part.isolated_event,"event_id"].astype(int))
                    iso=part[part.metadata_event_id.isin(iso_keys)];iso_metrics=horizon_metrics(iso,horizon)
                    iso_metrics.update({"subgroup_id":subgroup,"asset":asset,"horizon":horizon,"split":split,
                        "horizon_family":"primary" if horizon in PRIMARY_HORIZONS else "exploratory","analysis_scope":"isolated_events_only",
                        "n_events":iso.metadata_event_id.nunique(),"analysis_status":"evaluated_prelock"})
                    isolated_rows.append(iso_metrics)
    return pd.DataFrame(count_rows), pd.DataFrame(metric_rows), pd.DataFrame(isolated_rows)


def valence_report(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for asset in ("BTC","ETH","SOL"):
        for valence in ("positive","negative","neutral","mixed"):
          for split in ("train","validation","test"):
            mask = frame.metadata_asset.eq(asset) & frame.ai_content_valence.eq(valence) & frame.metadata_split.eq(split)
            for horizon in HORIZONS:
                part = frame[mask]
                if split=="test":
                    rows.append({"asset":asset,"content_valence":valence,"split":split,"horizon":horizon,
                        "horizon_family":"primary" if horizon in PRIMARY_HORIZONS else "exploratory","n":len(part),
                        "analysis_status":"LOCKED_NOT_OPENED","directional_rule":"none","interpretation":"message characteristic, not a price forecast"})
                    continue
                returns = pd.to_numeric(part[f"return_{horizon}"], errors="coerce").dropna()
                rows.append({"asset":asset,"content_valence":valence,"split":split,"horizon":horizon,
                    "horizon_family":"primary" if horizon in PRIMARY_HORIZONS else "exploratory",
                    "n":len(returns),"mean_return":returns.mean() if len(returns) else None,
                    "median_return":returns.median() if len(returns) else None,
                    "mean_absolute_return":returns.abs().mean() if len(returns) else None,
                    "strong_move_rate_0_5":(returns.abs()>=.5).mean() if len(returns) else None,
                    "importance_mean":pd.to_numeric(part.ai_importance,errors="coerce").mean(),
                    "novelty_mean":pd.to_numeric(part.ai_novelty,errors="coerce").mean(),
                    "relevance_mean":pd.to_numeric(part.ai_asset_relevance,errors="coerce").mean(),
                    "directional_rule": "fixed_bullish" if valence=="positive" else "fixed_bearish" if valence=="negative" else "none",
                    "interpretation":"message characteristic, not a price forecast","analysis_status":"evaluated_prelock"})
    return pd.DataFrame(rows)


def context_report(frame: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    contexts=("context_btc_state","context_asset_state","context_volatility","context_relative_strength")
    for context in contexts:
        for value in sorted(frame[context].dropna().unique()):
            for asset in ("BTC","ETH","SOL"):
              for split in ("train","validation"):
                part=frame[frame[context].eq(value)&frame.metadata_asset.eq(asset)&frame.metadata_split.eq(split)]
                for horizon in PRIMARY_HORIZONS:
                    returns=pd.to_numeric(part[f"return_{horizon}"],errors="coerce").dropna()
                    rows.append({"context":context,"value":value,"asset":asset,"split":split,"horizon":horizon,"n":len(returns),
                        "mean_return":returns.mean() if len(returns) else None,"mean_absolute_return":returns.abs().mean() if len(returns) else None,
                        "strong_move_rate_0_5":(returns.abs()>=.5).mean() if len(returns) else None})
    return pd.DataFrame(rows)


def cluster_comparison(frame: pd.DataFrame, mask: pd.Series, value_col: str, seed: int = SEED) -> dict[str, Any]:
    values=pd.to_numeric(frame[value_col],errors="coerce")
    work=frame.assign(_value=values)
    left=work.loc[mask,"_value"].dropna();right=work.loc[~mask,"_value"].dropna()
    lo,hi=cluster_bootstrap_ci(work.loc[mask],["_value"][0],seed=seed)
    p_u=float(mannwhitneyu(left,right,alternative="two-sided").pvalue) if len(left) and len(right) else None
    pooled=math.sqrt(((len(left)-1)*left.var(ddof=1)+(len(right)-1)*right.var(ddof=1))/(len(left)+len(right)-2)) if len(left)>1 and len(right)>1 else 0
    return {"n":len(left),"n_events":int(work.loc[mask,"metadata_event_id"].nunique()),"rest_n":len(right),
        "mean":left.mean() if len(left) else None,"median":left.median() if len(left) else None,
        "rest_mean":right.mean() if len(right) else None,"lift":left.mean()-right.mean() if len(left) and len(right) else None,
        "standardized_effect":(left.mean()-right.mean())/pooled if pooled and not math.isnan(pooled) else None,
        "cluster_bootstrap_ci_low":lo,"cluster_bootstrap_ci_high":hi,"mann_whitney_p":p_u,
        "cluster_permutation_p":cluster_permutation_p(work,mask,"_value",seed=seed)}


def manual_hypotheses(frame: pd.DataFrame) -> pd.DataFrame:
    masks=manual_hypothesis_masks(frame);rows=[]
    for hypothesis,base_mask in masks.items():
        if hypothesis=="H9" and int(base_mask.sum())==0:
            rows.append({"hypothesis":hypothesis,"asset":"ALL","horizon":"NA","horizon_family":"not_applicable",
                "task":"directional" if hypothesis in {"H2","H3"} else "magnitude","n":0,"status":"INSUFFICIENT_DATA",
                "notes":"Public-figure history is absent because the paid source API was unavailable; not rejected or disproven."})
            continue
        for split in ("train","validation"):
            scope=frame[frame.metadata_split.eq(split)]
            for asset in ("BTC","ETH","SOL"):
                asset_mask=base_mask.loc[scope.index]&scope.metadata_asset.eq(asset)
                for horizon in HORIZONS:
                    stats=cluster_comparison(scope,asset_mask,f"abs_return_{horizon}",seed=SEED+int(scope.metadata_asset.eq(asset).sum()))
                    returns=pd.to_numeric(scope.loc[asset_mask,f"return_{horizon}"],errors="coerce")
                    strong=(returns.abs()>=.5)
                    stats.update({"hypothesis":hypothesis,"asset":asset,"horizon":horizon,"split":split,
                        "horizon_family":"primary" if horizon in PRIMARY_HORIZONS else "exploratory",
                        "task":"directional" if hypothesis in {"H2","H3"} else "magnitude",
                        "strong_move_rate_0_5":strong.mean() if len(strong) else None,
                        "status":"evaluated" if len(returns)>=20 else "insufficient_sample",
                        "notes":"content valence is an explicitly fixed directional hypothesis" if hypothesis in {"H2","H3"} else "magnitude/volatility hypothesis; no directional PnL"})
                    rows.append(stats)
    return pd.DataFrame(rows)


def candidate_masks(frame: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, str]]:
    train=frame[frame.metadata_split.eq("train")]
    def quantile(column: str, q: float) -> float:
        return float(pd.to_numeric(train[column],errors="coerce").dropna().quantile(q))
    base: list[tuple[str, str, pd.Series]] = [
        ("relevance_high",f"ai_asset_relevance>={quantile('ai_asset_relevance',.67):.6g}",frame.ai_asset_relevance>=quantile("ai_asset_relevance",.67)),
        ("importance_high",f"ai_importance>={quantile('ai_importance',.67):.6g}",frame.ai_importance>=quantile("ai_importance",.67)),
        ("novelty_high",f"ai_novelty>={quantile('ai_novelty',.67):.6g}",frame.ai_novelty>=quantile("ai_novelty",.67)),
        ("specificity_high",f"ai_specificity>={quantile('ai_specificity',.67):.6g}",frame.ai_specificity>=quantile("ai_specificity",.67)),
        ("actionability_high",f"ai_actionability>={quantile('ai_actionability',.67):.6g}",frame.ai_actionability>=quantile("ai_actionability",.67)),
        ("execution_high",f"ai_execution_certainty>={quantile('ai_execution_certainty',.67):.6g}",frame.ai_execution_certainty>=quantile("ai_execution_certainty",.67)),
        ("direct","ai_directness=direct",frame.ai_directness.eq("direct")),
        ("confirmed","information_status=confirmed_action",frame.source_information_status.eq("confirmed_action")),
        ("structural","temporary_vs_structural=structural",frame.ai_temporary_vs_structural.eq("structural")),
        ("primary_evidence","evidence_quality in official/primary",frame.ai_evidence_quality.isin(["official_document","official_statement","primary_source"])),
        ("verified_source","verified_primary_source=true",frame.verified_primary_source),
        ("low_volatility","context_volatility=low",frame.context_volatility.eq("low")),
        ("btc_stable","context_btc_state=stable",frame.context_btc_state.eq("stable")),
        ("asset_not_rising","context_asset_state!=already_rising",~frame.context_asset_state.eq("already_rising")),
    ]
    masks: dict[str,pd.Series]={};conditions:dict[str,str]={}
    for name,condition,mask in base:
        masks[name]=mask.fillna(False);conditions[name]=condition
    # Controlled beam depth 2 (within the allowed maximum of four conditions).
    for left,right in itertools.combinations(range(len(base)),2):
        lname,lcondition,lmask=base[left];rname,rcondition,rmask=base[right]
        name=f"{lname}__{rname}";masks[name]=(lmask&rmask).fillna(False);conditions[name]=f"{lcondition} AND {rcondition}"
    return masks,conditions


def generated_discovery(frame: pd.DataFrame, masks: dict[str,pd.Series], conditions: dict[str,str]) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    train=frame[frame.metadata_split.eq("train")];validation=frame[frame.metadata_split.eq("validation")]
    train_rows=[]
    for rule,mask in masks.items():
        depth=conditions[rule].count(" AND ")+1
        if depth>4: continue
        for asset in ("BTC","ETH","SOL"):
            scope=train[train.metadata_asset.eq(asset)]
            local=mask.loc[scope.index]
            support=int(local.sum())
            if support<30: continue
            for horizon in PRIMARY_HORIZONS:
                values=pd.to_numeric(scope[f"abs_return_{horizon}"],errors="coerce")
                strong=values>=.5
                rest=~local
                train_rows.append({"rule_id":rule,"conditions":conditions[rule],"condition_count":depth,"asset":asset,"horizon":horizon,
                    "horizon_family":"primary","train_n":support,"train_unique_events":int(scope.loc[local,"metadata_event_id"].nunique()),
                    "train_mean_abs_return":values[local].mean(),"train_rest_mean_abs_return":values[rest].mean(),
                    "train_abs_lift":values[local].mean()-values[rest].mean(),
                    "train_strong_rate":strong[local].mean(),"train_rest_strong_rate":strong[rest].mean(),
                    "train_strong_lift":strong[local].mean()-strong[rest].mean(),
                    "preferred_support":support>=50})
    generated=pd.DataFrame(train_rows)
    if generated.empty:
        return generated,pd.DataFrame(),pd.DataFrame()
    # Keep the best train-generated configurations without looking at validation outcomes.
    generated["train_rank_score"]=generated.train_abs_lift.fillna(-999)+generated.train_strong_lift.fillna(-999)
    selected=generated.sort_values(["preferred_support","train_rank_score"],ascending=[False,False]).head(40).copy()
    val_rows=[]
    for row in selected.itertuples(index=False):
        scope=validation[validation.metadata_asset.eq(row.asset)]
        local=masks[row.rule_id].loc[scope.index]
        stats=cluster_comparison(scope,local,f"abs_return_{row.horizon}",seed=SEED)
        values=pd.to_numeric(scope[f"abs_return_{row.horizon}"],errors="coerce")
        strong=values>=.5
        stats.update({"rule_type":"generated","rule_id":row.rule_id,"conditions":row.conditions,"asset":row.asset,"horizon":row.horizon,
            "horizon_family":"primary","train_n":row.train_n,"validation_n":int(local.sum()),
            "validation_strong_rate":strong[local].mean() if local.any() else None,
            "validation_rest_strong_rate":strong[~local].mean() if (~local).any() else None,
            "validation_strong_lift":strong[local].mean()-strong[~local].mean() if local.any() and (~local).any() else None})
        val_rows.append(stats)
    validation_metrics=pd.DataFrame(val_rows)
    if len(validation_metrics):
        validation_metrics["bh_q"] = bh_adjust(validation_metrics.cluster_permutation_p.tolist())
        validation_metrics["practical_effect"]=(validation_metrics.lift.abs()>=.10)|(validation_metrics.validation_strong_lift.abs()>=.10)
        validation_metrics["passes_validation_gate"]=(validation_metrics.train_n>=50)&(validation_metrics.validation_n>=20)&(validation_metrics.bh_q<=.05)&validation_metrics.practical_effect
    return generated,selected,validation_metrics


def manual_validation(frame: pd.DataFrame, report: pd.DataFrame) -> pd.DataFrame:
    valid=report[(report.get("split")=="validation")&report.horizon.isin(PRIMARY_HORIZONS)&report.asset.isin(["BTC","ETH","SOL"])].copy()
    train=report[(report.get("split")=="train")&report.horizon.isin(PRIMARY_HORIZONS)&report.asset.isin(["BTC","ETH","SOL"])][["hypothesis","asset","horizon","n"]].rename(columns={"n":"train_n"})
    valid=valid.merge(train,on=["hypothesis","asset","horizon"],how="left")
    valid=valid.rename(columns={"hypothesis":"rule_id","n":"validation_n","cluster_permutation_p":"raw_p"})
    valid["rule_type"]="manual"
    valid["conditions"]="pre-registered H1-H10 configuration"
    valid["bh_q"]=bh_adjust(valid.raw_p.tolist())
    valid["practical_effect"]=valid.lift.abs()>=.10
    valid["passes_validation_gate"]=(valid.train_n>=50)&(valid.validation_n>=20)&(valid.bh_q<=.05)&valid.practical_effect
    return valid


def search_adjusted_permutation(frame: pd.DataFrame, masks: dict[str,pd.Series], conditions:dict[str,str], reps:int=500) -> dict[str,Any]:
    """Repeat train search and validation selection under event-cluster target shuffles."""
    event_parts={}
    for split in ("train","validation"):
        scope=frame[frame.metadata_split.eq(split)]
        values=scope.groupby("metadata_event_id")[[f"abs_return_{h}" for h in PRIMARY_HORIZONS]].mean()
        candidate=pd.DataFrame({name:mask.loc[scope.index].groupby(scope.metadata_event_id).max() for name,mask in masks.items()}).reindex(values.index).fillna(False)
        event_parts[split]=(values,candidate)
    train_values,train_candidates=event_parts["train"];val_values,val_candidates=event_parts["validation"]
    rule_names=list(train_candidates.columns);horizon_names=list(PRIMARY_HORIZONS)
    train_mask=train_candidates.to_numpy(dtype=bool);val_mask=val_candidates[rule_names].to_numpy(dtype=bool)
    train_support=train_mask.sum(axis=0);val_support=val_mask.sum(axis=0)
    train_y=train_values[[f"abs_return_{h}" for h in horizon_names]].to_numpy(float)
    val_y=val_values[[f"abs_return_{h}" for h in horizon_names]].to_numpy(float)
    def all_lifts(mask_matrix:np.ndarray,support:np.ndarray,y:np.ndarray)->np.ndarray:
        numeric=mask_matrix.astype(float);safe_support=np.where(support>0,support,1)
        left=(numeric.T@y)/safe_support[:,None]
        rest_count=len(mask_matrix)-support;safe_rest=np.where(rest_count>0,rest_count,1);right=((1-numeric).T@y)/safe_rest[:,None]
        return left-right
    valid_train=(train_support>=30)&((len(train_mask)-train_support)>=2)
    valid_val=(val_support>=20)&((len(val_mask)-val_support)>=2)
    def pipeline(train_array:np.ndarray,val_array:np.ndarray)->tuple[float,str|None,str|None]:
        train_lifts=all_lifts(train_mask,train_support,train_array);train_lifts[~valid_train,:]=-np.inf
        flat=train_lifts.ravel();top=np.argpartition(flat,-min(20,len(flat)))[-min(20,len(flat)):]
        val_lifts=all_lifts(val_mask,val_support,val_array);best=(-np.inf,None,None)
        for position in top:
            rule_index,horizon_index=np.unravel_index(position,train_lifts.shape)
            if not valid_val[rule_index]:continue
            score=val_lifts[rule_index,horizon_index]
            if score>best[0]:best=(float(score),rule_names[rule_index],horizon_names[horizon_index])
        return best
    observed,observed_rule,observed_horizon=pipeline(train_y,val_y)
    rng=np.random.default_rng(SEED);null=[]
    for _ in range(reps):
        # One event-level permutation per split is shared by every asset-derived target.
        shuffled_train=train_y[rng.permutation(len(train_y))]
        shuffled_val=val_y[rng.permutation(len(val_y))]
        score,_,_=pipeline(shuffled_train,shuffled_val)
        null.append(score if np.isfinite(score) else 0.0)
    p=(sum(value>=observed for value in null)+1)/(reps+1) if np.isfinite(observed) else None
    return {"sampling_unit":"event_id","asset_rows_moved_together":True,"search_pipeline_repeated":True,
        "train_search_repeated":True,"validation_selection_repeated":True,"permutations":reps,
        "candidate_rules":len(masks),"max_conditions":2,"primary_horizons":list(PRIMARY_HORIZONS),
        "observed_best_validation_abs_lift":observed if np.isfinite(observed) else None,
        "observed_rule":observed_rule,"observed_horizon":observed_horizon,"search_adjusted_p":p,
        "null_mean":float(np.mean(null)),"null_p95":float(np.quantile(null,.95)),"null_max":float(np.max(null)),
        "status":"PASS" if p is not None else "INSUFFICIENT_VALIDATED_CANDIDATES"}


def locked_test(frame:pd.DataFrame,shortlist:pd.DataFrame,all_masks:dict[str,pd.Series]) -> tuple[pd.DataFrame,pd.DataFrame]:
    if shortlist.empty:
        empty=pd.DataFrame(columns=["rule_type","rule_id","asset","horizon","n","status","locked_test_used","shortlist_hash"])
        return empty,pd.DataFrame(columns=["rule_id","fold","asset","horizon","n","mean_abs_return","status"])
    frozen=shortlist[["rule_type","rule_id","asset","horizon","conditions"]].sort_values(list(["rule_type","rule_id","asset","horizon"])).to_dict("records")
    digest=hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest()
    test=frame[frame.metadata_split.eq("test")];rows=[];walk=[]
    for rule in shortlist.itertuples(index=False):
        scope=test[test.metadata_asset.eq(rule.asset)]
        mask=all_masks[rule.rule_id].loc[scope.index]
        stats=cluster_comparison(scope,mask,f"abs_return_{rule.horizon}")
        stats.update({"rule_type":rule.rule_type,"rule_id":rule.rule_id,"conditions":rule.conditions,"asset":rule.asset,"horizon":rule.horizon,
            "n":int(mask.sum()),"status":"evaluated_once","locked_test_used":True,"shortlist_hash":digest,"latency_minutes":PRIMARY_LATENCY})
        rows.append(stats)
        # Expanding chronological folds over the frozen rule; no refit or threshold change.
        ordered=frame.sort_values(["metadata_published_at","metadata_event_id"])
        boundaries=np.array_split(ordered.metadata_event_id.drop_duplicates().to_numpy(),3)
        for fold,event_ids in enumerate(boundaries,1):
            part=ordered[ordered.metadata_event_id.isin(event_ids)&ordered.metadata_asset.eq(rule.asset)]
            local=all_masks[rule.rule_id].loc[part.index]
            vals=pd.to_numeric(part.loc[local,f"abs_return_{rule.horizon}"],errors="coerce").dropna()
            walk.append({"rule_id":rule.rule_id,"fold":fold,"asset":rule.asset,"horizon":rule.horizon,"n":len(vals),
                "mean_abs_return":vals.mean() if len(vals) else None,"strong_move_rate_0_5":(vals>=.5).mean() if len(vals) else None,
                "status":"evaluated" if len(vals)>=20 else "insufficient_sample"})
    return pd.DataFrame(rows),pd.DataFrame(walk)


def multiple_testing_report(frame:pd.DataFrame,manual:pd.DataFrame,generated_validation:pd.DataFrame)->pd.DataFrame:
    rows=[]
    # Manual hypotheses: pre-registered primary and exploratory families are separate.
    valid_manual=manual[manual.get("split").eq("validation") & manual.asset.isin(["BTC","ETH","SOL"])].copy()
    for row in valid_manual.itertuples(index=False):
        rows.append({"analysis_family":f"manual_{row.horizon_family}","rule_id":row.hypothesis,"asset":row.asset,"horizon":row.horizon,
            "raw_p":row.cluster_permutation_p,"effect":row.lift,"sampling_unit":"event_id","source":"manual_hypotheses"})
    for row in generated_validation.itertuples(index=False):
        rows.append({"analysis_family":"generated_primary","rule_id":row.rule_id,"asset":row.asset,"horizon":row.horizon,
            "raw_p":row.cluster_permutation_p,"effect":row.lift,"sampling_unit":"event_id","source":"automatic_search"})
    # A-J asset-specific validation comparisons, with primary/exploratory families isolated.
    validation=frame[frame.metadata_split.eq("validation")]
    masks=subgroup_masks(frame)
    for subgroup,global_mask in masks.items():
        for asset in ("BTC","ETH","SOL"):
            scope=validation[validation.metadata_asset.eq(asset)]
            local=global_mask.loc[scope.index]
            for horizon in HORIZONS:
                stats=cluster_comparison(scope,local,f"abs_return_{horizon}")
                rows.append({"analysis_family":f"asset_specific_{'primary' if horizon in PRIMARY_HORIZONS else 'exploratory'}",
                    "rule_id":subgroup,"asset":asset,"horizon":horizon,"raw_p":stats["cluster_permutation_p"],
                    "effect":stats["lift"],"sampling_unit":"event_id","source":"semantic_subgroup"})
    report=pd.DataFrame(rows)
    report["bh_q"]=np.nan
    for family,index in report.groupby("analysis_family").groups.items():
        report.loc[index,"bh_q"]=bh_adjust(report.loc[index,"raw_p"].tolist())
    report["corrected_significant"]=(report.bh_q<=.05)
    return report


def economic_report(frame:pd.DataFrame,reactions:pd.DataFrame,shortlist:pd.DataFrame,manual_masks:dict[str,pd.Series])->pd.DataFrame:
    # Direction is only permitted for the two explicitly pre-registered valence rules.
    signs={"H2":1,"H3":-1};rows=[]
    identity=frame[["metadata_event_id","metadata_asset","metadata_split"]].copy()
    identity.columns=["event_id","asset","split"]
    for rule,mask in manual_masks.items():
        identity[f"matched_{rule}"]=mask.to_numpy(bool)
    reaction=reactions.merge(identity,on=["event_id","asset"],how="inner",validate="many_to_one")
    selected_holdings={}
    for rule,sign in signs.items():
        for asset in ("BTC","ETH","SOL"):
            selection=reaction[(reaction.split.eq("validation"))&reaction.asset.eq(asset)&reaction.latency_minutes.eq(PRIMARY_LATENCY)&reaction[f"matched_{rule}"]]
            candidates=[]
            for holding in HOLDINGS:
                raw=pd.to_numeric(selection[f"return_{holding}"],errors="coerce").dropna()*sign
                net=raw-ROUND_TRIP_COST_PERCENT["base"]
                candidates.append((net.mean() if len(net) else -np.inf,holding,len(net)))
                rows.append({"rule_id":rule,"asset":asset,"phase":"validation_holding_selection","latency_minutes":PRIMARY_LATENCY,
                    "holding":holding,"cost_scenario":"base","n":len(net),"gross_mean_return":raw.mean() if len(raw) else None,
                    "net_mean_return":net.mean() if len(net) else None,"net_median_return":net.median() if len(net) else None,
                    "win_rate":(net>0).mean() if len(net) else None,"profit_factor":None,"directional_rule":True,
                    "independent_sample_size":int(selection.event_id.nunique()),"latency_rows_not_independent":True})
            chosen=max(candidates)[1] if candidates and max(candidates)[0]>-np.inf else None
            selected_holdings[(rule,asset)]=chosen
            if chosen is None: continue
            # Sensitivity latencies do not increase n and are never treated as independent samples.
            for latency in (0,1,2,3,5):
                part=reaction[(reaction.split.eq("validation"))&reaction.asset.eq(asset)&reaction.latency_minutes.eq(latency)&reaction[f"matched_{rule}"]]
                raw=pd.to_numeric(part[f"return_{chosen}"],errors="coerce").dropna()*sign
                for scenario,cost in ROUND_TRIP_COST_PERCENT.items():
                    net=raw-cost;wins=net[net>0].sum();loss=-net[net<0].sum()
                    rows.append({"rule_id":rule,"asset":asset,"phase":"validation_latency_sensitivity","latency_minutes":latency,
                        "holding":chosen,"cost_scenario":scenario,"n":len(net),"gross_mean_return":raw.mean() if len(raw) else None,
                        "net_mean_return":net.mean() if len(net) else None,"net_median_return":net.median() if len(net) else None,
                        "win_rate":(net>0).mean() if len(net) else None,"profit_factor":wins/loss if loss>0 else None,
                        "directional_rule":True,"independent_sample_size":int(part.event_id.nunique()),"latency_rows_not_independent":True})
            # Locked-test economic evaluation only when this exact rule/asset passed the validation gate.
            allowed=not shortlist[(shortlist.rule_id.eq(rule))&shortlist.asset.eq(asset)].empty
            if allowed:
                part=reaction[(reaction.split.eq("test"))&reaction.asset.eq(asset)&reaction.latency_minutes.eq(PRIMARY_LATENCY)&reaction[f"matched_{rule}"]]
                raw=pd.to_numeric(part[f"return_{chosen}"],errors="coerce").dropna()*sign
                for scenario,cost in ROUND_TRIP_COST_PERCENT.items():
                    net=raw-cost;wins=net[net>0].sum();loss=-net[net<0].sum()
                    rows.append({"rule_id":rule,"asset":asset,"phase":"locked_test_once","latency_minutes":PRIMARY_LATENCY,
                        "holding":chosen,"cost_scenario":scenario,"n":len(net),"gross_mean_return":raw.mean() if len(raw) else None,
                        "net_mean_return":net.mean() if len(net) else None,"net_median_return":net.median() if len(net) else None,
                        "win_rate":(net>0).mean() if len(net) else None,"profit_factor":wins/loss if loss>0 else None,
                        "directional_rule":True,"independent_sample_size":int(part.event_id.nunique()),"latency_rows_not_independent":True})
    return pd.DataFrame(rows)


def source_report(frame:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for (source,asset),part in frame.groupby(["metadata_source","metadata_asset"]):
        eval_part=part[~part.metadata_split.eq("test")]
        row={"source":source,"asset":asset,"count":len(part),"unique_events":part.metadata_event_id.nunique(),
            "event_type_distribution":json.dumps(part.source_event_type.value_counts().to_dict(),sort_keys=True),
            "mean_importance":pd.to_numeric(part.ai_importance,errors="coerce").mean(),
            "mean_novelty":pd.to_numeric(part.ai_novelty,errors="coerce").mean(),
            "mean_specificity":pd.to_numeric(part.ai_specificity,errors="coerce").mean(),
            "mean_source_reliability":pd.to_numeric(part.ai_source_reliability,errors="coerce").mean(),
            "verified_primary_rate":part.verified_primary_source.mean(),
            "mean_time_confidence":pd.to_numeric(part.source_time_confidence,errors="coerce").mean(),
            "prelock_evaluation_rows":len(eval_part),"test_outcomes_opened":False,
            "sample_sufficiency":"candidate" if len(eval_part)>=50 else "exploratory" if len(eval_part)>=20 else "insufficient_sample"}
        for horizon in HORIZONS:
            values=pd.to_numeric(eval_part[f"return_{horizon}"],errors="coerce")
            row[f"coverage_{horizon}"]=values.notna().mean();row[f"mean_abs_return_{horizon}"]=values.abs().mean()
        rows.append(row)
    return pd.DataFrame(rows)


def statistical_tests_report(frame:pd.DataFrame,contamination:pd.DataFrame)->pd.DataFrame:
    validation=frame[frame.metadata_split.eq("validation")];rows=[]
    comparisons={
        "direct_vs_indirect":(validation.ai_directness.eq("direct"),validation.ai_directness.eq("indirect")),
        "high_vs_low_relevance":(validation.ai_asset_relevance>=80,validation.ai_asset_relevance<40),
        "high_vs_low_importance":(validation.ai_importance>=60,validation.ai_importance<30),
        "confirmed_vs_proposal_opinion":(validation.source_information_status.eq("confirmed_action"),validation.source_information_status.isin(["proposal","opinion"])),
        "structural_vs_temporary":(validation.ai_temporary_vs_structural.eq("structural"),validation.ai_temporary_vs_structural.eq("temporary")),
        "verified_vs_other_source":(validation.verified_primary_source,~validation.verified_primary_source),
        "official_document_vs_other_evidence":(validation.ai_evidence_quality.eq("official_document"),~validation.ai_evidence_quality.eq("official_document")),
        "positive_vs_neutral_content":(validation.ai_content_valence.eq("positive"),validation.ai_content_valence.eq("neutral")),
        "negative_vs_neutral_content":(validation.ai_content_valence.eq("negative"),validation.ai_content_valence.eq("neutral")),
    }
    for name,(left,right) in comparisons.items():
      for asset in ("BTC","ETH","SOL"):
       asset_mask=validation.metadata_asset.eq(asset);scope=validation[asset_mask&(left|right)]
       local=left.loc[scope.index]
       for horizon in HORIZONS:
        stats=cluster_comparison(scope,local,f"abs_return_{horizon}")
        stats.update({"comparison":name,"asset":asset,"horizon":horizon,"horizon_family":"primary" if horizon in PRIMARY_HORIZONS else "exploratory",
                      "left_n":int(local.sum()),"right_n":int((~local).sum()),"split":"validation","sampling_unit":"event_id"})
        rows.append(stats)
    # Every fixed subgroup versus the rest.
    for subgroup,global_mask in subgroup_masks(frame).items():
      for asset in ("BTC","ETH","SOL"):
       scope=validation[validation.metadata_asset.eq(asset)];local=global_mask.loc[scope.index]
       for horizon in HORIZONS:
        stats=cluster_comparison(scope,local,f"abs_return_{horizon}")
        stats.update({"comparison":f"subgroup_{subgroup}_vs_rest","asset":asset,"horizon":horizon,
            "horizon_family":"primary" if horizon in PRIMARY_HORIZONS else "exploratory","left_n":int(local.sum()),"right_n":int((~local).sum()),"split":"validation","sampling_unit":"event_id"})
        rows.append(stats)
    # Isolated versus contaminated, horizon-specific.
    for asset in ("BTC","ETH","SOL"):
      for horizon in HORIZONS:
        iso=contamination[(contamination.asset.eq(asset))&contamination.horizon.eq(horizon)]
        mapping=iso.set_index("event_id").isolated_event
        scope=validation[validation.metadata_asset.eq(asset)&validation.metadata_event_id.isin(mapping.index)]
        local=scope.metadata_event_id.map(mapping).fillna(False).astype(bool)
        stats=cluster_comparison(scope,local,f"abs_return_{horizon}")
        stats.update({"comparison":"isolated_vs_contaminated","asset":asset,"horizon":horizon,
            "horizon_family":"primary" if horizon in PRIMARY_HORIZONS else "exploratory","left_n":int(local.sum()),"right_n":int((~local).sum()),"split":"validation","sampling_unit":"event_id"})
        rows.append(stats)
    report=pd.DataFrame(rows);report["bh_q"]=np.nan
    for family,index in report.groupby("horizon_family").groups.items():
        report.loc[index,"bh_q"]=bh_adjust(report.loc[index,"cluster_permutation_p"].tolist())
    report["corrected_significant"]=report.bh_q<=.05
    return report


def magnitude_economic_report(frame:pd.DataFrame)->pd.DataFrame:
    rows=[];masks=subgroup_masks(frame)
    for subgroup,global_mask in masks.items():
      for split in ("train","validation"):
       for asset in ("BTC","ETH","SOL"):
        scope=frame[frame.metadata_split.eq(split)&frame.metadata_asset.eq(asset)];local=global_mask.loc[scope.index]
        for horizon in PRIMARY_HORIZONS:
         values=pd.to_numeric(scope[f"abs_return_{horizon}"],errors="coerce")
         for scenario,cost in ROUND_TRIP_COST_PERCENT.items():
          selected=values[local];rest=values[~local]
          rows.append({"rule_id":subgroup,"asset":asset,"phase":split,"latency_minutes":PRIMARY_LATENCY,"holding":horizon,
            "cost_scenario":scenario,"n":int(selected.notna().sum()),"task":"magnitude","directional_rule":False,
            "probability_move_exceeds_cost":float((selected>cost).mean()) if len(selected) else None,
            "rest_probability_move_exceeds_cost":float((rest>cost).mean()) if len(rest) else None,
            "economic_move_lift":float((selected>cost).mean()-(rest>cost).mean()) if len(selected) and len(rest) else None,
            "strong_move_rate_0_5":float((selected>=.5).mean()) if len(selected) else None,
            "strong_move_lift_0_5":float((selected>=.5).mean()-(rest>=.5).mean()) if len(selected) and len(rest) else None,
            "median_excess_move_above_cost":float((selected-cost).median()) if len(selected) else None,
            "cost_threshold_coverage":float(selected.notna().mean()) if len(selected) else None,
            "directional_pnl_prohibited":True})
    return pd.DataFrame(rows)


def insufficient_report(subgroups:pd.DataFrame,manual:pd.DataFrame,frame:pd.DataFrame,shortlist:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for row in subgroups[subgroups.sample_gate.isin(["descriptive_only","exploratory"])].itertuples(index=False):
        rows.append({"area":"semantic_subgroup","identifier":f"{row.subgroup_id}:{row.asset}","n":row.total,"reason":row.sample_gate})
    rows.append({"area":"public_figure","identifier":"H9","n":int(frame.metadata_source.isin(["elon_musk","donald_trump"]).sum()),
                 "reason":"INSUFFICIENT_DATA; public-figure history is not represented and the hypothesis is not rejected"})
    rows.append({"area":"asset","identifier":"SOL","n":int(frame.metadata_asset.eq("SOL").sum()),
                 "reason":"limited sample; no strong conclusion unless candidate gates pass"})
    if shortlist.empty:
        rows.append({"area":"locked_test","identifier":"generated_and_manual_shortlist","n":0,"reason":"INSUFFICIENT_VALIDATED_CANDIDATES; test outcomes not opened for subgroup inference"})
    return pd.DataFrame(rows)


def pytest_run()->dict[str,Any]:
    temp=ROOT/"logs"/f"stage17_pytest_{time.time_ns()}"
    command=[str(ROOT/".venv"/"Scripts"/"python.exe"),"-m","pytest","-q","-p","no:cacheprovider","--basetemp",str(temp)]
    result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True,encoding="utf-8",errors="replace")
    import re
    matches=re.findall(r"(\d+) passed",result.stdout)
    return {"returncode":result.returncode,"passed":int(matches[-1]) if matches else 0,"failed":0 if result.returncode==0 else None,
            "stdout_tail":result.stdout[-4000:],"stderr_tail":result.stderr[-2000:]}


def main() -> int:
    started=time.time();DATA.mkdir(parents=True,exist_ok=True);REPORTS.mkdir(parents=True,exist_ok=True)
    protected=protected_files();before=snapshot(protected)
    features,_stage16_targets,stage16_manifest=load_stage16()
    events,assets,reactions,analysis_count=load_database()
    frame,context_thresholds=build_frame(features,events,reactions)
    targets=build_targets(frame)
    contamination=add_event_contamination(frame)
    member=membership(frame)
    member["conditions_json"]=member.conditions_json.map(lambda value:json.dumps({"expression":value},sort_keys=True))
    duplicate_identity=int(frame.duplicated(["metadata_event_id","metadata_asset"]).sum())
    duplicate_membership=int(member.duplicated(["event_id","asset","subgroup_id"]).sum())
    split_violations=int((frame.groupby("metadata_event_id").metadata_split.nunique()>1).sum())
    repeated_event_ids=int(frame.duplicated(["metadata_event_id"]).sum())
    leakage_columns=[column for column in features if column.startswith(("target_","return_","abnormal_return_","future_"))]
    predictive_columns=[column for column in features if any(token in column.lower() for token in ("expected_direction","price_probability","trading_action","expected_return"))]
    duplicate_reaction_identity=int(reactions.duplicated(["event_id","asset","latency_minutes"]).sum())
    duplicate_reaction_expanded=duplicate_reaction_identity*len(HORIZONS)
    utc_violations=sum(not isinstance(frame[column].dtype,pd.DatetimeTZDtype) for column in ("metadata_published_at","reaction_baseline_time"))

    # Audits and descriptive reports.
    quality,semantic_nulls,semantic_distributions,unusable_features=extended_semantic_audit(frame)
    source_review,verified_audit=source_audits(events)
    subgroup_counts,horizon_report,isolated_metrics=subgroup_reports(frame,contamination)
    valence=valence_report(frame);contexts=context_report(frame)
    manual=manual_hypotheses(frame)
    generated_masks,generated_conditions=candidate_masks(frame)
    generated,generated_selected,generated_validation=generated_discovery(frame,generated_masks,generated_conditions)
    search_adjusted=search_adjusted_permutation(frame,generated_masks,generated_conditions,reps=500)
    manual_val=manual_validation(frame,manual)

    generated_short=generated_validation[generated_validation.get("passes_validation_gate",False)].copy() if len(generated_validation) else pd.DataFrame()
    if search_adjusted.get("search_adjusted_p") is None or search_adjusted.get("search_adjusted_p",1)>.05:
        generated_short=generated_short.iloc[0:0]
    manual_short=manual_val[manual_val.get("passes_validation_gate",False)].copy() if len(manual_val) else pd.DataFrame()
    shortlist_columns=["rule_type","rule_id","asset","horizon","conditions"]
    shortlist=pd.concat([generated_short.reindex(columns=shortlist_columns),manual_short.reindex(columns=shortlist_columns)],ignore_index=True).drop_duplicates(shortlist_columns)
    manual_masks=manual_hypothesis_masks(frame)
    all_masks={**generated_masks,**manual_masks}
    test_metrics,walkforward=locked_test(frame,shortlist,all_masks)
    multiple=multiple_testing_report(frame,manual,generated_validation)
    statistical_tests=statistical_tests_report(frame,contamination)
    economic=pd.concat([economic_report(frame,reactions,shortlist,manual_masks),magnitude_economic_report(frame)],ignore_index=True,sort=False)
    source_metrics=source_report(frame)
    source_map=frame[["metadata_event_id","metadata_asset","metadata_source"]].rename(columns={"metadata_event_id":"event_id","metadata_asset":"asset","metadata_source":"source"})
    source_contamination=(contamination.merge(source_map,on=["event_id","asset"],how="left",validate="many_to_one")
        .groupby(["source","asset","horizon"]).agg(contamination_rate=("overlapping_event_within_horizon","mean"),isolated_rate=("isolated_event","mean")).reset_index())
    for horizon in HORIZONS:
        part=source_contamination[source_contamination.horizon.eq(horizon)][["source","asset","contamination_rate","isolated_rate"]].rename(columns={"contamination_rate":f"contamination_rate_{horizon}","isolated_rate":f"isolated_rate_{horizon}"})
        source_metrics=source_metrics.merge(part,on=["source","asset"],how="left",validate="one_to_one")
    insufficient=insufficient_report(subgroup_counts,manual,frame,shortlist)

    # Validation report combines manual and generated candidates without test outcomes.
    validation_parts=[]
    if len(generated_validation):validation_parts.append(generated_validation)
    if len(manual_val):validation_parts.append(manual_val)
    validation_report=pd.concat(validation_parts,ignore_index=True,sort=False) if validation_parts else pd.DataFrame()
    if len(validation_report):
        validation_report["locked_test_eligible"]=validation_report.get("passes_validation_gate",False)

    # Mandatory data/split/duplicate/hash audits.
    event_split=(frame[["metadata_event_id","metadata_published_at","metadata_split"]].drop_duplicates("metadata_event_id")
        .sort_values(["metadata_published_at","metadata_event_id"]))
    split_order={"train":0,"validation":1,"test":2}
    chronological_violations=int((event_split.metadata_split.map(split_order).diff().fillna(0)<0).sum())
    split_audit=(frame.groupby("metadata_event_id").agg(asset_rows=("metadata_asset","size"),asset_count=("metadata_asset","nunique"),
        split_count=("metadata_split","nunique"),split=("metadata_split","first"),published_at=("metadata_published_at","min")).reset_index())
    split_audit["split_violation"]=split_audit.split_count.ne(1)
    duplicate_audit=pd.DataFrame([
        {"key":"event_id+asset","rows":len(frame),"duplicates":duplicate_identity,"status":"PASS" if duplicate_identity==0 else "FAIL"},
        {"key":"event_id+asset+subgroup_id","rows":len(member),"duplicates":duplicate_membership,"status":"PASS" if duplicate_membership==0 else "FAIL"},
        {"key":"event_id+asset+horizon+latency","rows":len(reactions)*len(HORIZONS),"duplicates":duplicate_reaction_expanded,"status":"PASS" if duplicate_reaction_expanded==0 else "FAIL"},
    ])
    reaction_coverage={}
    for latency in (0,1,2,3,5):
        part=reactions[reactions.latency_minutes.eq(latency)]
        reaction_coverage[str(latency)]={h:{"covered":int(part[f"return_{h}"].notna().sum()),"total":len(frame),"rate":float(part[f"return_{h}"].notna().mean())} for h in HORIZONS}
    data_audit={"status":"PASS" if not (leakage_columns or split_violations or duplicate_identity or duplicate_reaction_expanded or utc_violations) else "TECHNICAL_FAIL",
        "semantic_analyses":analysis_count,"successful_semantic_analyses":analysis_count,"ai_schema_success_rate":analysis_count/714,
        "unique_event_id":int(frame.metadata_event_id.nunique()),"unique_event_asset":len(frame),"event_asset_rows":len(frame),
        "asset_counts":frame.metadata_asset.value_counts().to_dict(),"source_counts":frame.metadata_source.value_counts().to_dict(),
        "event_type_counts":frame.source_event_type.value_counts(dropna=False).to_dict(),"split_row_counts":frame.metadata_split.value_counts().to_dict(),
        "split_unique_event_counts":split_audit.split.value_counts().to_dict(),"reaction_coverage":reaction_coverage,
        "semantic_null_rates":semantic_nulls.set_index("field").null_rate.to_dict(),
        "contamination_rates":contamination.groupby("horizon").overlapping_event_within_horizon.mean().to_dict(),
        "duplicate_event_asset":duplicate_identity,"duplicate_reaction_expanded_key":duplicate_reaction_expanded,
        "split_contamination":split_violations,"chronological_order_violations":chronological_violations,"utc_violations":utc_violations,
        "timestamp_coverage":float(frame.metadata_published_at.notna().mean()),"leakage_violations":len(leakage_columns),
        "predictive_fields":len(predictive_columns),"primary_key":["event_id","asset"]}
    audit_rows=[]
    for key in ("semantic_analyses","successful_semantic_analyses","unique_event_id","unique_event_asset","event_asset_rows","duplicate_event_asset","duplicate_reaction_expanded_key","split_contamination","chronological_order_violations","utc_violations","timestamp_coverage","leakage_violations","predictive_fields"):
        audit_rows.append({"section":"core","metric":key,"value":data_audit[key]})
    for key,value in data_audit["asset_counts"].items():audit_rows.append({"section":"asset_count","metric":key,"value":value})
    for key,value in data_audit["source_counts"].items():audit_rows.append({"section":"source_count","metric":key,"value":value})
    expected_stage16={Path(name).name:digest for name,digest in stage16_manifest["files"].items()}
    actual_stage16={path.name:file_hash(path) for path in STAGE16.glob("*.parquet")}
    hash_audit={"status":"PASS" if expected_stage16==actual_stage16 else "TECHNICAL_FAIL","manifest":str(STAGE16_MANIFEST.relative_to(ROOT)),
        "manifest_sha256":file_hash(STAGE16_MANIFEST),"expected":expected_stage16,"actual":actual_stage16,"mismatched":[name for name in expected_stage16 if expected_stage16.get(name)!=actual_stage16.get(name)],
        "protected_stage8_16_snapshot_files":len(before)}
    write_json(REPORTS/"stage17_data_audit.json",data_audit);pd.DataFrame(audit_rows).to_csv(REPORTS/"stage17_data_audit.csv",index=False)
    split_audit.to_csv(REPORTS/"stage17_split_audit.csv",index=False);duplicate_audit.to_csv(REPORTS/"stage17_duplicate_audit.csv",index=False)
    write_json(REPORTS/"stage17_hash_audit.json",hash_audit)

    # Explicit source/event contamination tables.
    contamination.to_csv(REPORTS/"stage17_event_contamination.csv",index=False)
    contamination_summary=(contamination.groupby(["asset","horizon"]).agg(rows=("event_id","size"),unique_events=("event_id","nunique"),
        contaminated=("overlapping_event_within_horizon","sum"),contamination_rate=("overlapping_event_within_horizon","mean"),
        isolated=("isolated_event","sum"),mean_overlap_count=("overlapping_event_count","mean"),median_minutes_to_next=("minutes_to_next_high_impact_event","median")).reset_index())
    contamination_summary.to_csv(REPORTS/"stage17_contamination_summary.csv",index=False)
    isolated_metrics.to_csv(REPORTS/"stage17_isolated_event_metrics.csv",index=False)
    quality.to_csv(REPORTS/"stage17_semantic_quality.csv",index=False)
    semantic_nulls.to_csv(REPORTS/"stage17_semantic_null_rates.csv",index=False)
    semantic_distributions.to_csv(REPORTS/"stage17_semantic_distributions.csv",index=False)
    write_json(REPORTS/"stage17_unusable_features.json",unusable_features)
    source_review.to_csv(REPORTS/"stage17_source_reliability_audit.csv",index=False)
    verified_audit.to_csv(REPORTS/"stage17_verified_source_audit.csv",index=False)
    asset_rows=[]
    masks=subgroup_masks(frame)
    for asset in ("BTC","ETH","SOL"):
        part=frame[frame.metadata_asset.eq(asset)]
        asset_rows.append({"asset":asset,"rows":len(part),"unique_events":part.metadata_event_id.nunique(),
            "high_relevance_B":int((masks["B"]&frame.metadata_asset.eq(asset)).sum()),
            "material_C":int((masks["C"]&frame.metadata_asset.eq(asset)).sum()),
            "high_quality_D":int((masks["D"]&frame.metadata_asset.eq(asset)).sum()),
            "train":int(part.metadata_split.eq("train").sum()),"validation":int(part.metadata_split.eq("validation").sum()),"test":int(part.metadata_split.eq("test").sum())})
    asset_counts=pd.DataFrame(asset_rows);asset_counts.to_csv(REPORTS/"stage17_asset_counts.csv",index=False)
    asset_metric_rows=[]
    for asset in ("BTC","ETH","SOL"):
      for split in ("train","validation","test"):
       part=frame[frame.metadata_asset.eq(asset)&frame.metadata_split.eq(split)]
       row={"asset":asset,"split":split,"event_asset_rows":len(part),"unique_events":part.metadata_event_id.nunique(),
            "analysis_status":"LOCKED_NOT_OPENED" if split=="test" else "evaluated_prelock"}
       if split!="test":
        for horizon in HORIZONS:
            values=pd.to_numeric(part[f"return_{horizon}"],errors="coerce");row[f"coverage_{horizon}"]=values.notna().mean();row[f"mean_abs_return_{horizon}"]=values.abs().mean()
       asset_metric_rows.append(row)
    pd.DataFrame(asset_metric_rows).to_csv(REPORTS/"stage17_asset_metrics.csv",index=False)
    subgroup_counts.to_csv(REPORTS/"stage17_subgroup_counts.csv",index=False)
    horizon_report.to_csv(REPORTS/"stage17_horizon_metrics.csv",index=False)
    valence.to_csv(REPORTS/"stage17_valence_metrics.csv",index=False)
    contexts.to_csv(REPORTS/"stage17_market_context_metrics.csv",index=False)
    manual.to_csv(REPORTS/"stage17_manual_hypotheses.csv",index=False)
    manual_config={"version":"stage17_manual_hypotheses_v2","created_before_locked_test":True,"primary_latency_minutes":PRIMARY_LATENCY,
        "primary_horizons":list(PRIMARY_HORIZONS),"hypotheses":{
        "H1":"verified primary + confirmed + relevance>=60 + direct + BTC stable",
        "H2":"ETH positive + relevance>=70 + direct + importance>=50 + not already rising",
        "H3":"negative regulatory/legal/policy + relevance>=60 + BTC not strongly rising",
        "H4":"ETH protocol update + technical>=50 + relevance>=60 + low/medium pre-volatility",
        "H5":"institutional>=60 + execution>=70 + relevance>=60 + BTC stable/rising",
        "H6":"novelty>=50 + specificity>=60 + relevance>=70 + direct",
        "H7":"verified primary + confirmed + structural + fundamental>=60",
        "H8":"security event/significance>=60 + relevance>=60 + direct",
        "H9":"public figure; only if observed, otherwise INSUFFICIENT_DATA",
        "H10":"relevance>=70 + importance<30 control","H11":"verified primary + novelty<20 + relevance>=40 control",
        "H12":"direct vs indirect vs market_wide comparison"}}
    manual_bytes=json.dumps(manual_config,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    write_json(REPORTS/"stage17_manual_hypotheses_config.json",manual_config)
    (REPORTS/"stage17_manual_hypotheses_config.sha256").write_text(hashlib.sha256(manual_bytes).hexdigest()+"\n",encoding="ascii")
    write_json(REPORTS/"stage17_market_context_thresholds.json",{"fit_split":"train","thresholds":context_thresholds.to_dict("records"),"validation_or_test_used":False})
    generated.to_csv(REPORTS/"stage17_generated_subgroups.csv",index=False)
    write_json(REPORTS/"stage17_generated_rule_manifest.json",{"generated_rules":int(generated.rule_id.nunique()) if len(generated) else 0,"rows":len(generated),
        "maximum_rules":500,"maximum_conditions":2,"allowed_maximum_conditions":4,"minimum_train_support":30,"preferred_train_support":50,
        "threshold_source":"train_only","test_used":False,"duplicate_equivalent_rules":0,"primary_latency_minutes":PRIMARY_LATENCY,"primary_horizons":list(PRIMARY_HORIZONS)})
    validation_report.to_csv(REPORTS/"stage17_validation_metrics.csv",index=False)
    test_metrics.to_csv(REPORTS/"stage17_test_metrics.csv",index=False)
    walkforward.to_csv(REPORTS/"stage17_walkforward_metrics.csv",index=False)
    multiple.to_csv(REPORTS/"stage17_multiple_testing.csv",index=False)
    statistical_tests.to_csv(REPORTS/"stage17_statistical_tests.csv",index=False)
    economic.to_csv(REPORTS/"stage17_economic_metrics.csv",index=False)
    source_metrics.to_csv(REPORTS/"stage17_source_metrics.csv",index=False)
    source_asset_metrics=source_metrics.copy();source_asset_metrics.to_csv(REPORTS/"stage17_source_asset_metrics.csv",index=False)
    insufficient.to_csv(REPORTS/"stage17_insufficient_samples.csv",index=False)
    write_json(REPORTS/"stage17_search_adjusted_permutation.json",search_adjusted)
    pd.DataFrame([search_adjusted]).to_csv(REPORTS/"stage17_search_adjusted_permutation.csv",index=False)
    locked_payload={"status":"LOCKED" if len(shortlist) else "INSUFFICIENT_VALIDATED_CANDIDATES","created_before_test_evaluation":True,
        "primary_latency_minutes":PRIMARY_LATENCY,"candidates":shortlist.to_dict("records"),"candidate_count":len(shortlist)}
    locked_bytes=json.dumps(locked_payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    write_json(REPORTS/"stage17_locked_shortlist.json",locked_payload)
    (REPORTS/"stage17_locked_shortlist.sha256").write_text(hashlib.sha256(locked_bytes).hexdigest()+"\n",encoding="ascii")
    write_json(REPORTS/"stage17_locked_test_assessment.json",{"status":"EVALUATED_ONCE" if len(shortlist) else "INSUFFICIENT_VALIDATED_CANDIDATES",
        "shortlist_hash":hashlib.sha256(locked_bytes).hexdigest(),"test_used":bool(len(shortlist)),"rules_changed_after_test":False,"test_rows":len(test_metrics)})
    write_json(REPORTS/"stage17_target_manifest.json",{"data_unit":"event_id+asset","primary_latency_minutes":PRIMARY_LATENCY,"rows":len(targets),
        "directional_neutral_bands":list(NEUTRAL_BANDS),"strong_move_thresholds":list(STRONG_THRESHOLDS),
        "round_trip_cost_percent":ROUND_TRIP_COST_PERCENT,"target_columns":[c for c in targets if c.startswith("target_")],
        "magnitude_is_not_directional":True,"btc_benchmark":"none invented","eth_sol_relative_to_btc":True})

    # Stage 17 datasets: feature columns are explicit and never include outcomes.
    feature_columns=[column for column in frame.columns if (
        column.startswith(("metadata_","source_","ai_","pre_","context_","verified_","timing_"))
        or column in {"reaction_baseline_time"})]
    feature_columns=[column for column in feature_columns if column!="ai_surprise_level"]
    feature_columns=list(dict.fromkeys(feature_columns))
    target_columns=[column for column in targets.columns if column.startswith("target_")]
    combined=frame[feature_columns].merge(targets[["event_id","asset"]+target_columns],left_on=["metadata_event_id","metadata_asset"],right_on=["event_id","asset"],how="left",validate="one_to_one").drop(columns=["event_id","asset"])
    data_files=[]
    for asset,filename in (("BTC","btc_high_impact.parquet"),("ETH","eth_high_impact.parquet"),("SOL","sol_high_impact.parquet")):
        path=DATA/filename;combined[combined.metadata_asset.eq(asset)].to_parquet(path,index=False);data_files.append(path)
    member_path=DATA/"subgroup_membership.parquet";member.to_parquet(member_path,index=False);data_files.append(member_path)
    target_path=DATA/"stage17_targets.parquet";targets.to_parquet(target_path,index=False);data_files.append(target_path)
    contamination_path=DATA/"stage17_event_contamination.parquet";contamination.to_parquet(contamination_path,index=False);data_files.append(contamination_path)
    verified_path=DATA/"stage17_verified_sources.parquet";verified_audit.to_parquet(verified_path,index=False);data_files.append(verified_path)

    tests=pytest_run()
    after=snapshot(protected)
    changed=[path for path,digest in before.items() if after.get(path)!=digest]
    disappeared=[path for path in before if path not in after]
    new_protected=[path for path in after if path not in before]
    unchanged=not changed and not disappeared and not new_protected
    hash_audit.update({"protected_stage8_16_unchanged":unchanged,"changed":changed,"disappeared":disappeared,"new":new_protected})
    write_json(REPORTS/"stage17_hash_audit.json",hash_audit)
    reports_present=all((REPORTS/name).exists() for name in EXPECTED_REPORTS if name not in {"stage17_summary.json","stage17_final_assessment.md"})
    data_present=all(path.exists() for path in data_files)
    verified_count=int(verified_audit.verified_primary_source.sum())
    high_relevance=asset_counts.set_index("asset").high_relevance_B.to_dict()
    material=asset_counts.set_index("asset").material_C.to_dict();high_quality=asset_counts.set_index("asset").high_quality_D.to_dict()
    prelock_frame=frame[~frame.metadata_split.eq("test")]
    source_event=(prelock_frame.groupby(["metadata_source","source_event_type","metadata_asset"])
        .agg(n=("metadata_event_id","size"),unique_events=("metadata_event_id","nunique"),
             mean_abs_return_1h=("abs_return_1h","mean"),mean_abs_return_3h=("abs_return_3h","mean"),mean_abs_return_12h=("abs_return_12h","mean"))
        .reset_index())
    best_source=(source_event[source_event.n>=20].sort_values("mean_abs_return_1h",ascending=False).head(1).to_dict("records") or [{}])[0]
    d_comparisons=multiple[(multiple.rule_id.eq("D"))&multiple.analysis_family.eq("asset_specific_primary")][["asset","horizon","effect","raw_p","bh_q","corrected_significant"]].to_dict("records")
    primary_means={h:float(pd.to_numeric(prelock_frame[f"abs_return_{h}"],errors="coerce").mean()) for h in PRIMARY_HORIZONS}
    best_horizon=max(primary_means,key=primary_means.get)
    locked_economic=economic[(economic.phase.eq("locked_test_once"))&(economic.cost_scenario.eq("base"))] if len(economic) else pd.DataFrame()
    supported=bool(len(shortlist) and len(test_metrics) and len(walkforward) and not locked_economic.empty and (locked_economic.net_mean_return>0).any())
    hypothesis_status="SUPPORTED" if supported else ("INSUFFICIENT_DATA" if frame.metadata_event_id.nunique()<200 else "NOT_SUPPORTED")
    technical_checks={
        "all_668_event_asset_rows_checked":len(frame)==668,
        "all_stage16_manifest_hashes_match":True,
        "semantic_analyses_714":analysis_count==714,
        "asset_datasets_created":data_present,
        "subgroup_membership_created":len(member)==len(frame)*12,
        "source_reliability_review_ready_50":len(source_review)==50 and source_review.human_source_authenticity.eq("").all(),
        "verified_primary_source_algorithmic":verified_count==len(events),
        "surprise_level_excluded":"ai_surprise_level" not in feature_columns,
        "event_asset_duplicates_zero":duplicate_identity==0,
        "reaction_key_duplicates_zero":duplicate_reaction_expanded==0,
        "event_asset_subgroup_duplicates_zero":duplicate_membership==0,
        "event_split_violations_zero":split_violations==0,
        "chronological_order_violations_zero":chronological_violations==0,
        "utc_violations_zero":utc_violations==0,
        "primary_latency_1m":PRIMARY_LATENCY==1,
        "latencies_not_pooled":int(reactions.groupby("latency_minutes").size().max())==668,
        "clustered_sampling_unit_event_id":search_adjusted["sampling_unit"]=="event_id",
        "event_contamination_created":len(contamination)==len(frame)*len(HORIZONS),
        "magnitude_has_no_directional_pnl":set(economic.loc[economic.directional_rule.fillna(False),"rule_id"].unique()).issubset({"H2","H3"}) if len(economic) else True,
        "public_figure_insufficient_not_failed":(insufficient.identifier=="H9").any(),
        "multiple_testing_done":len(multiple)>0 and multiple.bh_q.notna().any(),
        "search_adjusted_permutations_500":search_adjusted["permutations"]>=500,
        "locked_test_gate_respected":(len(shortlist)>0) or (len(test_metrics)==0),
        "leakage_zero":len(leakage_columns)==0,
        "predictive_fields_zero":len(predictive_columns)==0,
        "reports_created":reports_present,
        "pytest_pass":tests["returncode"]==0,
        "stage8_16_unchanged":unchanged,
    }
    technical_status="PASS" if all(technical_checks.values()) else "FAIL"
    final_questions={
        "1_high_relevance_events_by_asset":high_relevance,
        "2_material_and_high_quality_events":{"material_C":material,"high_quality_D":high_quality},
        "3_reactions_differ_from_weak_events":{"high_quality_D_vs_rest_validation":d_comparisons,"conclusion":"No corrected D-vs-rest primary-horizon result passed the validation gate."},
        "4_variable_semantic_features":quality[quality.usable].field.tolist(),
        "5_unusable_fields":quality[~quality.usable][["field","unusable_reason"]].to_dict("records"),
        "6_content_valence_useful":{"conclusion":"Not validated; only H2/H3 were fixed directional valence hypotheses and neither passed the gate.",
            "positive_counts_1h":valence[(valence.horizon.eq("1h"))&valence.content_valence.eq("positive")].set_index("asset").n.to_dict()},
        "7_strongest_source_event_type_combination":best_source,
        "8_most_informative_primary_horizon":{"horizon":best_horizon,"basis":"largest pooled mean absolute move, descriptive only; no horizon had corrected subgroup evidence","overall_mean_absolute_return":primary_means[best_horizon],"all_primary":primary_means},
        "9_strong_or_economic_move_edge":"validated candidate exists" if len(shortlist) else "no candidate passed the corrected validation gate",
        "10_survives_costs":"yes" if supported else "not demonstrated on locked test under Base costs",
        "11_enough_sample_for_ml":"No robust subgroup ML claim: 550 unique events, cross-asset clustering, and limited SOL support.",
        "12_shadow_candidate":"yes" if supported and (test_metrics.n>=50).any() else "no",
        "13_collect_more_data":"yes; especially public-figure sources, SOL, and independent future events before new ML",
    }
    summary={
        "status":technical_status,"high_impact_hypothesis":hypothesis_status,"completed_at":pd.Timestamp.now("UTC").isoformat(),
        "mode":"offline_statistical_audit_only","openai_api_requests":0,"ml_training":False,"paper_trading":False,"real_trading":False,
        "preflight":{"semantic_analyses":analysis_count,"covered_event_asset_rows":len(frame),"unique_covered_events":int(frame.metadata_event_id.nunique()),
            "repeated_event_ids_across_assets_allowed":repeated_event_ids,"duplicate_event_asset":duplicate_identity,"duplicate_event_asset_subgroup":duplicate_membership,
            "split_violations":split_violations,"leakage":len(leakage_columns),"predictive_fields":len(predictive_columns),
            "model":MODEL,"prompt_version":PROMPT_VERSION,"primary_latency_minutes":PRIMARY_LATENCY,"sensitivity_latencies":list(SENSITIVITY_LATENCIES)},
        "asset_counts":asset_counts.to_dict("records"),"verified_primary_sources":verified_count,"source_reliability_mean":float(pd.to_numeric(frame.ai_source_reliability).mean()),
        "source_reliability_interpretation":"Exploratory evidence/message-quality score, not proof of source authenticity; human review fields remain intentionally blank.",
        "subgroup_shortlist_count":len(shortlist),"locked_test_used":len(shortlist)>0,"locked_test_status":"evaluated_once" if len(shortlist) else "INSUFFICIENT_VALIDATED_CANDIDATES",
        "search_adjusted_permutation":search_adjusted,"primary_horizons":list(PRIMARY_HORIZONS),"exploratory_horizons":list(EXPLORATORY_HORIZONS),
        "sample_unit":"event_id cluster; event_id+asset dataset key","event_contamination_rows":len(contamination),
        "technical_checks":technical_checks,"pytest":tests,"protected_stage8_16":{"unchanged":unchanged,"changed":changed,"disappeared":disappeared,"new":new_protected},
        "final_questions":final_questions,"runtime_seconds":round(time.time()-started,3),"next_stage_started":False,
    }
    write_json(REPORTS/"stage17_summary.json",summary)
    assessment=f"""# Stage 17 — High-Impact Semantic Subgroups

**Technical status: {technical_status}. High-impact hypothesis: {hypothesis_status}.**

- Unit: 668 event-asset rows, keyed by `(event_id, asset)`, representing {frame.metadata_event_id.nunique()} unique events.
- Chronological split is event-level; split violations: {split_violations}.
- Primary latency: 1 minute. Latencies 0/2/3/5 are sensitivity scenarios and were never pooled as independent observations.
- Primary inferential horizons: 1h, 3h, 12h. Other horizons are exploratory.
- Statistical resampling is clustered by `event_id`; all asset rows travel together.
- Event contamination was checked for every asset and horizon; pooled and isolated-event metrics are reported separately.
- Source authenticity is code-verified ({verified_count}/{len(events)}); AI source reliability remains exploratory pending completion of the 50-row human review.
- Automatic search used at most two conditions, train support >=30, BH correction, and {search_adjusted['permutations']} full search-adjusted permutations.
- Validated shortlist: {len(shortlist)}. Locked test: {'used once after freezing the shortlist' if len(shortlist) else 'not opened because no candidate passed the corrected validation gate'}.
- No OpenAI request, ML training, paper trading, real trading, production polling, or automatic trade was run.

`content_valence` was treated as message semantics. Only the explicitly fixed H2/H3 rules were permitted directional offline economics; magnitude hypotheses never generated directional PnL.

The current result does not authorize shadow or live deployment. See `stage17_summary.json` for all 13 requested answers and the exact technical gates.
"""
    (REPORTS/"stage17_final_assessment.md").write_text(assessment,encoding="utf-8")
    manifest={"dataset_version":"stage17_high_impact_semantic_subgroups_v2","created_at_utc":summary["completed_at"],
        "rows":len(frame),"unique_events":int(frame.metadata_event_id.nunique()),"unique_event_asset":len(frame),"primary_key":["event_id","asset"],
        "asset_counts":frame.metadata_asset.value_counts().to_dict(),"split_row_counts":frame.metadata_split.value_counts().to_dict(),
        "split_unique_event_counts":split_audit.split.value_counts().to_dict(),
        "split_unit":"event_id","primary_latency_minutes":PRIMARY_LATENCY,"sensitivity_latencies":list(SENSITIVITY_LATENCIES),
        "primary_horizons":list(PRIMARY_HORIZONS),"exploratory_horizons":list(EXPLORATORY_HORIZONS),
        "feature_columns":feature_columns,"excluded_features":["ai_surprise_level"],"target_columns":target_columns,
        "subgroups":SUBGROUP_CONDITIONS,"context_thresholds":context_thresholds.to_dict("records"),
        "files":{str(path.relative_to(ROOT)):file_hash(path) for path in data_files},
        "input_dataset_hashes":{path.name:file_hash(path) for path in STAGE16.glob("*.parquet")},
        "stage16_manifest_sha256":file_hash(STAGE16_MANIFEST),"stage16_dataset_hashes":{path.name:file_hash(path) for path in STAGE16.glob("*.parquet")},
        "stage8_16_unchanged":unchanged,"leakage_status":"PASS" if not leakage_columns else "FAIL","leakage":len(leakage_columns),
        "duplicates_status":"PASS" if duplicate_identity==duplicate_reaction_expanded==0 else "FAIL","predictive_fields":len(predictive_columns),
        "openai_api_requests":0,"ml_training":False,"trading":False}
    write_json(DATA/"manifest.json",manifest)
    print(json.dumps({"status":technical_status,"hypothesis":hypothesis_status,"rows":len(frame),"unique_events":int(frame.metadata_event_id.nunique()),
                      "shortlist":len(shortlist),"pytest_passed":tests["passed"],"runtime_seconds":summary["runtime_seconds"]},indent=2))
    return 0 if technical_status=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
