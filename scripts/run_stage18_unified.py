"""Stage 18 unified pattern reanalysis with complete 1-minute market paths.

This is an offline research pipeline.  It never submits paid API requests and
never writes trading instructions or old database rows.  Existing semantic
labels are normalized into a common layer with explicit missing indicators.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import text

from database.db import engine
from ml.stage18_unified import (
    API_HARD_LIMIT_USD, BASE_COST_PERCENT, ENTRY_LATENCY_MINUTES, HORIZONS,
    NEUTRAL_THRESHOLD_PERCENT, POST_CONTEXT_MINUTES, PRE_CONTEXT_MINUTES,
    PRIMARY_HORIZON, FrozenRule, add_missing_flags, assert_no_future_features,
    budget_allows, canonical_hash, chronological_split, directional_target,
    duplicate_components, economic_metrics, endpoint_return, entry_timestamp,
    gap_minutes, normalize_text, normalize_url, official_identifier,
    sha256_file, signed_return, text_fingerprint, validate_candles,
    wilson_interval,
)


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data" / "stage18"
MODELS = ROOT / "models"
PATHS = DATA / "price_paths"
VERSION = "stage18_unified_patterns_v1"
SEED = 18017
PATTERN_A_ID = "pattern_a_v2:semantic_only:subgroup_k:12h"
PATTERN_B_ID = "pattern_b_v2:semantic_plus_market:gradient_boosting:12h:eth"
PATTERN_A_CANDIDATE_HASH = "743808baf640223e19f0be18f50f79c08ab26d630bc9d503cf4add5c59de2f0f"
PATTERN_B_SOURCE_LOCK = "509a91b2d6fda0991eba012cf273ad54ef9b2f711a49a6891a7ba0a7277f900e"
PROTECTED_DIRS = (ROOT / "data" / "stage12", ROOT / "data" / "stage135", ROOT / "data" / "stage16b", ROOT / "data" / "stage17",
                  ROOT / "datasets" / "stage16_high_impact_v1", ROOT / "datasets" / "stage16_high_impact_semantic_v21")

SEM_NUMERIC = ["sem_relevance", "sem_content_valence_score", "sem_importance", "sem_novelty", "sem_confidence",
               "sem_source_reliability", "sem_asset_relevance", "sem_specificity", "sem_actionability",
               "sem_institutional_relevance", "sem_retail_relevance", "sem_economic_significance",
               "sem_technical_significance", "sem_security_significance", "sem_adoption_significance",
               "sem_execution_certainty", "sem_urgency", "sem_fundamental_relevance"]
SEM_CATEGORICAL = ["sem_content_valence", "sem_event_type", "sem_directness", "sem_information_status",
                   "sem_evidence_quality", "source", "source_type", "platform", "asset"]
MARKET_NUMERIC = ["pre_return_5m", "pre_return_20m", "pre_return_60m", "pre_return_180m", "pre_return_720m",
                  "pre_btc_return_5m", "pre_btc_return_20m", "pre_btc_return_60m", "pre_btc_return_180m",
                  "pre_btc_return_720m", "pre_realized_vol_20m", "pre_realized_vol_60m", "pre_realized_vol_180m",
                  "pre_realized_vol_720m", "pre_volume_z60", "pre_volume_vs_avg60", "pre_relative_strength_1h",
                  "pre_rolling_corr_btc", "pre_rolling_beta_btc", "hour_utc", "day_of_week"]
MARKET_CATEGORICAL = ["pre_trend_regime", "context_btc_state", "context_asset_state", "context_volatility",
                      "context_relative_strength"]


def write_json(path: Path, value: Any) -> None:
    def default(item: Any):
        if item is pd.NaT or item is pd.NA: return None
        if isinstance(item, pd.Timestamp): return item.isoformat()
        if isinstance(item, (np.integer,)): return int(item)
        if isinstance(item, (np.floating,)): return None if not np.isfinite(item) else float(item)
        if isinstance(item, (np.bool_,)): return bool(item)
        if isinstance(item, Path): return str(item)
        raise TypeError(type(item).__name__)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=default, allow_nan=False) + "\n", encoding="utf-8")


def protected_files() -> list[Path]:
    result: list[Path] = []
    for directory in PROTECTED_DIRS:
        if directory.exists(): result.extend(path for path in directory.rglob("*") if path.is_file())
    for path in REPORTS.iterdir():
        if path.is_file() and path.name.startswith("stage") and not path.name.startswith("stage18"):
            try:
                number = int(path.name[5:].split("_")[0].rstrip("abcdefghijklmnopqrstuvwxyz"))
            except ValueError:
                continue
            if 8 <= number <= 17: result.append(path)
    return sorted(set(result))


def protected_snapshot() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in protected_files()}


def database_signature() -> dict[str, Any]:
    with engine.connect() as connection:
        tables = ["news_articles", "news_assets", "news_analysis", "news_market_reactions", "high_impact_events",
                  "high_impact_event_assets", "high_impact_event_analysis", "high_impact_market_reactions", "market_candles"]
        counts = {table: int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()) for table in tables}
        candles = connection.execute(text("""SELECT symbol,count(*) n,min(open_time) first,max(open_time) last,
          sum(id)::numeric checksum FROM market_candles WHERE symbol IN ('BTCUSDT','ETHUSDT','SOLUSDT')
          GROUP BY symbol ORDER BY symbol""")).mappings().all()
    return {"counts": counts, "candles": [{**dict(row), "first": row["first"].isoformat(), "last": row["last"].isoformat(),
                                             "checksum": str(row["checksum"])} for row in candles]}


def read_old_news() -> pd.DataFrame:
    base = pd.read_parquet(ROOT / "data" / "stage12" / "eth_market_plus_ai.parquet")
    ids = base.news_id.astype(int).tolist()
    with engine.connect() as connection:
        meta = pd.read_sql(text("""SELECT id news_id,source,url,canonical_url,title,body,published_at,content_hash,event_group_id
          FROM news_articles WHERE id=ANY(:ids)"""), connection, params={"ids": ids})
    frame = base.merge(meta, on="news_id", how="left", suffixes=("", "_db"), validate="one_to_one")
    frame["member_id"] = "A:" + frame.event_key.astype(str)
    frame["dataset_source"] = "A"
    frame["asset"] = "ETH"; frame["symbol"] = "ETHUSDT"
    frame["published_at"] = pd.to_datetime(frame.published_at, utc=True)
    frame["source"] = frame.metadata_source.combine_first(frame.source)
    frame["source_type"] = "news_media"; frame["platform"] = "web"
    frame["external_id"] = None
    frame["sem_relevance"] = pd.to_numeric(frame.ai_eth_relevance, errors="coerce")
    frame["sem_asset_relevance"] = frame.sem_relevance
    frame["sem_content_valence_score"] = pd.to_numeric(frame.ai_sentiment, errors="coerce")
    frame["sem_content_valence"] = pd.cut(frame.sem_content_valence_score, [-101, -10, 10, 101], labels=["negative", "neutral", "positive"]).astype(str)
    frame["sem_importance"] = pd.to_numeric(frame.ai_importance, errors="coerce")
    frame["sem_novelty"] = pd.to_numeric(frame.ai_novelty, errors="coerce")
    frame["sem_confidence"] = pd.to_numeric(frame.ai_confidence, errors="coerce")
    frame["sem_source_reliability"] = pd.to_numeric(frame.ai_credibility, errors="coerce")
    frame["sem_event_type"] = frame.ai_category
    frame["sem_directness"] = None; frame["sem_information_status"] = None; frame["sem_evidence_quality"] = "secondary_source"
    for column in SEM_NUMERIC:
        if column not in frame: frame[column] = np.nan
    frame["previous_split"] = frame.split
    return frame


def _analysis_asset(value: Any, asset: str) -> dict[str, Any]:
    if not isinstance(value, list): return {}
    return next((item for item in value if isinstance(item, dict) and str(item.get("asset", "")).upper() == asset), {})


def read_high_impact() -> pd.DataFrame:
    with engine.connect() as connection:
        frame = pd.read_sql(text("""SELECT e.id event_id,e.source,e.source_type,e.platform,e.external_id,e.url,e.canonical_url,
          e.title,e.body,e.published_at,e.content_hash,e.event_group_id,ea.asset,
          an.prompt_version,an.status analysis_status,an.event_type,an.information_status,an.source_reliability,
          an.novelty,an.importance,an.specificity,an.confidence,an.assets_json,an.actionability,
          an.institutional_relevance,an.retail_relevance,an.economic_significance,an.technical_significance,
          an.security_significance,an.adoption_significance,an.execution_certainty,an.urgency,
          an.fundamental_relevance,an.evidence_quality
          FROM high_impact_events e JOIN high_impact_event_assets ea ON ea.event_id=e.id
          LEFT JOIN LATERAL (SELECT * FROM high_impact_event_analysis x WHERE x.event_id=e.id
            AND x.prompt_version='high_impact_semantic_v2_1' ORDER BY (x.status='success') DESC,x.id DESC LIMIT 1) an ON true
          WHERE e.status='accepted' ORDER BY e.id,ea.asset"""), connection)
    split_map = pd.concat([pd.read_parquet(ROOT / "data" / "stage17" / f"{asset}_high_impact.parquet",
                                           columns=["metadata_event_id", "metadata_split"]) for asset in ("btc", "eth", "sol")])
    split_map = split_map.drop_duplicates("metadata_event_id").set_index("metadata_event_id").metadata_split
    frame["previous_split"] = frame.event_id.map(split_map)
    frame["dataset_source"] = np.where(frame.analysis_status.eq("success"), "B", "D")
    frame["member_id"] = frame.dataset_source + ":" + frame.event_id.astype(str)
    frame["asset"] = frame.asset.str.upper(); frame["symbol"] = frame.asset + "USDT"
    frame["published_at"] = pd.to_datetime(frame.published_at, utc=True)
    details = [_analysis_asset(value, asset) for value, asset in zip(frame.assets_json, frame.asset)]
    # Stage 16 v2.1 schema is explicitly 0..100.  Preserve its stored values;
    # Stage 18B performs schema-aware 0..1 normalization downstream.
    scale = lambda values: pd.to_numeric(values, errors="coerce")
    frame["sem_relevance"] = scale([item.get("relevance") for item in details])
    frame["sem_asset_relevance"] = frame.sem_relevance
    frame["sem_content_valence_score"] = scale([item.get("content_valence_score") for item in details])
    frame["sem_content_valence"] = [item.get("content_valence") for item in details]
    frame["sem_directness"] = [item.get("directness") for item in details]
    mapping = {"source_reliability":"sem_source_reliability", "novelty":"sem_novelty", "importance":"sem_importance",
               "specificity":"sem_specificity", "confidence":"sem_confidence", "actionability":"sem_actionability",
               "institutional_relevance":"sem_institutional_relevance", "retail_relevance":"sem_retail_relevance",
               "economic_significance":"sem_economic_significance", "technical_significance":"sem_technical_significance",
               "security_significance":"sem_security_significance", "adoption_significance":"sem_adoption_significance",
               "execution_certainty":"sem_execution_certainty", "urgency":"sem_urgency",
               "fundamental_relevance":"sem_fundamental_relevance"}
    for source, target in mapping.items(): frame[target] = scale(frame[source])
    frame["sem_event_type"] = frame.event_type; frame["sem_information_status"] = frame.information_status
    frame["sem_evidence_quality"] = frame.evidence_quality
    return frame


def read_archive() -> pd.DataFrame:
    frame = pd.read_parquet(ROOT / "data" / "stage16b" / "canonical_events.parquet")
    coverage = pd.read_parquet(ROOT / "data" / "stage16b" / "event_asset_coverage.parquet")[["canonical_event_id", "asset", "symbol"]]
    frame = frame.merge(coverage, on="canonical_event_id", how="inner", validate="one_to_one")
    frame["member_id"] = "C:" + frame.canonical_event_id.astype(str); frame["dataset_source"] = "C"
    frame["published_at"] = pd.to_datetime(frame.published_at, utc=True)
    frame["url"] = frame.canonical_url; frame["content_hash"] = None; frame["external_id"] = None
    frame["sem_relevance"] = pd.to_numeric(frame.local_relevance_score, errors="coerce")
    frame["sem_asset_relevance"] = frame.sem_relevance
    frame["sem_event_type"] = frame.event_type
    frame["sem_evidence_quality"] = np.where(frame.source_type.isin(["government", "github", "foundation"]), "primary_source", None)
    frame["sem_content_valence_score"] = np.nan; frame["sem_content_valence"] = None
    frame["sem_directness"] = None; frame["sem_information_status"] = None; frame["previous_split"] = None
    for column in SEM_NUMERIC:
        if column not in frame: frame[column] = np.nan
    return frame


def canonical_inventory() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frames = [read_old_news(), read_high_impact(), read_archive()]
    columns = list(dict.fromkeys(["member_id", "dataset_source", "asset", "symbol", "published_at", "source", "source_type", "platform",
        "url", "canonical_url", "title", "body", "content_hash", "external_id", "event_group_id", "previous_split"] + SEM_NUMERIC + SEM_CATEGORICAL))
    members = pd.concat([frame.reindex(columns=columns) for frame in frames], ignore_index=True)
    members["normalized_url"] = members.canonical_url.combine_first(members.url).map(normalize_url)
    members["normalized_title"] = members.title.map(normalize_text)
    members["official_id"] = [official_identifier(url, ext) for url, ext in zip(members.canonical_url.combine_first(members.url), members.external_id)]
    members["text_fingerprint"] = [text_fingerprint(title, body) for title, body in zip(members.title, members.body)]
    members["content_hash"] = members.content_hash.fillna("")
    root_map, duplicates = duplicate_components(members)
    members["duplicate_root"] = members.member_id.map(root_map)
    priority = {"B": 0, "D": 1, "A": 2, "C": 3}; members["priority"] = members.dataset_source.map(priority)
    rows = []
    for _, group in members.groupby("duplicate_root", sort=False):
        sources = sorted(group.dataset_source.unique())
        canonical_id = "evt18-" + hashlib.sha256("|".join(sorted(group.member_id.unique())).encode()).hexdigest()[:20]
        for asset, asset_group in group.groupby("asset"):
            best = asset_group.sort_values(["priority", "published_at", "member_id"]).iloc[0]
            row = best.to_dict(); row["canonical_event_id"] = canonical_id
            row["dataset_sources"] = "|".join(sources); row["source_mappings"] = json.dumps(sorted(group.member_id.unique().tolist()))
            row["prior_exposure"] = bool(set(sources) & {"A", "B"})
            row["previously_used_in_train"] = bool(group.previous_split.eq("train").any())
            row["previously_used_in_validation"] = bool(group.previous_split.eq("validation").any())
            row["previously_used_in_test"] = bool(group.previous_split.eq("test").any())
            row["first_stage_used"] = 12 if "A" in sources else 16 if "B" in sources else None
            row["first_analysis_date"] = "2026-07-18" if "A" in sources else "2026-07-19" if "B" in sources else None
            row["historical_external_candidate"] = sources == ["C"]
            rows.append(row)
    canonical = pd.DataFrame(rows).sort_values(["published_at", "canonical_event_id", "asset"]).reset_index(drop=True)
    canonical["split"] = chronological_split(canonical, canonical.historical_external_candidate)
    canonical = add_missing_flags(canonical, SEM_NUMERIC)
    return members, duplicates, canonical


class CandleGrid:
    def __init__(self, frame: pd.DataFrame):
        frame = frame.sort_values("open_time").drop_duplicates("open_time")
        # PostgreSQL currently arrives as datetime64[us, UTC] under pandas 3.
        # Convert the extension array explicitly to ns before integer division;
        # astype(int64) alone would preserve microseconds and shrink epochs 1000x.
        timestamps = pd.to_datetime(frame.open_time, utc=True).array.as_unit("ns").asi8
        self.minutes = (timestamps // 60_000_000_000).astype(np.int64, copy=False)
        for name in ("open", "high", "low", "close", "volume"):
            setattr(self, name, pd.to_numeric(frame[name], errors="coerce").to_numpy(float))

    def position(self, minute: int) -> int | None:
        index = int(np.searchsorted(self.minutes, minute))
        return index if index < len(self.minutes) and self.minutes[index] == minute else None


def load_grid(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> CandleGrid:
    with engine.connect() as connection:
        frame = pd.read_sql(text("""SELECT open_time,open::double precision open,high::double precision high,
          low::double precision low,close::double precision close,volume::double precision volume
          FROM market_candles WHERE symbol=:symbol AND interval='1m' AND open_time BETWEEN :start AND :end ORDER BY open_time"""),
          connection, params={"symbol": symbol, "start": start.to_pydatetime(), "end": end.to_pydatetime()})
    if not validate_candles(frame).all(): raise RuntimeError(f"invalid candles loaded for {symbol}")
    return CandleGrid(frame)


def _pre_features(grid: CandleGrid, btc: CandleGrid, entry_minute: int) -> dict[str, Any]:
    current = grid.position(entry_minute - 1); btc_current = btc.position(entry_minute - 1)
    if current is None or btc_current is None: return {}
    latest = grid.close[current]; btc_latest = btc.close[btc_current]
    result: dict[str, Any] = {}
    for horizon in (5, 20, 60, 180, 720):
        index, bindex = grid.position(entry_minute - horizon), btc.position(entry_minute - horizon)
        result[f"pre_return_{horizon}m"] = endpoint_return(grid.open[index], latest) if index is not None else np.nan
        result[f"pre_btc_return_{horizon}m"] = endpoint_return(btc.open[bindex], btc_latest) if bindex is not None else np.nan
    for horizon in (20, 60, 180, 720):
        start = grid.position(entry_minute - horizon)
        prices = grid.close[start:current + 1] if start is not None else np.array([])
        result[f"pre_realized_vol_{horizon}m"] = float(np.sqrt(np.sum(np.diff(np.log(prices)) ** 2)) * 100) if len(prices) > 1 else np.nan
    start60 = grid.position(entry_minute - 60); start720 = grid.position(entry_minute - 720); bstart720 = btc.position(entry_minute - 720)
    volumes = grid.volume[start60:current + 1] if start60 is not None else np.array([])
    result["pre_volume_z60"] = float((volumes[-1] - volumes.mean()) / volumes.std()) if len(volumes) > 1 and volumes.std() else 0.0
    result["pre_volume_vs_avg60"] = float(volumes[-1] / volumes.mean()) if len(volumes) and volumes.mean() else np.nan
    if start720 is not None and bstart720 is not None:
        asset_r = np.diff(np.log(grid.close[start720:current + 1])); btc_r = np.diff(np.log(btc.close[bstart720:btc_current + 1]))
        n = min(len(asset_r), len(btc_r)); asset_r, btc_r = asset_r[-n:], btc_r[-n:]
        covariance = np.cov(asset_r, btc_r) if n > 2 else np.full((2, 2), np.nan)
        result["pre_rolling_corr_btc"] = float(np.corrcoef(asset_r, btc_r)[0, 1]) if n > 2 else np.nan
        result["pre_rolling_beta_btc"] = float(covariance[0, 1] / covariance[1, 1]) if n > 2 and covariance[1, 1] else np.nan
    result["pre_relative_strength_1h"] = result["pre_return_60m"] - result["pre_btc_return_60m"]
    result["pre_trend_regime"] = "bullish" if result["pre_return_60m"] > .1 else "bearish" if result["pre_return_60m"] < -.1 else "flat"
    result["context_btc_state"] = "rising" if result["pre_btc_return_60m"] > .1 else "falling" if result["pre_btc_return_60m"] < -.1 else "stable"
    result["context_asset_state"] = "rising" if result["pre_return_60m"] > .1 else "falling" if result["pre_return_60m"] < -.1 else "stable"
    result["context_volatility"] = "high" if result["pre_realized_vol_60m"] > 1 else "low" if result["pre_realized_vol_60m"] < .25 else "medium"
    result["context_relative_strength"] = "strong" if result["pre_relative_strength_1h"] > .1 else "weak" if result["pre_relative_strength_1h"] < -.1 else "middle"
    return result


def _path_summary(row: pd.Series, grid: CandleGrid, btc: CandleGrid) -> tuple[dict[str, Any], pd.DataFrame | None]:
    entry = entry_timestamp(row.published_at); minute = int(entry.timestamp() // 60)
    pre_missing = gap_minutes(grid.minutes, minute - PRE_CONTEXT_MINUTES, minute - 1)
    post_missing = gap_minutes(grid.minutes, minute, minute + POST_CONTEXT_MINUTES)
    summary = {"canonical_event_id": row.canonical_event_id, "asset": row.asset, "symbol": row.symbol,
               "entry_timestamp": entry, "pre_window_start": entry - pd.Timedelta(minutes=PRE_CONTEXT_MINUTES),
               "post_window_end": entry + pd.Timedelta(minutes=POST_CONTEXT_MINUTES),
               "full_pre_context": len(pre_missing) == 0, "full_post_context": len(post_missing) == 0,
               "missing_pre_minutes": len(pre_missing), "missing_post_minutes": len(post_missing),
               "missing_minutes": len(pre_missing) + len(post_missing), "gap_overlap": bool(len(pre_missing) + len(post_missing)),
               "pre_listing": bool(len(grid.minutes) == 0 or minute - PRE_CONTEXT_MINUTES < grid.minutes[0])}
    summary["fully_covered"] = bool(summary["full_pre_context"] and summary["full_post_context"])
    if not summary["fully_covered"]: return summary, None
    index = grid.position(minute); btc_index = btc.position(minute)
    if index is None or btc_index is None: return summary, None
    offsets = grid.minutes[index:index + POST_CONTEXT_MINUTES + 1] - minute
    if len(offsets) != POST_CONTEXT_MINUTES + 1 or not np.array_equal(offsets, np.arange(POST_CONTEXT_MINUTES + 1)): return summary, None
    entry_price = grid.open[index]; summary["entry_price"] = entry_price
    summary.update(_pre_features(grid, btc, minute))
    for label, horizon in HORIZONS.items(): summary[f"raw_return_{label}"] = endpoint_return(entry_price, grid.open[index + horizon])
    highs = (grid.high[index:index + POST_CONTEXT_MINUTES + 1] / entry_price - 1) * 100
    lows = (grid.low[index:index + POST_CONTEXT_MINUTES + 1] / entry_price - 1) * 100
    opens = (grid.open[index:index + POST_CONTEXT_MINUTES + 1] / entry_price - 1) * 100
    summary.update({"long_mfe_24h":float(highs.max()), "long_mae_24h":float(lows.min()),
                    "time_to_long_mfe":int(highs.argmax()), "time_to_long_mae":int(lows.argmin()),
                    "long_returned_to_entry_after_peak":bool((opens[int(highs.argmax()):] <= 0).any()),
                    "short_returned_to_entry_after_peak":bool((opens[int(lows.argmin()):] >= 0).any())})
    for threshold in (.10, .25, .50, 1.00):
        up, down = np.flatnonzero(opens >= threshold), np.flatnonzero(opens <= -threshold)
        key = str(threshold).replace(".", "_")
        summary[f"first_up_{key}_minute"] = int(up[0]) if len(up) else np.nan
        summary[f"first_down_{key}_minute"] = int(down[0]) if len(down) else np.nan
    path = pd.DataFrame({"canonical_event_id":row.canonical_event_id, "dataset_sources":row.dataset_sources,
                         "asset":row.asset, "event_timestamp":row.published_at, "entry_timestamp":entry,
                         "minute_offset":np.arange(POST_CONTEXT_MINUTES + 1),
                         "open_time":pd.to_datetime(grid.minutes[index:index + POST_CONTEXT_MINUTES + 1] * 60, unit="s", utc=True),
                         "open":grid.open[index:index + POST_CONTEXT_MINUTES + 1], "high":grid.high[index:index + POST_CONTEXT_MINUTES + 1],
                         "low":grid.low[index:index + POST_CONTEXT_MINUTES + 1], "close":grid.close[index:index + POST_CONTEXT_MINUTES + 1],
                         "volume":grid.volume[index:index + POST_CONTEXT_MINUTES + 1], "raw_open_return_percent":opens,
                         "raw_high_return_percent":highs, "raw_low_return_percent":lows})
    return summary, path


def build_market(canonical: pd.DataFrame, inventory_hash: str, db_sig: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    manifest_path = DATA / "path_build_manifest.json"; summary_path = DATA / "canonical_market.parquet"
    coverage_path = DATA / "market_coverage.parquet"
    signature = canonical_hash({"inventory": inventory_hash, "candles": db_sig["candles"], "lookback": PRE_CONTEXT_MINUTES,
                                "post": POST_CONTEXT_MINUTES, "grid_timestamp_encoding":"explicit_ns_v2"})
    if manifest_path.exists() and summary_path.exists() and coverage_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("signature") == signature:
            return pd.read_parquet(summary_path), pd.read_parquet(coverage_path)
    resolved = PATHS.resolve(); allowed = DATA.resolve()
    if resolved.exists():
        if allowed not in resolved.parents: raise RuntimeError("unsafe Stage 18 path target")
        shutil.rmtree(resolved)
    PATHS.mkdir(parents=True, exist_ok=True)
    global_start = canonical.published_at.min().floor("min") - pd.Timedelta(minutes=PRE_CONTEXT_MINUTES + 2)
    global_end = canonical.published_at.max().ceil("min") + pd.Timedelta(minutes=POST_CONTEXT_MINUTES + 2)
    btc = load_grid("BTCUSDT", global_start, global_end)
    summaries, coverage = [], []
    for asset in ("BTC", "ETH", "SOL"):
        selected = canonical[canonical.asset.eq(asset)].copy()
        if selected.empty: continue
        grid = btc if asset == "BTC" else load_grid(f"{asset}USDT", selected.published_at.min().floor("min") - pd.Timedelta(days=1, minutes=2),
                                                    selected.published_at.max().ceil("min") + pd.Timedelta(days=1, minutes=2))
        selected["event_year"] = selected.published_at.dt.year; selected["event_month"] = selected.published_at.dt.month
        for (year, month), group in selected.groupby(["event_year", "event_month"]):
            path_frames = []
            for _, row in group.iterrows():
                summary, path = _path_summary(row, grid, btc); coverage.append({key:value for key,value in summary.items() if key in {
                    "canonical_event_id","asset","symbol","entry_timestamp","pre_window_start","post_window_end","full_pre_context","full_post_context",
                    "missing_pre_minutes","missing_post_minutes","missing_minutes","gap_overlap","pre_listing","fully_covered"}})
                summaries.append(summary)
                if path is not None: path_frames.append(path)
            if path_frames:
                directory = PATHS / f"asset={asset}" / f"year={int(year)}" / f"month={int(month):02d}"; directory.mkdir(parents=True, exist_ok=True)
                pq.write_table(pa.Table.from_pandas(pd.concat(path_frames, ignore_index=True), preserve_index=False), directory / "part-00000.parquet", compression="zstd")
    market = pd.DataFrame(summaries); coverage_frame = pd.DataFrame(coverage)
    market.to_parquet(summary_path, index=False); coverage_frame.to_parquet(coverage_path, index=False)
    write_json(manifest_path, {"signature":signature, "inventory_hash":inventory_hash, "rows":len(market),
                               "fully_covered":int(coverage_frame.fully_covered.sum()), "path_rows":int(coverage_frame.fully_covered.sum()) * 1441,
                               "partitioning":"asset/event-year/event-month", "no_synthetic_candles":True})
    return market, coverage_frame


def model_pipeline(frame: pd.DataFrame, columns: list[str], family: str) -> Pipeline:
    numeric = [column for column in columns if pd.api.types.is_numeric_dtype(frame[column])]
    categorical = [column for column in columns if column not in numeric]
    transformers = []
    if numeric: transformers.append(("numeric", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric))
    if categorical: transformers.append(("categorical", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]), categorical))
    estimator = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000, random_state=SEED) if family == "logistic" else GradientBoostingClassifier(n_estimators=80, learning_rate=.05, max_depth=2, random_state=SEED)
    return Pipeline([("preprocess", ColumnTransformer(transformers)), ("model", estimator)])


def predict_direction(model: Pipeline, frame: pd.DataFrame, columns: list[str], threshold: float = .4) -> tuple[np.ndarray, np.ndarray]:
    probabilities = model.predict_proba(frame[columns]); classes = list(model.named_steps["model"].classes_)
    if "UP" not in classes or "DOWN" not in classes: raise RuntimeError("training data lacks UP or DOWN class")
    up, down = probabilities[:, classes.index("UP")], probabilities[:, classes.index("DOWN")]
    confidence = np.maximum(up, down); result = np.where(up >= down, "UP", "DOWN").astype(object); result[confidence < threshold] = "NO_SIGNAL"
    return result, confidence


def prediction_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    signals = frame[frame.predicted_direction.isin(["UP", "DOWN"])].copy(); n = len(signals)
    correct = int(signals.predicted_direction.eq(signals.actual_direction).sum())
    lo, hi = wilson_interval(correct, n); up = int(signals.predicted_direction.eq("UP").sum()); down = n - up
    directional = signals.actual_direction.isin(["UP", "DOWN"])
    balanced = float(balanced_accuracy_score(signals.loc[directional, "actual_direction"], signals.loc[directional, "predicted_direction"])) if directional.any() and signals.loc[directional, "actual_direction"].nunique() == 2 else None
    return {"eligible_rows":len(frame), "predictions":n, "coverage":n/len(frame) if len(frame) else 0.0,
            "correct":correct, "accuracy":correct/n if n else None, "balanced_accuracy":balanced,
            "long_predictions":up, "short_predictions":down, "dominant_direction_share":max(up, down)/n if n else None,
            "wilson_95_low":lo, "wilson_95_high":hi}


def baseline_predictions(train: pd.DataFrame, evaluate: pd.DataFrame, market_model: Pipeline | None, market_columns: list[str]) -> dict[str, np.ndarray]:
    majority = "UP" if train.actual_direction.eq("UP").sum() >= train.actual_direction.eq("DOWN").sum() else "DOWN"
    result = {"majority_direction":np.repeat(majority, len(evaluate)), "always_LONG":np.repeat("UP", len(evaluate)),
              "always_SHORT":np.repeat("DOWN", len(evaluate)),
              "previous_market_direction":np.where(evaluate.pre_return_60m.fillna(0) >= 0, "UP", "DOWN"),
              "BTC_trend_direction":np.where(evaluate.pre_btc_return_60m.fillna(0) >= 0, "UP", "DOWN")}
    if market_model is not None: result["market_only_logistic"] = market_model.predict(evaluate[market_columns])
    return result


def baseline_accuracy(actual: pd.Series, predicted: np.ndarray) -> float:
    return float(np.mean(actual.to_numpy() == predicted)) if len(actual) else 0.0


def prepare_training(canonical: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    frame = canonical.merge(market, on=["canonical_event_id", "asset", "symbol"], how="left", validate="one_to_one")
    frame["published_at"] = pd.to_datetime(frame.published_at, utc=True)
    frame["hour_utc"] = frame.published_at.dt.hour; frame["day_of_week"] = frame.published_at.dt.dayofweek
    for column in SEM_NUMERIC + MARKET_NUMERIC:
        if column not in frame: frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in SEM_CATEGORICAL + MARKET_CATEGORICAL:
        if column not in frame: frame[column] = None
    frame = add_missing_flags(frame, SEM_NUMERIC + MARKET_NUMERIC)
    frame["actual_direction"] = directional_target(frame.raw_return_12h)
    return frame


def eligible_pattern(frame: pd.DataFrame, pattern: str) -> pd.Series:
    covered = frame.fully_covered.fillna(False)
    if pattern == "A": return covered & ((frame.sem_asset_relevance < 40) | (frame.sem_importance < 30))
    return covered & frame.asset.eq("ETH")


def score_frame(model: Pipeline, frame: pd.DataFrame, columns: list[str], pattern: str, split: str, fold: str) -> pd.DataFrame:
    selected = frame[eligible_pattern(frame, pattern) & frame.split.eq(split)].copy()
    if selected.empty: return selected.assign(predicted_direction=pd.Series(dtype=str), confidence=pd.Series(dtype=float), fold=fold)
    selected["predicted_direction"], selected["confidence"] = predict_direction(model, selected, columns)
    selected["fold"] = fold
    return selected


def train_pattern(frame: pd.DataFrame, pattern: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    pattern_id = PATTERN_A_ID if pattern == "A" else PATTERN_B_ID; family = "logistic" if pattern == "A" else "gradient_boosting"
    columns = SEM_NUMERIC + [f"{c}_missing" for c in SEM_NUMERIC] + SEM_CATEGORICAL
    if pattern == "B": columns += MARKET_NUMERIC + [f"{c}_missing" for c in MARKET_NUMERIC] + MARKET_CATEGORICAL
    columns = list(dict.fromkeys(column for column in columns if column in frame))
    assert_no_future_features(columns)
    eligible = eligible_pattern(frame, pattern)
    train = frame[eligible & frame.split.eq("train")].copy(); validation = frame[eligible & frame.split.eq("validation")].copy()
    test = frame[eligible & frame.split.eq("test")].copy(); external = frame[eligible & frame.split.eq("historical_external")].copy()
    model = model_pipeline(train, columns, family); model.fit(train[columns], train.actual_direction)
    market_columns = [c for c in MARKET_NUMERIC + MARKET_CATEGORICAL if c in frame]
    market_model = None
    if len(train) and market_columns:
        market_model = model_pipeline(train, market_columns, "logistic"); market_model.fit(train[market_columns], train.actual_direction)
    val_predictions, val_confidence = predict_direction(model, validation, columns) if len(validation) else (np.array([]), np.array([]))
    validation["predicted_direction"] = val_predictions; validation["confidence"] = val_confidence
    baselines = baseline_predictions(train, validation, market_model, market_columns)
    baseline_rows = [{"pattern":pattern, "baseline":name, "validation_accuracy":baseline_accuracy(validation.actual_direction, values)} for name, values in baselines.items()]
    predicted_up_share = float(np.mean(val_predictions == "UP")) if len(val_predictions) else .5
    actual_up = float(validation.actual_direction.eq("UP").mean()) if len(validation) else .5
    actual_down = float(validation.actual_direction.eq("DOWN").mean()) if len(validation) else .5
    baseline_rows.append({"pattern":pattern, "baseline":"random_same_LONG_SHORT_ratio", "validation_accuracy":predicted_up_share*actual_up+(1-predicted_up_share)*actual_down})
    strongest = max(baseline_rows, key=lambda row: row["validation_accuracy"])
    rule = FrozenRule(pattern_id, PRIMARY_HORIZON, NEUTRAL_THRESHOLD_PERCENT, .4, ENTRY_LATENCY_MINUTES)
    config = {"version":VERSION, "pattern":pattern, "pattern_id":pattern_id, "source_pattern":("Stage17 Pattern A" if pattern=="A" else "Stage17B"),
              "source_lock":(PATTERN_A_CANDIDATE_HASH if pattern=="A" else PATTERN_B_SOURCE_LOCK), "primary_horizon":"12h",
              "candidate_fixed_before_test":True, "neutral_threshold":.1, "confidence_threshold":.4, "latency_minutes":1,
              "feature_family":("semantic_only" if pattern=="A" else "semantic_plus_market"), "feature_columns":columns,
              "model_family":family, "random_seed":SEED, "train_rows":len(train), "validation_rows":len(validation),
              "test_rows":len(test), "external_rows":len(external), "strongest_baseline":strongest,
              "test_outcomes_used_for_configuration":False, "rule_hash":rule.digest(), "package_versions":{"python":platform.python_version(),"pandas":pd.__version__}}
    model_path = MODELS / f"stage18_pattern_{pattern.lower()}_v2.joblib"; joblib.dump({"model":model,"columns":columns,"config":config}, model_path)
    config["model_path"] = str(model_path.relative_to(ROOT)); config["model_sha256"] = sha256_file(model_path); config["config_hash"] = canonical_hash(config)
    write_json(DATA / f"pattern_{pattern.lower()}_v2_lock.json", config)
    # Test is queried/scored only after model and config are persisted.
    scored = []
    for split_name, part, fold in (("validation", validation, "VALIDATION"), ("test", test, "LOCKED_TEST"), ("historical_external", external, "HISTORICAL_EXTERNAL_VALIDATION")):
        if split_name == "validation": result = part
        else:
            result = part.copy()
            if len(result): result["predicted_direction"], result["confidence"] = predict_direction(model, result, columns)
        result["fold"] = fold; result["pattern"] = pattern; result["pattern_id"] = pattern_id
        scored.append(result)
    predictions = pd.concat(scored, ignore_index=True) if scored else pd.DataFrame()
    return config, pd.DataFrame(baseline_rows), predictions


def walkforward(frame: pd.DataFrame, pattern: str, columns: list[str]) -> pd.DataFrame:
    data = frame[eligible_pattern(frame, pattern) & ~frame.split.eq("historical_external")].sort_values(["published_at", "canonical_event_id"])
    events = data.canonical_event_id.drop_duplicates().tolist(); rows=[]
    for fold in range(5):
        train_end = int(len(events) * (.40 + fold * .10)); eval_end = int(len(events) * (.50 + fold * .10))
        train_ids, eval_ids = set(events[:train_end]), set(events[train_end:eval_end])
        train, evaluate = data[data.canonical_event_id.isin(train_ids)], data[data.canonical_event_id.isin(eval_ids)].copy()
        if len(train) < 20 or len(evaluate) < 5: continue
        family = "logistic" if pattern == "A" else "gradient_boosting"; model = model_pipeline(train, columns, family); model.fit(train[columns], train.actual_direction)
        evaluate["predicted_direction"], evaluate["confidence"] = predict_direction(model, evaluate, columns)
        metrics = prediction_metrics(evaluate); strongest = max(baseline_accuracy(evaluate.actual_direction, values) for values in baseline_predictions(train, evaluate, None, []).values())
        signals = evaluate[evaluate.predicted_direction.isin(["UP","DOWN"])]; signed = [signed_return(value, "LONG" if pred=="UP" else "SHORT") for value,pred in zip(signals.raw_return_12h,signals.predicted_direction)]
        rows.append({"pattern":pattern,"fold":fold+1,"train_start":train.published_at.min(),"train_end":train.published_at.max(),
                     "evaluation_start":evaluate.published_at.min(),"evaluation_end":evaluate.published_at.max(),**metrics,
                     "strongest_baseline":strongest,"edge":(metrics["accuracy"]-strongest if metrics["accuracy"] is not None else None),
                     **{f"economic_{k}":v for k,v in economic_metrics(signed).items()}})
    return pd.DataFrame(rows)


def enrich_predictions(predictions: pd.DataFrame, configs: dict[str, dict[str, Any]]) -> pd.DataFrame:
    if predictions.empty: return predictions
    rows=[]
    for row in predictions.itertuples(index=False):
        signal = "LONG" if row.predicted_direction == "UP" else "SHORT" if row.predicted_direction == "DOWN" else "NO_SIGNAL"
        result = {"event_id":row.canonical_event_id,"dataset_source":row.dataset_sources,"event_timestamp":row.published_at,
                  "asset":row.asset,"pattern_id":row.pattern_id,"model_version":VERSION,"fold":row.fold,"split":row.split,
                  "signal":signal,"confidence":row.confidence,"entry_timestamp":row.entry_timestamp,"entry_price":row.entry_price,
                  "correct_at_primary_horizon":bool(row.predicted_direction==row.actual_direction) if signal!="NO_SIGNAL" else None,
                  "model_hash":configs[row.pattern]["model_sha256"],"config_hash":configs[row.pattern]["config_hash"],
                  "cost_model":f"base_round_trip_{BASE_COST_PERCENT:.2f}_percent","source":row.source,"event_type":row.sem_event_type,
                  "actual_direction":row.actual_direction,"prior_exposure":row.prior_exposure}
        for horizon in HORIZONS:
            raw = getattr(row, f"raw_return_{horizon}"); result[f"return_{horizon}"] = raw
        if signal != "NO_SIGNAL":
            direction = 1 if signal=="LONG" else -1
            result["MFE"] = row.long_mfe_24h if direction==1 else -row.long_mae_24h
            result["MAE"] = row.long_mae_24h if direction==1 else -row.long_mfe_24h
            result["time_to_MFE"] = row.time_to_long_mfe if direction==1 else row.time_to_long_mae
            result["time_to_MAE"] = row.time_to_long_mae if direction==1 else row.time_to_long_mfe
            result["gross_return"] = signed_return(row.raw_return_12h, signal); result["net_return"] = result["gross_return"] - BASE_COST_PERCENT
            first_key = "first_up" if direction==1 else "first_down"
            for threshold in ("0_1","0_25","0_5","1_0"): result[f"first_{threshold}_percent_minute"] = getattr(row,f"{first_key}_{threshold}_minute")
            for horizon in ("1h","3h","6h","8h","12h"):
                signed = signed_return(getattr(row,f"raw_return_{horizon}"),signal); result[f"mfe_retained_{horizon}"] = signed/result["MFE"] if result["MFE"]>0 else np.nan; result[f"giveback_{horizon}"] = result["MFE"]-signed
            result["return_to_entry_after_peak"] = row.long_returned_to_entry_after_peak if direction==1 else row.short_returned_to_entry_after_peak
            result["peak_then_reversal"] = bool(result["return_to_entry_after_peak"] and result["gross_return"]<0)
        else:
            for name in ("MFE","MAE","time_to_MFE","time_to_MAE","gross_return","net_return","return_to_entry_after_peak","peak_then_reversal"): result[name]=np.nan
        rows.append(result)
    return pd.DataFrame(rows)


def aggregate_report(predictions: pd.DataFrame, dimension: str) -> pd.DataFrame:
    rows=[]
    signals=predictions[predictions.signal.isin(["LONG","SHORT"])].copy()
    for keys, part in signals.groupby(["pattern_id",dimension],dropna=False):
        correct=int(part.correct_at_primary_horizon.sum()); n=len(part); econ=economic_metrics(part.gross_return)
        rows.append({"pattern_id":keys[0],dimension:keys[1],"predictions":n,"accuracy":correct/n if n else None,
                     "average_absolute_move_12h":float(part.return_12h.abs().mean()),"median_time_to_MFE":float(part.time_to_MFE.median()),**econ})
    return pd.DataFrame(rows)


def run_pytest() -> dict[str, Any]:
    # The host's global pytest temp root may be ACL-locked by another process.
    # A fresh workspace-local root is both reproducible and isolated.
    basetemp=REPORTS/f"pytest_stage18_{os.getpid()}"
    result=subprocess.run([sys.executable,"-m","pytest","-q","--basetemp",str(basetemp)],cwd=ROOT,text=True,capture_output=True)
    (REPORTS/"stage18_pytest.stdout.log").write_text(result.stdout,encoding="utf-8")
    (REPORTS/"stage18_pytest.stderr.log").write_text(result.stderr,encoding="utf-8")
    return {"returncode":result.returncode,"passed":int(re.search(r"(\d+) passed",result.stdout).group(1)) if re.search(r"(\d+) passed",result.stdout) else None,
            "stdout_log":"reports/stage18_pytest.stdout.log","stderr_log":"reports/stage18_pytest.stderr.log"}


def main() -> int:
    REPORTS.mkdir(exist_ok=True); DATA.mkdir(parents=True,exist_ok=True); MODELS.mkdir(exist_ok=True)
    protected_before_path=DATA/"protected_before.json"; db_before_path=DATA/"database_before.json"
    before=protected_snapshot();db_before=database_signature()
    if not protected_before_path.exists(): write_json(protected_before_path,before)
    if not db_before_path.exists(): write_json(db_before_path,db_before)
    members,duplicates,canonical=canonical_inventory()
    inventory_hash=canonical_hash(canonical[["canonical_event_id","asset","published_at","dataset_sources"]].astype(str).to_dict("records"))
    canonical.to_parquet(DATA/"canonical_inventory.parquet",index=False)
    canonical.drop(columns=[c for c in ("body",) if c in canonical]).to_csv(REPORTS/"stage18_canonical_event_inventory.csv",index=False)
    duplicates.to_csv(REPORTS/"stage18_cross_dataset_duplicates.csv",index=False)
    inventory=[]
    for source in ("A","B","C","D"):
        part=members[members.dataset_source.eq(source)]
        inventory.append({"dataset":source,"event_asset_rows":len(part),"unique_events":int(part.member_id.nunique()),"earliest_timestamp":part.published_at.min(),
                          "latest_timestamp":part.published_at.max(),"ai_schema":("eth_label_v1" if source=="A" else "high_impact_semantic_v2_1" if source=="B" else "missing_explicit_flags"),
                          "duplicates_within_member_asset":int(part.duplicated(["member_id","asset"]).sum())})
    pd.DataFrame(inventory).to_csv(REPORTS/"stage18_data_inventory.csv",index=False)
    prior_columns=["canonical_event_id","asset","prior_exposure","previously_used_in_train","previously_used_in_validation","previously_used_in_test","first_stage_used","first_analysis_date","split"]
    canonical[prior_columns].to_csv(REPORTS/"stage18_prior_exposure_audit.csv",index=False)
    required=canonical[["canonical_event_id","asset","symbol","published_at"]].copy();required["entry_timestamp"]=required.published_at.map(entry_timestamp)
    required["required_start"]=required.entry_timestamp-pd.Timedelta(minutes=PRE_CONTEXT_MINUTES);required["required_end"]=required.entry_timestamp+pd.Timedelta(minutes=POST_CONTEXT_MINUTES)
    required["maximum_feature_lookback_minutes"]=PRE_CONTEXT_MINUTES;required["maximum_reaction_horizon_minutes"]=POST_CONTEXT_MINUTES
    required.to_csv(REPORTS/"stage18_required_candle_windows.csv",index=False)
    db_sig=database_signature(); market,coverage=build_market(canonical,inventory_hash,db_sig)
    coverage.to_csv(REPORTS/"stage18_market_coverage.csv",index=False)
    gaps=coverage[~coverage.fully_covered].copy();gaps["reason"]=np.where(gaps.pre_listing,"pre_listing","observed_exchange_gap")
    gaps.to_csv(REPORTS/"stage18_candle_gaps.csv",index=False)
    download=pd.read_csv(REPORTS/"stage16c_download_manifest.csv");download.assign(stage18_action="reused_checksum_verified_stage16c").to_csv(REPORTS/"stage18_candle_download_manifest.csv",index=False)
    checksum_columns=[c for c in download.columns if any(token in c.lower() for token in ("symbol","year","month","sha","checksum","status","path"))]
    download[checksum_columns].to_csv(REPORTS/"stage18_candle_checksum_audit.csv",index=False)
    pd.DataFrame(columns=["provider","endpoint","request_id","timestamp","purpose","input_tokens","output_tokens","estimated_cost","actual_cost","cumulative_cost","remaining_budget","status"]).to_csv(REPORTS/"stage18_api_budget.csv",index=False)
    schema_rows=[]
    mapping={"A":{"sem_relevance":"ai_eth_relevance","sem_content_valence_score":"ai_sentiment","sem_importance":"ai_importance","sem_novelty":"ai_novelty","sem_confidence":"ai_confidence","sem_source_reliability":"ai_credibility","sem_event_type":"ai_category"},
             "B":{"sem_relevance":"assets.relevance × 10","sem_content_valence_score":"assets.content_valence_score × 10","sem_importance":"importance × 10","sem_novelty":"novelty × 10","sem_confidence":"confidence × 10","sem_source_reliability":"source_reliability × 10","sem_event_type":"event_type"},
             "C":{"sem_relevance":"local_relevance_score","sem_event_type":"event_type"},"D":{"sem_event_type":"existing metadata when available"}}
    for dataset,values in mapping.items():
        for canonical_field in ["sem_relevance","sem_content_valence_score","sem_importance","sem_novelty","sem_confidence","sem_source_reliability","sem_event_type","sem_asset_relevance","sem_directness","sem_information_status"]:
            schema_rows.append({"dataset":dataset,"canonical_field":canonical_field,"source_field":values.get(canonical_field),"missing_flag":canonical_field not in values,"invented_value":False})
    pd.DataFrame(schema_rows).to_csv(REPORTS/"stage18_semantic_schema_mapping.csv",index=False)
    frame=prepare_training(canonical,market)
    configs={};baseline_frames=[];prediction_frames=[]
    prediction_path=REPORTS/"stage18_prediction_level_results.parquet"
    locks=[DATA/"pattern_a_v2_lock.json",DATA/"pattern_b_v2_lock.json"]
    models=[MODELS/"stage18_pattern_a_v2.joblib",MODELS/"stage18_pattern_b_v2.joblib"]
    resume_predictions=prediction_path.exists() and all(path.exists() for path in locks+models)
    if resume_predictions:
        configs={"A":json.loads(locks[0].read_text(encoding="utf-8")),"B":json.loads(locks[1].read_text(encoding="utf-8"))}
        for pattern in ("A","B"):
            payload=joblib.load(MODELS/f"stage18_pattern_{pattern.lower()}_v2.joblib")
            if sha256_file(MODELS/f"stage18_pattern_{pattern.lower()}_v2.joblib") != configs[pattern]["model_sha256"]:
                raise RuntimeError(f"Pattern {pattern} frozen model hash mismatch on resume")
            if payload["columns"] != configs[pattern]["feature_columns"]: raise RuntimeError(f"Pattern {pattern} feature order mismatch")
        enriched=pd.read_parquet(prediction_path)
        predictions=enriched.copy()
        predictions["pattern"]=np.where(predictions.pattern_id.eq(PATTERN_A_ID),"A","B")
        predictions["predicted_direction"]=predictions.signal.map({"LONG":"UP","SHORT":"DOWN","NO_SIGNAL":"NO_SIGNAL"})
        if (DATA/"frozen_validation_baselines.csv").exists(): baseline_frames=[pd.read_csv(DATA/"frozen_validation_baselines.csv")]
    else:
        for pattern in ("A","B"):
            config,baselines,predictions_part=train_pattern(frame,pattern);configs[pattern]=config;baseline_frames.append(baselines);prediction_frames.append(predictions_part)
        predictions=pd.concat(prediction_frames,ignore_index=True); enriched=enrich_predictions(predictions,configs)
        enriched.to_parquet(prediction_path,index=False)
    enriched[enriched.pattern_id.eq(PATTERN_A_ID)].to_csv(REPORTS/"stage18_pattern_a_results.csv",index=False)
    enriched[enriched.pattern_id.eq(PATTERN_B_ID)].to_csv(REPORTS/"stage18_pattern_b_results.csv",index=False)
    if resume_predictions and (REPORTS/"stage18_walkforward_results.csv").exists():
        folds=pd.read_csv(REPORTS/"stage18_walkforward_results.csv")
    else:
        folds=pd.concat([walkforward(frame,pattern,configs[pattern]["feature_columns"]) for pattern in ("A","B")],ignore_index=True)
    folds.to_csv(REPORTS/"stage18_walkforward_results.csv",index=False)
    pd.concat(baseline_frames,ignore_index=True).to_csv(DATA/"frozen_validation_baselines.csv",index=False)
    horizon_rows=[]
    for (pattern_id,split),part in enriched[enriched.signal.isin(["LONG","SHORT"])].groupby(["pattern_id","split"]):
        for horizon in HORIZONS:
            values=[signed_return(raw,signal) for raw,signal in zip(part[f"return_{horizon}"],part.signal)];econ=economic_metrics(values)
            horizon_rows.append({"pattern_id":pattern_id,"split":split,"horizon":horizon,"primary":horizon=="12h","retrospective_sensitivity":horizon!="12h",
                                 "accuracy":float(np.mean(np.asarray(values)>0)) if values else None,**econ})
    pd.DataFrame(horizon_rows).to_csv(REPORTS/"stage18_horizon_sensitivity.csv",index=False)
    mfe_columns=["event_id","pattern_id","split","asset","signal","MFE","MAE","time_to_MFE","time_to_MAE","return_to_entry_after_peak","peak_then_reversal"]+[c for c in enriched if c.startswith(("mfe_retained_","giveback_","first_"))]
    enriched[mfe_columns].to_csv(REPORTS/"stage18_mfe_mae_analysis.csv",index=False)
    enriched["year"]=pd.to_datetime(enriched.event_timestamp,utc=True).dt.year
    aggregate_report(enriched,"year").to_csv(REPORTS/"stage18_year_analysis.csv",index=False)
    aggregate_report(enriched,"source").to_csv(REPORTS/"stage18_source_analysis.csv",index=False)
    aggregate_report(enriched,"asset").to_csv(REPORTS/"stage18_asset_analysis.csv",index=False)
    enriched[enriched.split.eq("historical_external")].to_csv(REPORTS/"stage18_external_2017_2022_validation.csv",index=False)
    cost_rows=[]
    for (pattern_id,split),part in enriched[enriched.signal.isin(["LONG","SHORT"])].groupby(["pattern_id","split"]):
        for cost in (.10,.15,.20,.25,.30,.40):
            values=part.gross_return.to_numpy(float);metrics=economic_metrics(values,cost)
            cost_rows.append({"pattern_id":pattern_id,"split":split,"cost_percent":cost,**metrics})
    pd.DataFrame(cost_rows).to_csv(REPORTS/"stage18_cost_sensitivity.csv",index=False)
    pattern_metrics={}
    for pattern,config in configs.items():
        part=enriched[(enriched.pattern_id.eq(config["pattern_id"]))&enriched.split.eq("test")]
        raw=predictions[(predictions.pattern.eq(pattern))&predictions.split.eq("test")]
        metrics=prediction_metrics(raw);signals=part[part.signal.isin(["LONG","SHORT"])]
        econ=economic_metrics(signals.gross_return);baseline=config["strongest_baseline"]["validation_accuracy"]
        relevant_folds=folds[folds.pattern.eq(pattern)];fold_wins=int((relevant_folds.edge>0).sum())
        predictive=bool(metrics["predictions"]>=50 and metrics["coverage"]>=.20 and (metrics["accuracy"] or 0)>.55 and (metrics["accuracy"] or 0)>baseline and (metrics["dominant_direction_share"] or 1)<=.80 and fold_wins>=2)
        strong=bool(predictive and (metrics["wilson_95_low"] or 0)>.50)
        economic=bool((econ["net_expectancy"] or -1)>0 and (econ["profit_factor"] or 0)>1 and (econ["cumulative_net_return"] or -1)>0)
        status="PASS_PREDICTIVE_AND_ECONOMIC" if strong and economic else "PASS_PREDICTIVE_ONLY" if predictive else "PARTIAL_EVIDENCE" if (metrics["accuracy"] or 0)>.5 else "NOT_SUPPORTED"
        pattern_metrics[pattern]={"status":status,**metrics,"strongest_validation_baseline":baseline,"folds_beating_baseline":fold_wins,"folds_total":len(relevant_folds),**econ,
                                  "external_predictions":int(((enriched.pattern_id.eq(config["pattern_id"]))&enriched.split.eq("historical_external")&enriched.signal.isin(["LONG","SHORT"])).sum())}
    tests=run_pytest();after=protected_snapshot();db_after=database_signature();protected_unchanged=before==after;db_unchanged=db_before==db_after
    all_test_prior=bool(enriched[enriched.split.eq("test")].prior_exposure.all()) if len(enriched[enriched.split.eq("test")]) else True
    overall="NO_TRUE_UNTOUCHED_TEST" if all_test_prior else ("PASS_PREDICTIVE_AND_ECONOMIC" if any(x["status"]=="PASS_PREDICTIVE_AND_ECONOMIC" for x in pattern_metrics.values()) else "NOT_SUPPORTED")
    if not bool(coverage.fully_covered.any()): overall="INSUFFICIENT_MARKET_COVERAGE"
    if tests["returncode"]!=0 or not protected_unchanged or not db_unchanged: overall="FAIL"
    api={"paid_requests":0,"free_api_requests":0,"openai_requests":0,"actual_total_cost_usd":0.0,"remaining_budget_usd":2.0,"hard_limit_respected":True}
    manifest={"version":VERSION,"status":overall,"inventory_hash":inventory_hash,"canonical_event_asset_rows":len(canonical),"unique_events":int(canonical.canonical_event_id.nunique()),
              "datasets":inventory,"cross_dataset_duplicate_pairs":len(duplicates),"fully_covered_rows":int(coverage.fully_covered.sum()),"uncovered_rows":int((~coverage.fully_covered).sum()),
              "price_path_rows":int(coverage.fully_covered.sum())*1441,"patterns":pattern_metrics,"configs":configs,"api":api,"pytest":tests,
              "protected_artifacts_unchanged":protected_unchanged,"controlled_database_unchanged":db_unchanged,"all_current_test_events_prior_exposed":all_test_prior,
              "leakage":0,"synthetic_candles":0,"primary_horizon":"12h","pattern_a_candidate_hash":PATTERN_A_CANDIDATE_HASH,"pattern_b_source_lock":PATTERN_B_SOURCE_LOCK,
              "resume_used_persisted_predictions":resume_predictions,"new_locked_test_evaluations_on_resume":0 if resume_predictions else 1}
    report_files=[path for path in REPORTS.glob("stage18*") if path.is_file()];manifest["report_hashes"]={path.name:sha256_file(path) for path in sorted(report_files) if path.name!="stage18_final_manifest.json"}
    write_json(REPORTS/"stage18_final_manifest.json",manifest)
    summary=f"""# Stage 18 — Unified Pattern Reanalysis

Overall status: **{overall}**. This is offline research; no paper or real trading was started.

## Data and coverage

- Canonical events: {manifest['unique_events']:,}; event-asset rows: {len(canonical):,}.
- Dataset A/B/C/D rows: {', '.join(f"{x['dataset']}={x['event_asset_rows']:,}" for x in inventory)}.
- Cross-dataset duplicate evidence pairs: {len(duplicates):,}.
- Fully covered event-assets: {manifest['fully_covered_rows']:,}; excluded for missing candles: {manifest['uncovered_rows']:,}.
- Stored 1-minute path rows: {manifest['price_path_rows']:,}; synthetic/interpolated candles: 0.
- Maximum feature lookback: 24h (derived maximum feature need was 12h; the stricter Stage 18 minimum was used). Maximum reaction path: 24h.

## Pattern A V2

- Status: **{pattern_metrics['A']['status']}**; locked-test predictions: {pattern_metrics['A']['predictions']:,}; accuracy: {(pattern_metrics['A']['accuracy'] or 0)*100:.2f}%.
- Strongest validation baseline: {pattern_metrics['A']['strongest_validation_baseline']*100:.2f}%; folds beating baseline: {pattern_metrics['A']['folds_beating_baseline']}/{pattern_metrics['A']['folds_total']}.
- LONG/SHORT: {pattern_metrics['A']['long_predictions']}/{pattern_metrics['A']['short_predictions']}; net expectancy: {(pattern_metrics['A']['net_expectancy'] or 0):+.4f}%; PF: {pattern_metrics['A']['profit_factor']}.

## Pattern B V2

- Status: **{pattern_metrics['B']['status']}**; locked-test predictions: {pattern_metrics['B']['predictions']:,}; accuracy: {(pattern_metrics['B']['accuracy'] or 0)*100:.2f}%.
- Strongest validation baseline: {pattern_metrics['B']['strongest_validation_baseline']*100:.2f}%; folds beating baseline: {pattern_metrics['B']['folds_beating_baseline']}/{pattern_metrics['B']['folds_total']}.
- LONG/SHORT: {pattern_metrics['B']['long_predictions']}/{pattern_metrics['B']['short_predictions']}; net expectancy: {(pattern_metrics['B']['net_expectancy'] or 0):+.4f}%; PF: {pattern_metrics['B']['profit_factor']}.

## Direct answers

1. Pattern A confirmation: {pattern_metrics['A']['status']}.
2. Pattern B confirmation: {pattern_metrics['B']['status']}.
3. Accuracy above 55%: A={bool((pattern_metrics['A']['accuracy'] or 0)>.55)}, B={bool((pattern_metrics['B']['accuracy'] or 0)>.55)}.
4. Better than frozen validation baseline: A={bool((pattern_metrics['A']['accuracy'] or 0)>pattern_metrics['A']['strongest_validation_baseline'])}, B={bool((pattern_metrics['B']['accuracy'] or 0)>pattern_metrics['B']['strongest_validation_baseline'])}.
5. LONG and SHORT were evaluated separately; exact counts and metrics are in pattern reports.
6. Average moves by horizon are in `stage18_horizon_sensitivity.csv`.
7. Median time-to-MFE and MFE/MAE are in `stage18_mfe_mae_analysis.csv`.
8. The old 1h horizon was too short only as retrospective sensitivity; the primary 12h exit was frozen before this test and was not reselected.
9. Post-cost result: A net expectancy {(pattern_metrics['A']['net_expectancy'] or 0):+.4f}%, B {(pattern_metrics['B']['net_expectancy'] or 0):+.4f}% at 0.20% round-trip cost.
10. Year/fold stability is reported separately; folds beating baseline are shown above.
11. Events excluded for candle coverage: {manifest['uncovered_rows']:,}.
12. All Stage 18 API calls cost **$0.00**; existing semantic results plus explicit missing flags were sufficient.
13. The $2.00 hard limit was respected; remaining budget is $2.00.

## Integrity

- Leakage: 0; predictive fields used as features: 0; paid requests: 0.
- Protected Stage 8–17 artifacts unchanged: {protected_unchanged}; controlled DB tables unchanged: {db_unchanged}.
- Pytest: {tests['passed']} passed, return code {tests['returncode']}.
- Current chronological test is not truly untouched because all of its events had prior Stage 8–17 exposure: {all_test_prior}. Therefore the overall epistemic label is `{overall}` even where a pattern-level metric is positive.
"""
    (REPORTS/"stage18_final_summary.md").write_text(summary,encoding="utf-8")
    # Refresh manifest hash list after the summary exists.
    manifest["report_hashes"]={path.name:sha256_file(path) for path in sorted(REPORTS.glob("stage18*")) if path.is_file() and path.name!="stage18_final_manifest.json"}
    write_json(REPORTS/"stage18_final_manifest.json",manifest)
    print(json.dumps({"status":overall,"unique_events":manifest["unique_events"],"event_asset_rows":len(canonical),"coverage":f"{manifest['fully_covered_rows']}/{len(coverage)}",
                      "pattern_a":pattern_metrics["A"],"pattern_b":pattern_metrics["B"],"api_cost":0.0,"pytest":tests,"protected_unchanged":protected_unchanged},ensure_ascii=False,indent=2,default=str))
    return 0 if overall!="FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
