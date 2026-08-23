"""Stage 12 final event-level ETH ML dataset builder and quality audits."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from ml.stage11_dataset_builder import HORIZONS, load_analysis_rows, load_candle_grid

DATASET_VERSION = "stage12_eth_v1"
MODEL = "gpt-5-mini-2025-08-07"
PROMPT_VERSION = "eth_label_v1"
TARGET_HORIZONS = ("15m", "30m", "1h", "4h", "24h")
MARKET_WINDOWS = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "24h": 1440}
VOL_WINDOWS = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}
NEUTRAL_BANDS = {"010": .10, "025": .25, "050": .50, "100": 1.00}
STRONG_BANDS = {"025": .25, "050": .50, "100": 1.00, "200": 2.00}
IDENTITY_COLUMNS = ["dataset_version", "event_key", "news_id", "published_at", "baseline_time", "split"]
FORBIDDEN_FEATURE_FRAGMENTS = (
    "target_", "future_", "reaction", "abnormal_return", "max_favorable", "max_adverse",
    "raw_response", "actual_cost", "input_tokens", "output_tokens",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_counts(session: Session) -> dict[str, int]:
    names = ["news_articles", "news_assets", "news_analysis", "news_market_reactions", "market_candles", "news_market_context_analysis"]
    return {name: int(session.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()) for name in names}


def stage12_event_selection(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = frame.drop_duplicates("news_id").copy()
    data["event_key"] = data.event_group_id.where(
        data.event_group_id.notna(), data.news_id.map(lambda value: f"news:{int(value)}")
    )
    data = data.sort_values(
        ["event_key", "published_at", "time_confidence", "news_id"],
        ascending=[True, True, False, True], kind="mergesort",
    )
    counts = data.groupby("event_key").size().rename("article_count_in_event")
    selected = data.drop_duplicates("event_key", keep="first").join(counts, on="event_key")
    selected["selected_reason"] = np.where(
        selected.event_group_id.isna(), "synthetic_news_id_key",
        np.where(selected.article_count_in_event.eq(1), "only_article", "earliest_then_time_confidence_then_news_id"),
    )
    selection_columns = [
        "event_key", "event_group_id", "news_id", "source", "published_at", "baseline_time",
        "time_confidence", "article_count_in_event", "selected_reason",
    ]
    return selected.sort_values(["published_at", "news_id"]).reset_index(drop=True), selected[selection_columns].sort_values(["published_at", "news_id"]).reset_index(drop=True)


def chronological_split(frame: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    ordered = frame.sort_values(["published_at", "news_id"], kind="mergesort").index
    n = len(ordered); train_end = int(n * .60); validation_end = int(n * .80)
    labels = pd.Series(index=frame.index, dtype="object")
    labels.loc[ordered[:train_end]] = "train"
    labels.loc[ordered[train_end:validation_end]] = "validation"
    labels.loc[ordered[validation_end:]] = "test"

    def details(label: str) -> dict[str, Any]:
        part = frame.loc[labels.eq(label)].sort_values(["published_at", "news_id"])
        return {
            "count": len(part), "start": part.published_at.min().isoformat(), "end": part.published_at.max().isoformat(),
            "first_event_key": part.event_key.iloc[0], "last_event_key": part.event_key.iloc[-1],
        }

    chunks = np.array_split(ordered, 5)
    folds = []
    for fold in range(3):
        train_idx = np.concatenate(chunks[:fold + 2]); eval_idx = chunks[fold + 2]
        folds.append({
            "fold": fold + 1, "train_count": len(train_idx), "evaluation_count": len(eval_idx),
            "train_end": frame.loc[train_idx, "published_at"].max().isoformat(),
            "evaluation_start": frame.loc[eval_idx, "published_at"].min().isoformat(),
            "evaluation_end": frame.loc[eval_idx, "published_at"].max().isoformat(),
        })
    return labels, {"method": "chronological_60_20_20", "train": details("train"), "validation": details("validation"), "test": details("test"), "walk_forward_folds": folds}


def _tokenize(title: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(title).casefold()) if len(token) >= 3}


def algorithmic_event_features(selected: pd.DataFrame, all_rows: pd.DataFrame) -> pd.DataFrame:
    groups: dict[str, pd.DataFrame] = {}
    source = all_rows.drop_duplicates("news_id").copy()
    source["event_key"] = source.event_group_id.where(source.event_group_id.notna(), source.news_id.map(lambda x: f"news:{int(x)}"))
    for key, group in source.groupby("event_key"):
        groups[str(key)] = group.sort_values(["published_at", "time_confidence", "news_id"], ascending=[True, False, True])
    ordered = selected.sort_values(["published_at", "news_id"]).copy()
    history: deque[tuple[pd.Timestamp, set[str]]] = deque()
    rows = []
    for row in ordered.itertuples(index=False):
        timestamp = pd.Timestamp(row.published_at); tokens = _tokenize(row.title)
        while history and timestamp - history[0][0] > pd.Timedelta(days=30): history.popleft()
        similarities = [(timestamp - prior_time, len(tokens & prior) / len(tokens | prior) if tokens | prior else 0.0) for prior_time, prior in history]
        within7 = [score for age, score in similarities if age <= pd.Timedelta(days=7)]
        group = groups[row.event_key]
        second_minutes = None
        if len(group) > 1:
            second_minutes = (pd.Timestamp(group.published_at.iloc[1]) - pd.Timestamp(group.published_at.iloc[0])).total_seconds() / 60
        rows.append({
            "news_id": int(row.news_id), "metadata_event_article_count": int(row.article_count_in_event),
            "metadata_minutes_to_second_article": second_minutes,
            "metadata_source_rank_within_event": 1, "metadata_is_first_known_article": 1,
            "metadata_title_similarity_to_prior_7d": max(within7, default=0.0),
            "metadata_similar_event_count_prior_7d": sum(score >= .5 for score in within7),
            "metadata_similar_event_count_prior_30d": sum(score >= .5 for _, score in similarities),
        })
        history.append((timestamp, tokens))
    return pd.DataFrame(rows)


def _distance(current: float, reference: float) -> float:
    return (current / reference - 1.0) * 100.0 if reference else np.nan


def _extra_market_features(row: Any, eth: Any, btc: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = int(pd.Timestamp(row.metadata_target_baseline).timestamp() // 60)
    cutoff = baseline - 1
    result: dict[str, Any] = {}; target: dict[str, Any] = {}
    for symbol, grid in (("eth", eth), ("btc", btc)):
        end = grid.index(cutoff)
        if end is None: raise ValueError(f"Missing {symbol} cutoff candle for news {row.metadata_news_id}")
        current = float(grid.open[end])
        for label, minutes in MARKET_WINDOWS.items():
            start = end - minutes + 1
            opens = grid.open[start:end + 1]; highs = grid.high[start:end + 1]
            lows = grid.low[start:end + 1]; volumes = grid.volume[start:end + 1]
            result[f"pre_{symbol}_log_return_{label}"] = float(np.log(current / grid.open[end - minutes]) * 100)
            result[f"pre_{symbol}_high_low_range_{label}"] = float((np.max(highs) - np.min(lows)) / current * 100)
            result[f"pre_{symbol}_volume_zscore_{label}"] = float((volumes[-1] - np.mean(volumes)) / np.std(volumes, ddof=1)) if len(volumes) > 1 and np.std(volumes, ddof=1) else 0.0
        for window in (20, 50, 200):
            values = grid.open[end - window + 1:end + 1]
            result[f"pre_{symbol}_distance_sma{window}"] = _distance(current, float(np.mean(values)))
        for window in (20, 50):
            now = float(np.mean(grid.open[end - window + 1:end + 1])); before = float(np.mean(grid.open[end - 2 * window + 1:end - window + 1]))
            result[f"pre_{symbol}_sma{window}_slope"] = _distance(now, before) / window
            # Stage 11 already computes EMA distances without future data; expose canonical names below.
        if symbol == "eth":
            base = grid.index(baseline); finish = grid.index(baseline + 60)
            if base is None or finish is None: raise ValueError("Missing ETH 1h target window")
            price = float(grid.open[base]); highs = grid.high[base:finish]; lows = grid.low[base:finish]
            favorable = (highs / price - 1) * 100; adverse = (lows / price - 1) * 100
            absolute = np.maximum(np.abs(favorable), np.abs(adverse))
            target.update({
                "target_max_favorable_excursion_1h": float(np.max(favorable)),
                "target_max_adverse_excursion_1h": float(np.min(adverse)),
                "target_max_absolute_excursion_1h": float(np.max(absolute)),
                "target_time_to_max_move_1h": int(np.argmax(absolute)),
            })
    return result, target


def assemble_stage12(session: Session, stage11_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    all_rows = load_analysis_rows(session)
    selected, selection = stage12_event_selection(all_rows)
    stage11 = pd.read_parquet(stage11_path).sort_values(["metadata_published_at", "metadata_news_id"]).reset_index(drop=True)
    covered_ids = set(stage11.metadata_news_id.astype(int))
    selection["coverage_status"] = np.where(selection.news_id.isin(covered_ids), "included", "excluded_no_candle_coverage")
    coverage = selection.loc[selection.news_id.isin(covered_ids)].copy()
    covered_selected = selected.loc[selected.news_id.isin(covered_ids)].copy()
    split_frame = pd.DataFrame({"event_key": coverage.event_key, "news_id": coverage.news_id, "published_at": coverage.published_at})
    split, split_details = chronological_split(split_frame); coverage["split"] = split.values
    stage11_by_id = stage11.set_index("metadata_news_id")
    coverage["baseline_time"] = coverage.news_id.map(stage11_by_id.metadata_target_baseline)
    event_index = selection.merge(coverage[["news_id", "split", "baseline_time"]], on="news_id", how="left", suffixes=("", "_covered"))
    event_index["baseline_time"] = event_index["baseline_time_covered"].combine_first(event_index["baseline_time"])
    event_index = event_index.drop(columns=["baseline_time_covered"])
    event_index["split"] = event_index.split.fillna("excluded")
    event_index.insert(0, "dataset_version", DATASET_VERSION)

    novelty = algorithmic_event_features(covered_selected, all_rows)
    raw = covered_selected.set_index("news_id")
    features = pd.DataFrame({
        "dataset_version": DATASET_VERSION,
        "event_key": coverage.event_key.values, "news_id": coverage.news_id.astype(int).values,
        "published_at": list(pd.to_datetime(coverage.published_at, utc=True)),
        "baseline_time": list(pd.to_datetime(coverage.baseline_time, utc=True)),
        "split": coverage.split.values,
    })
    ids = features.news_id.tolist()
    s = stage11_by_id.loc[ids].reset_index(drop=True)
    r = raw.loc[ids].reset_index(drop=True)
    metadata = {
        "metadata_source": r.source.astype("string"), "metadata_hour_utc": s.metadata_hour_utc,
        "metadata_day_of_week": s.metadata_day_of_week, "metadata_is_weekend": s.metadata_weekend,
        "metadata_month": s.metadata_month, "metadata_session_asia": s.metadata_asia_session,
        "metadata_session_europe": s.metadata_eu_session, "metadata_session_us": s.metadata_us_session,
        "metadata_time_confidence": s.metadata_time_confidence,
        "metadata_article_count_in_event": s.metadata_article_count_in_event,
        "metadata_seconds_from_minute_boundary": s.metadata_seconds_from_candle_boundary,
    }
    ai = {
        "ai_sentiment": r.sentiment, "ai_importance": r.importance, "ai_novelty": r.novelty,
        "ai_credibility": r.credibility, "ai_confidence": r.confidence,
        "ai_eth_relevance": r.eth_relevance, "ai_direction": r.direction.astype("string"),
        "ai_category": r.category.astype("string"), "ai_horizon": r.ai_horizon.astype("string"),
    }
    for name, values in {**metadata, **ai}.items(): features[name] = list(values)
    features = features.merge(novelty, on="news_id", how="left")

    for symbol in ("eth", "btc"):
        for label in MARKET_WINDOWS:
            features[f"pre_{symbol}_return_{label}"] = s[f"pre_{symbol}_return_{label}"].values
        for label in VOL_WINDOWS:
            features[f"pre_{symbol}_realized_vol_{label}"] = s[f"pre_{symbol}_realized_vol_{label}"].values
            features[f"pre_{symbol}_volume_{label}"] = s[f"pre_{symbol}_volume_{label}"].values
        for window in (20, 50, 200):
            features[f"pre_{symbol}_distance_sma{window}"] = s[f"pre_{symbol}_price_vs_sma{window}"].values
        features[f"pre_{symbol}_sma20_slope"] = s[f"pre_{symbol}_sma20_slope"].values
        for window in (20, 50): features[f"pre_{symbol}_ema{window}_distance"] = s[f"pre_{symbol}_price_vs_ema{window}"].values
    for label in MARKET_WINDOWS:
        features[f"pre_eth_minus_btc_return_{label}"] = s[f"pre_eth_btc_relative_return_{label}"].values
    features["pre_eth_btc_rolling_beta"] = s.pre_beta_pre_news.values
    features["pre_eth_btc_rolling_correlation"] = s.pre_eth_btc_correlation_7d.values
    features["pre_eth_btc_relative_strength"] = s.pre_eth_btc_relative_return_24h.values
    features["pre_beta_fallback_used"] = s.metadata_beta_fallback_used.values

    eth, btc = load_candle_grid(session, "ETHUSDT"), load_candle_grid(session, "BTCUSDT")
    extra_rows=[]; excursion_rows=[]
    for row in s.itertuples(index=False):
        extra, excursion = _extra_market_features(row, eth, btc); extra_rows.append(extra); excursion_rows.append(excursion)
    extra = pd.DataFrame(extra_rows); excursions = pd.DataFrame(excursion_rows)
    extra = extra.drop(columns=[column for column in extra if column in features], errors="ignore")
    features = pd.concat([features.reset_index(drop=True), extra.reset_index(drop=True)], axis=1).copy()
    features["pre_btc_trend_state"] = np.where(
        (features.pre_btc_return_4h > .25) & (features.pre_btc_distance_sma200 > 0), "bull_trend",
        np.where((features.pre_btc_return_4h < -.25) & (features.pre_btc_distance_sma200 < 0), "bear_trend", "range"),
    )
    train_mask = features.split.eq("train")
    volatility_threshold = float(features.loc[train_mask, "pre_eth_realized_vol_1h"].median())
    features["pre_regime_trend"] = np.where(
        (features.pre_eth_return_4h > .25) & (features.pre_eth_distance_sma200 > 0), "bull_trend",
        np.where((features.pre_eth_return_4h < -.25) & (features.pre_eth_distance_sma200 < 0), "bear_trend", "range"),
    )
    features["pre_regime_volatility"] = np.where(features.pre_eth_realized_vol_1h > volatility_threshold, "high_volatility", "low_volatility")
    features["pre_regime_volume"] = np.where(features.pre_eth_volume_zscore_1h > 1, "high_volume", "normal_volume")
    direction = lambda values: np.where(values > .1, "positive", np.where(values < -.1, "negative", "flat"))
    features["pre_regime_btc_direction"] = direction(features.pre_btc_return_1h)
    features["pre_regime_eth_direction"] = direction(features.pre_eth_return_1h)
    features["pre_regime_relative_strength"] = np.where(features.pre_eth_btc_relative_strength > .1, "outperform", np.where(features.pre_eth_btc_relative_strength < -.1, "underperform", "neutral"))
    for prefix in ("pre_eth_", "pre_btc_", "pre_eth_minus_btc_"):
        columns = [column for column in features if column.startswith(prefix) and pd.api.types.is_numeric_dtype(features[column])]
        features[f"{prefix}context_missing"] = features[columns].isna().any(axis=1).astype(int)
    categorical = [column for column in features if pd.api.types.is_object_dtype(features[column]) or isinstance(features[column].dtype, pd.StringDtype)]
    for column in categorical: features[column] = features[column].fillna("__missing__")

    targets = features[IDENTITY_COLUMNS].copy()
    beta = s.pre_beta_pre_news.to_numpy(float)
    for label in TARGET_HORIZONS:
        abnormal = s[f"target_eth_return_{label}"].to_numpy(float) - beta * s[f"target_btc_return_{label}"].to_numpy(float)
        targets[f"target_abnormal_return_{label}"] = abnormal
        targets[f"target_abs_abnormal_return_{label}"] = np.abs(abnormal)
        for suffix, band in NEUTRAL_BANDS.items():
            targets[f"target_abnormal_direction_{label}_band_{suffix}"] = np.where(abnormal > band, "positive", np.where(abnormal < -band, "negative", "neutral"))
        for suffix, band in STRONG_BANDS.items(): targets[f"target_strong_abnormal_{label}_{suffix}"] = (np.abs(abnormal) >= band).astype(int)
    for label in VOL_WINDOWS: targets[f"target_realized_vol_{label}"] = s[f"target_future_realized_vol_{label}"].values
    for label in ("15m", "1h"):
        targets[f"target_volume_ratio_{label}"] = s[f"target_volume_ratio_{label}"].values
        targets[f"target_volume_shock_binary_{label}"] = (targets[f"target_volume_ratio_{label}"] >= 2.0).astype(int)
    for column in excursions: targets[column] = excursions[column].values

    cutoff_audit=[]
    for row in features[IDENTITY_COLUMNS].itertuples(index=False):
        max_input = pd.Timestamp(row.baseline_time) - pd.Timedelta(minutes=1)
        for group in ("eth_market", "btc_market", "relative_market", "regime"):
            cutoff_audit.append({"dataset_version":DATASET_VERSION,"event_key":row.event_key,"news_id":row.news_id,"feature_group":group,"max_input_open_time":max_input,"baseline_time":row.baseline_time,"violation":bool(max_input >= pd.Timestamp(row.baseline_time))})
    audit = pd.DataFrame(cutoff_audit)
    diagnostics = {
        "source_analysis_rows": len(all_rows), "selected_events": len(selection), "covered_events": len(features),
        "excluded_events": int((selection.coverage_status != "included").sum()), "split_details": split_details,
        "volatility_threshold_train_only": volatility_threshold,
        "abnormal_formula": "ETH_return_h - beta_pre_news * BTC_return_h",
        "beta_formula": "rolling 7d beta on 5m pre-news returns; fallback 1.0 with flag",
        "volume_shock_threshold": 2.0, "feature_cutoff_rule": "open_time < baseline_time",
    }
    return event_index, features, targets, {"cutoff_audit": audit, **diagnostics}


def feature_quality(features: pd.DataFrame) -> tuple[pd.DataFrame, list[str], pd.DataFrame, pd.DataFrame]:
    candidates = [column for column in features if column not in IDENTITY_COLUMNS]
    protected_provenance_flags = {"pre_beta_fallback_used"}
    rows=[]; remove: dict[str, str] = {}
    for column in candidates:
        series = features[column]; numeric = pd.api.types.is_numeric_dtype(series)
        finite = pd.to_numeric(series, errors="coerce") if numeric else None
        nonmissing = series.dropna(); counts = nonmissing.value_counts(dropna=False)
        constant = nonmissing.nunique(dropna=False) <= 1
        near = bool(len(counts) and counts.iloc[0] / max(1, len(nonmissing)) >= .999)
        missing_pct = float(series.isna().mean() * 100)
        reason = None
        if column not in protected_provenance_flags:
            if missing_pct > 40: reason = "missing_over_40pct"
            elif constant: reason = "zero_variance"
            elif near: reason = "near_constant_99_9pct"
        if reason: remove[column] = reason
        values = finite.replace([np.inf, -np.inf], np.nan).dropna() if numeric else pd.Series(dtype=float)
        p01, p50, p99 = (values.quantile(.01), values.quantile(.5), values.quantile(.99)) if len(values) else (None, None, None)
        rows.append({
            "dataset_version":DATASET_VERSION,"feature":column,"dtype":str(series.dtype),"group":feature_group(column),
            "count":int(series.notna().sum()),"missing_count":int(series.isna().sum()),"missing_percentage":round(missing_pct,6),
            "unique_count":int(nonmissing.nunique(dropna=False)),"mean":float(values.mean()) if len(values) else None,
            "std":float(values.std()) if len(values)>1 else None,"min":float(values.min()) if len(values) else None,
            "max":float(values.max()) if len(values) else None,"p01":float(p01) if p01 is not None else None,
            "p50":float(p50) if p50 is not None else None,"p99":float(p99) if p99 is not None else None,
            "constant":constant,"near_constant":near,"infinite_count":int(np.isinf(finite).sum()) if numeric else 0,
            "outlier_count":int(((finite < p01) | (finite > p99)).sum()) if numeric and p01 is not None else 0,
            "first_available_timestamp":features.loc[series.notna(),"published_at"].min(),
            "leakage_risk":column in {"title","body","raw_article_text"} or any(fragment in column.casefold() for fragment in FORBIDDEN_FEATURE_FRAGMENTS),
            "approved_for_ml":reason is None and column not in {"title","body","raw_article_text"} and not any(fragment in column.casefold() for fragment in FORBIDDEN_FEATURE_FRAGMENTS),
            "removal_reason":reason,
            "retention_reason":"required provenance/fallback indicator" if column in protected_provenance_flags else None,
        })
    numeric = [column for column in candidates if column not in remove and pd.api.types.is_numeric_dtype(features[column])]
    correlations = features[numeric].corr()
    for i, left in enumerate(numeric):
        for right in numeric[i+1:]:
            value = correlations.at[left, right]
            if pd.notna(value) and abs(value) > .9999 and right not in remove:
                remove[right] = f"duplicate_correlation_with:{left}:{value:.6f}"
    quality = pd.DataFrame(rows)
    quality.loc[quality.feature.isin(remove), "approved_for_ml"] = False
    quality.loc[quality.feature.isin(remove), "removal_reason"] = quality.loc[quality.feature.isin(remove), "feature"].map(remove)
    approved = [column for column in candidates if column not in remove and column not in {"title","body","raw_article_text"} and not any(fragment in column.casefold() for fragment in FORBIDDEN_FEATURE_FRAGMENTS)]
    removed = quality.loc[~quality.approved_for_ml, ["dataset_version","feature","group","removal_reason"]].copy()
    return quality, approved, correlations, removed


def feature_group(column: str) -> str:
    if column.startswith("ai_"): return "stage9_ai"
    if column.startswith("metadata_"): return "metadata"
    if column.startswith("pre_eth_minus_btc_") or column.startswith("pre_eth_btc_") or column.startswith("pre_beta_"): return "relative_market"
    if column.startswith("pre_eth_"): return "eth_market"
    if column.startswith("pre_btc_"): return "btc_market"
    if column.startswith("pre_regime_"): return "market_regime"
    return "other"


def target_quality(targets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    target_columns = [column for column in targets if column.startswith("target_")]
    quality=[]; stability=[]
    for column in target_columns:
        series = targets[column]; numeric = pd.api.types.is_numeric_dtype(series)
        row={"dataset_version":DATASET_VERSION,"target":column,"count":int(series.notna().sum()),"missing":int(series.isna().sum()),"missing_percentage":float(series.isna().mean()*100)}
        if numeric:
            values=pd.to_numeric(series,errors="coerce"); row.update({"mean":values.mean(),"median":values.median(),"std":values.std(),"min":values.min(),"max":values.max()})
            unique=set(values.dropna().unique()); binary=unique <= {0,1}
            row["positive_rate"] = float(values.mean()) if binary else None; row["base_rate"] = row["positive_rate"]
            row["neutral_rate"] = None; row["negative_rate"] = None; row["class_balance"] = json.dumps(dict(Counter(values.dropna().astype(str)))) if binary else None
        else:
            distribution=series.value_counts(normalize=True); row.update({"mean":None,"median":None,"std":None,"min":None,"max":None,"positive_rate":distribution.get("positive"),"neutral_rate":distribution.get("neutral"),"negative_rate":distribution.get("negative"),"base_rate":float(distribution.max()) if len(distribution) else None,"class_balance":json.dumps(series.value_counts().to_dict())})
        rates=[]
        for split in ("train","validation","test"):
            part=series[targets.split.eq(split)]; dist=part.value_counts(normalize=True,dropna=False).to_dict()
            stability.append({"dataset_version":DATASET_VERSION,"target":column,"split":split,"count":len(part),"mean":float(pd.to_numeric(part,errors="coerce").mean()) if numeric else None,"std":float(pd.to_numeric(part,errors="coerce").std()) if numeric else None,"distribution":json.dumps({str(k):float(v) for k,v in dist.items()})})
            if numeric and set(pd.to_numeric(part,errors="coerce").dropna().unique()) <= {0,1}: rates.append(float(pd.to_numeric(part,errors="coerce").mean()))
        row["rare_class_under_2pct"] = bool(row.get("positive_rate") is not None and (row["positive_rate"] < .02 or row["positive_rate"] > .98))
        row["strong_split_shift"] = bool(rates and max(rates)-min(rates) > .10)
        quality.append(row)
    quality_frame=pd.DataFrame(quality); stability_frame=pd.DataFrame(stability)
    candidates=["target_strong_abnormal_1h_050","target_strong_abnormal_4h_100","target_abs_abnormal_return_1h","target_realized_vol_1h"]
    recommended=[]
    for target in candidates:
        row=quality_frame.loc[quality_frame.target.eq(target)].iloc[0]
        if row.missing_percentage == 0 and not row.rare_class_under_2pct and not row.strong_split_shift: recommended.append(target)
    if len(recommended)<2:
        recommended=[target for target in candidates if quality_frame.loc[quality_frame.target.eq(target),"missing_percentage"].iloc[0] == 0][:4]
    return quality_frame, stability_frame, recommended[:4]


def missing_report(features: pd.DataFrame, approved: list[str], removed: pd.DataFrame) -> pd.DataFrame:
    removed_reason = dict(zip(removed.feature, removed.removal_reason)) if len(removed) else {}
    return pd.DataFrame([{
        "dataset_version":DATASET_VERSION,"feature":column,"missing_count":int(features[column].isna().sum()),
        "missing_percentage":float(features[column].isna().mean()*100),
        "reason":"unavailable pre-news history or source field" if features[column].isna().any() else "none",
        "allowed_feature":column in approved,"remove_feature":column not in approved,
        "removal_reason":removed_reason.get(column),"imputation_policy":"Stage 13 train-only pipeline; categorical __missing__; numeric NaN preserved",
    } for column in features if column not in IDENTITY_COLUMNS])


def split_distribution(targets: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    selected=[column for column in targets if column.startswith("target_strong_abnormal_")]
    for split in ("train","validation","test"):
        part=targets.loc[targets.split.eq(split)]
        for target in selected:
            rows.append({"dataset_version":DATASET_VERSION,"split":split,"target":target,"count":len(part),"positive_rate":float(part[target].mean()),"start":part.published_at.min(),"end":part.published_at.max()})
    return pd.DataFrame(rows)


def cost_scenarios() -> dict[str, Any]:
    return {"dataset_version":DATASET_VERSION,"costs_not_subtracted_from_targets":True,"scenarios":{
        "low":{"assumed_fee_bps":2,"assumed_slippage_bps":2,"latency_minutes":1,"round_trip_cost_bps":8},
        "base":{"assumed_fee_bps":5,"assumed_slippage_bps":5,"latency_minutes":1,"round_trip_cost_bps":20},
        "stress":{"assumed_fee_bps":10,"assumed_slippage_bps":15,"latency_minutes":2,"round_trip_cost_bps":50},
    }}


def git_commit(root: Path) -> str | None:
    try: return subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()
    except Exception: return None
