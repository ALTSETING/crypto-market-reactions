"""Build the read-only derived MVP website event dataset.

The script never modifies canonical, raw, or research inputs.  It writes only
``data/website/events_mvp.{parquet,csv}`` and the accompanying audit report.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as pads
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

from high_impact_sources.parsers.crypto_relevance_detector import detect_crypto_relevance


ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = ROOT / "data" / "stage18b" / "canonical_inventory.parquet"
MARKET_PATH = ROOT / "data" / "stage18b" / "canonical_market.parquet"
PATHS_DIR = ROOT / "data" / "stage18" / "price_paths"
STAGE16_PATH = ROOT / "reports" / "stage16_market_reactions.parquet"
STAGE13A_PATH = ROOT / "reports" / "stage13a_eth_early_returns.parquet"
STAGE11_PATH = ROOT / "reports" / "stage11_eth_abnormal_returns.parquet"
OUTPUT_DIR = ROOT / "data" / "website"
PARQUET_OUTPUT = OUTPUT_DIR / "events_mvp.parquet"
CSV_OUTPUT = OUTPUT_DIR / "events_mvp.csv"
REPORT_OUTPUT = ROOT / "docs" / "WEBSITE_DATASET_REPORT.md"

ASSETS = ("BTC", "ETH", "SOL")
HORIZONS = ("1m", "5m", "15m", "1h", "4h", "24h")
PATH_OFFSETS = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "24h": 1440}
TOLERANCE = 1e-9
SAMPLE_SEED = 18022
# Body-only mentions need semantic corroboration. Scores at or below the
# known metadata-only Coinbase range (0.02-0.03) are excluded, while title
# evidence remains sufficient on its own.
MIN_BODY_ASSET_RELEVANCE = 0.05


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON list, got {type(parsed).__name__}")
    return [str(item) for item in parsed]


def build_source_mapping(inventory: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for row in inventory[["canonical_event_id", "asset", "source_mappings"]].itertuples(index=False):
        for mapping in _json_list(row.source_mappings):
            rows.append({"mapping": mapping, "event_id": row.canonical_event_id, "asset": row.asset})
    mapping = pd.DataFrame(rows).drop_duplicates()
    conflicts = mapping.groupby(["mapping", "asset"]).event_id.nunique().gt(1)
    if conflicts.any():
        raise RuntimeError("A source member maps to multiple canonical events for the same asset")
    return mapping


def _asset_scores(group: pd.DataFrame) -> pd.Series:
    return group.groupby("asset", sort=True).sem_asset_relevance.max().dropna()


def _classified_assets(group: pd.DataFrame, title: str, body: str) -> list[str]:
    """Use direct title evidence or corroborated body evidence for each asset."""

    title_assets, _title_relevance, _title_hits = detect_crypto_relevance(title)
    body_assets, _body_relevance, _body_hits = detect_crypto_relevance(body)
    scores = _asset_scores(group)
    body_assets = [
        asset
        for asset in body_assets
        if float(scores.get(asset, 0.0)) >= MIN_BODY_ASSET_RELEVANCE
    ]
    evidenced = set(title_assets) | set(body_assets)
    return [asset for asset in ASSETS if asset in evidenced]


def _primary_asset(group: pd.DataFrame, assets: list[str]) -> str | None:
    if len(assets) == 1:
        return assets[0]
    scores = _asset_scores(group[group.asset.isin(assets)])
    if scores.empty:
        return None
    winners = scores[scores.eq(scores.max())].index.tolist()
    return str(winners[0]) if len(winners) == 1 else None


def build_events(inventory: pd.DataFrame) -> pd.DataFrame:
    invariant_columns = [
        "title", "published_at", "source", "url", "canonical_url",
        "sem_event_type", "sem_content_valence", "sem_content_valence_score",
        "sem_importance", "semantic_schema_version", "semantic_prompt_version",
        "original_semantic_scale", "dataset_source",
    ]
    for column in invariant_columns:
        conflicts = inventory.groupby("canonical_event_id")[column].nunique(dropna=False).gt(1)
        if conflicts.any():
            raise RuntimeError(f"Conflicting {column} inside {int(conflicts.sum())} canonical events")

    rows: list[dict[str, Any]] = []
    for event_id, group in inventory.groupby("canonical_event_id", sort=True):
        representative = group.sort_values(["priority", "member_id", "asset"]).iloc[0]
        assets = _classified_assets(
            group,
            str(representative.title or ""),
            str(representative.body or ""),
        )
        source_url = representative.url
        if pd.isna(source_url) or not str(source_url).strip():
            source_url = representative.canonical_url
        family = str(representative.dataset_source)
        rows.append({
            "event_id": str(event_id),
            "title": representative.title,
            "published_at": pd.Timestamp(representative.published_at),
            "source": representative.source,
            "source_url": source_url,
            "primary_asset": _primary_asset(group, assets),
            "related_assets": json.dumps(assets, ensure_ascii=False, separators=(",", ":")),
            "category": representative.sem_event_type,
            "sentiment": representative.sem_content_valence,
            "sentiment_score": representative.sem_content_valence_score,
            "importance": representative.sem_importance,
            "ai_schema_version": representative.semantic_schema_version,
            "ai_prompt_version": representative.semantic_prompt_version,
            "ai_original_scale": representative.original_semantic_scale,
            "archive_dataset_source": family,
            "archive_member_id": representative.member_id,
            "reaction_methodology": (
                "next_full_minute_latency_0_open_to_open"
                if family == "A" else "next_full_minute_latency_1_open_to_open"
            ),
            "reaction_value_unit": "percent",
        })
    events = pd.DataFrame(rows).sort_values(["published_at", "event_id"]).reset_index(drop=True)
    if events.event_id.duplicated().any():
        raise RuntimeError("Duplicate event_id after canonical event collapse")
    return events


def load_path_endpoints() -> pd.DataFrame:
    dataset = pads.dataset(PATHS_DIR, format="parquet")
    offsets = [0, *PATH_OFFSETS.values()]
    table = dataset.to_table(
        columns=[
            "canonical_event_id", "asset", "event_timestamp", "entry_timestamp",
            "minute_offset", "open", "raw_open_return_percent",
        ],
        filter=pc.field("minute_offset").isin(offsets),
    )
    frame = table.to_pandas()
    frame["entry_timestamp"] = pd.to_datetime(frame.entry_timestamp, utc=True)
    frame["event_timestamp"] = pd.to_datetime(frame.event_timestamp, utc=True)
    if frame.duplicated(["canonical_event_id", "asset", "minute_offset"]).any():
        raise RuntimeError("Duplicate Stage 18 price-path endpoint")
    return frame


def build_a_reactions(mapping: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    early_columns = [
        "event_key", "published_at", "baseline_time",
        *[f"{asset}_return_{horizon}" for asset in ("btc", "eth") for horizon in ("1m", "5m", "15m")],
    ]
    long_columns = [
        "metadata_event_key", "metadata_published_at",
        *[f"target_{asset}_return_{horizon}" for asset in ("btc", "eth") for horizon in ("5m", "15m", "1h", "4h", "24h")],
    ]
    early = pd.read_parquet(STAGE13A_PATH, columns=early_columns)
    long = pd.read_parquet(STAGE11_PATH, columns=long_columns)
    merged = early.merge(
        long, left_on="event_key", right_on="metadata_event_key", validate="one_to_one"
    )
    if not pd.to_datetime(merged.published_at, utc=True).equals(
        pd.to_datetime(merged.metadata_published_at, utc=True)
    ):
        raise RuntimeError("Stage 13A and Stage 11 publication timestamps differ")

    a_map = mapping[mapping.mapping.str.startswith("A:")][["mapping", "event_id"]].drop_duplicates()
    if a_map.groupby("mapping").event_id.nunique().gt(1).any():
        raise RuntimeError("Ambiguous dataset A mapping")
    merged["mapping"] = "A:" + merged.event_key.astype(str)
    merged = merged.merge(a_map, on="mapping", how="inner", validate="one_to_one")

    rows: list[dict[str, Any]] = []
    for row in merged.itertuples(index=False):
        for asset in ("BTC", "ETH"):
            prefix = asset.lower()
            rows.append({
                "event_id": row.event_id,
                "asset": asset,
                "1m": getattr(row, f"{prefix}_return_1m"),
                "5m": getattr(row, f"{prefix}_return_5m"),
                "15m": getattr(row, f"{prefix}_return_15m"),
                "1h": getattr(row, f"target_{prefix}_return_1h"),
                "4h": getattr(row, f"target_{prefix}_return_4h"),
                "24h": getattr(row, f"target_{prefix}_return_24h"),
                "reaction_source": "stage13a_early+stage11_abnormal_returns",
                "reference_time": pd.Timestamp(row.baseline_time),
                "reference_latency_minutes": 0,
            })
    return pd.DataFrame(rows), merged, long


def build_stage18_reactions(
    events: pd.DataFrame, market: pd.DataFrame, paths: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, float]]:
    non_a = set(events.loc[events.archive_dataset_source.ne("A"), "event_id"])
    selected_paths = paths[paths.canonical_event_id.isin(non_a)].copy()
    path_values = selected_paths.pivot(
        index=["canonical_event_id", "asset", "entry_timestamp"],
        columns="minute_offset", values="raw_open_return_percent",
    ).reset_index()
    path_values = path_values.rename(columns={offset: horizon for horizon, offset in PATH_OFFSETS.items()})

    market_columns = {
        "raw_return_5m": "5m",
        "raw_return_1h": "1h",
        "raw_return_4h": "4h",
        "raw_return_24h": "24h",
    }
    market_part = market[
        ["canonical_event_id", "asset", "entry_timestamp", "fully_covered", *market_columns]
    ].rename(columns=market_columns)
    market_part = market_part[market_part.canonical_event_id.isin(non_a)]
    combined = path_values.merge(
        market_part,
        on=["canonical_event_id", "asset", "entry_timestamp"],
        how="outer",
        suffixes=("_path", "_market"),
        validate="one_to_one",
    )

    conflict_max: dict[str, float] = {}
    for horizon in ("5m", "1h", "4h", "24h"):
        path_col, market_col = f"{horizon}_path", f"{horizon}_market"
        both = combined[path_col].notna() & combined[market_col].notna()
        difference = (combined.loc[both, path_col] - combined.loc[both, market_col]).abs()
        conflict_max[horizon] = float(difference.max()) if len(difference) else math.nan
        if len(difference) and difference.gt(TOLERANCE).any():
            raise RuntimeError(f"Stage 18 summary/path conflict for {horizon}")
        combined[horizon] = combined[market_col].combine_first(combined[path_col])
    for horizon in ("1m", "15m"):
        if horizon not in combined:
            combined[horizon] = np.nan
    combined = combined.rename(columns={"canonical_event_id": "event_id"})
    combined["reaction_source"] = "stage18b_canonical_market+stage18_price_paths"
    combined["reference_time"] = combined.entry_timestamp
    combined["reference_latency_minutes"] = 1
    return combined[
        ["event_id", "asset", *HORIZONS, "reaction_source", "reference_time", "reference_latency_minutes"]
    ], conflict_max


def apply_stage16_fallback(
    reactions: pd.DataFrame, mapping: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    stage16 = pd.read_parquet(STAGE16_PATH)
    stage16 = stage16[stage16.latency_minutes.eq(1)].copy()
    stage16["mapping"] = "B:" + stage16.event_id.astype(str)
    stage16["asset"] = stage16.symbol.str.replace("USDT", "", regex=False)
    b_map = mapping[mapping.mapping.str.startswith("B:")]
    mapped = stage16.merge(b_map, on=["mapping", "asset"], how="left", suffixes=("_source", ""))
    usable = mapped[mapped.event_id.notna()].copy()
    fallback_rows = pd.DataFrame({
        "event_id": usable.event_id,
        "asset": usable.asset,
        "1m": usable.return_1m,
        "5m": usable.return_5m,
        "15m": np.nan,
        "1h": usable.return_1h,
        "4h": np.nan,
        "24h": np.nan,
        "reaction_source": "stage16_market_reactions_latency_1_fallback",
        "reference_time": pd.to_datetime(usable.baseline_time, utc=True),
        "reference_latency_minutes": 1,
    })

    result = reactions.set_index(["event_id", "asset"]).copy()
    filled_cells = 0
    new_rows = 0
    for row in fallback_rows.to_dict("records"):
        key = (row["event_id"], row["asset"])
        if key not in result.index:
            result.loc[key, :] = [
                row[horizon] for horizon in HORIZONS
            ] + [row["reaction_source"], row["reference_time"], row["reference_latency_minutes"]]
            new_rows += 1
            filled_cells += sum(pd.notna(row[horizon]) for horizon in HORIZONS)
            continue
        previous_nonnull = sum(pd.notna(result.loc[key, horizon]) for horizon in HORIZONS)
        row_filled = 0
        for horizon in ("1m", "5m", "1h"):
            if pd.isna(result.loc[key, horizon]) and pd.notna(row[horizon]):
                result.loc[key, horizon] = row[horizon]
                filled_cells += 1
                row_filled += 1
        if row_filled:
            if previous_nonnull:
                result.loc[key, "reaction_source"] = (
                    str(result.loc[key, "reaction_source"])
                    + "+stage16_market_reactions_latency_1_fallback"
                )
            else:
                result.loc[key, "reaction_source"] = "stage16_market_reactions_latency_1_fallback"
            result.loc[key, "reference_time"] = row["reference_time"]
            result.loc[key, "reference_latency_minutes"] = 1
    result = result.reset_index()
    stats = {
        "source_rows_latency_1": len(stage16),
        "mapped_rows": len(usable),
        "unmapped_rows": int(mapped.event_id.isna().sum()),
        "new_reaction_rows": new_rows,
        "filled_cells": int(filled_cells),
    }
    return result, stats, usable


def build_wide(events: pd.DataFrame, reactions: pd.DataFrame) -> pd.DataFrame:
    if reactions.duplicated(["event_id", "asset"]).any():
        raise RuntimeError("Duplicate event/asset reaction rows")
    result = events.copy()
    for asset in ASSETS:
        prefix = asset.lower()
        part = reactions[reactions.asset.eq(asset)][
            ["event_id", *HORIZONS, "reaction_source", "reference_time", "reference_latency_minutes"]
        ].rename(columns={
            **{horizon: f"{prefix}_{horizon}" for horizon in HORIZONS},
            "reaction_source": f"{prefix}_reaction_source",
            "reference_time": f"{prefix}_reference_time",
            "reference_latency_minutes": f"{prefix}_reference_latency_minutes",
        })
        result = result.merge(part, on="event_id", how="left", validate="one_to_one")
    return result


def normalized_title_audit(events: pd.DataFrame) -> dict[str, Any]:
    titles = events.title.fillna("").astype(str)
    normalized = titles.str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()
    exact_mask = normalized.ne("") & normalized.duplicated(keep=False)
    exact_groups = int(normalized[exact_mask].nunique())

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2)
    matrix = vectorizer.fit_transform(titles)
    neighbors = NearestNeighbors(n_neighbors=2, metric="cosine", algorithm="brute").fit(matrix)
    distances, indices = neighbors.kneighbors(matrix)
    similarities = 1.0 - distances[:, 1]
    near_pairs: set[tuple[str, str]] = set()
    examples: list[dict[str, Any]] = []
    for index, similarity in enumerate(similarities):
        other = int(indices[index, 1])
        if similarity < 0.92 or normalized.iloc[index] == normalized.iloc[other]:
            continue
        pair = tuple(sorted((str(events.iloc[index].event_id), str(events.iloc[other].event_id))))
        if pair in near_pairs:
            continue
        near_pairs.add(pair)
        if len(examples) < 10:
            examples.append({
                "left_event_id": pair[0], "right_event_id": pair[1],
                "similarity": float(similarity),
            })
    return {
        "exact_normalized_duplicate_events": int(exact_mask.sum()),
        "exact_normalized_duplicate_groups": exact_groups,
        "near_duplicate_pairs_similarity_gte_0_92": len(near_pairs),
        "near_duplicate_examples": examples,
    }


def coverage_table(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for asset in ASSETS:
        prefix = asset.lower()
        row: dict[str, Any] = {"asset": asset}
        for horizon in HORIZONS:
            count = int(events[f"{prefix}_{horizon}"].notna().sum())
            row[horizon] = count
            row[f"{horizon}_pct"] = count / len(events) * 100
        row["full_6"] = int(events[[f"{prefix}_{h}" for h in HORIZONS]].notna().all(axis=1).sum())
        row["full_6_pct"] = row["full_6"] / len(events) * 100
        rows.append(row)
    return pd.DataFrame(rows)


def period_coverage(events: pd.DataFrame) -> pd.DataFrame:
    period = np.where(events.published_at.dt.year.le(2022), "2017-2022", "2023-2026")
    rows = []
    for label in ("2017-2022", "2023-2026"):
        part = events[period == label]
        for asset in ASSETS:
            prefix = asset.lower()
            row: dict[str, Any] = {"period": label, "asset": asset, "events": len(part)}
            for horizon in HORIZONS:
                row[horizon] = int(part[f"{prefix}_{horizon}"].notna().sum())
            row["full_6"] = int(part[[f"{prefix}_{h}" for h in HORIZONS]].notna().all(axis=1).sum())
            rows.append(row)
    return pd.DataFrame(rows)


def conflict_audit(
    a_merged: pd.DataFrame,
    market_conflicts: dict[str, float],
    stage16_mapped: pd.DataFrame,
    paths: pd.DataFrame,
    mapping: pd.DataFrame,
) -> dict[str, Any]:
    result: dict[str, Any] = {"stage18_market_vs_paths_max_abs_difference": market_conflicts}
    overlap: dict[str, float] = {}
    for asset in ("btc", "eth"):
        for horizon in ("5m", "15m"):
            difference = (
                a_merged[f"{asset}_return_{horizon}"]
                - a_merged[f"target_{asset}_return_{horizon}"]
            ).abs()
            overlap[f"{asset}_{horizon}"] = float(difference.max())
    result["stage13a_vs_stage11_max_abs_difference"] = overlap

    path_lookup = paths[paths.minute_offset.isin([1, 5, 60])]
    comparison = stage16_mapped.merge(
        path_lookup,
        left_on=["event_id", "asset"],
        right_on=["canonical_event_id", "asset"],
        how="inner",
    )
    s16_overlap: dict[str, Any] = {}
    for offset, column in ((1, "return_1m"), (5, "return_5m"), (60, "return_1h")):
        part = comparison[comparison.minute_offset.eq(offset)]
        difference = (part[column] - part.raw_open_return_percent).abs()
        s16_overlap[str(offset)] = {
            "rows": len(part),
            "max_abs_difference": float(difference.max()) if len(difference) else None,
        }
    result["stage16_latency1_vs_stage18_paths"] = s16_overlap

    a_map = mapping[mapping.mapping.str.startswith("A:")][["mapping", "event_id"]].drop_duplicates()
    a = a_merged.assign(mapping="A:" + a_merged.event_key.astype(str)).merge(a_map, on="mapping")
    a_paths = paths[(paths.asset.eq("ETH")) & paths.minute_offset.isin([1, 5, 15])]
    latency_difference = a.merge(a_paths, left_on="event_id_y", right_on="canonical_event_id")
    latency_stats: dict[str, Any] = {}
    for offset, column in ((1, "eth_return_1m"), (5, "eth_return_5m"), (15, "eth_return_15m")):
        part = latency_difference[latency_difference.minute_offset.eq(offset)]
        difference = (part[column] - part.raw_open_return_percent).abs()
        latency_stats[str(offset)] = {
            "rows": len(part),
            "median_abs_difference": float(difference.median()),
            "max_abs_difference": float(difference.max()),
        }
    result["dataset_a_latency0_vs_stage18_latency1"] = latency_stats
    return result


def validate_sample(
    output: pd.DataFrame,
    reactions: pd.DataFrame,
    paths: pd.DataFrame,
) -> list[dict[str, Any]]:
    rng = np.random.default_rng(SAMPLE_SEED)
    a_ids = output.loc[output.archive_dataset_source.eq("A"), "event_id"].to_numpy()
    other_ids = output.loc[
        output.archive_dataset_source.ne("A")
        & output[[f"{a.lower()}_{h}" for a in ASSETS for h in HORIZONS]].notna().any(axis=1),
        "event_id",
    ].to_numpy()
    sample_ids = [*rng.choice(a_ids, size=min(10, len(a_ids)), replace=False),
                  *rng.choice(other_ids, size=min(10, len(other_ids)), replace=False)]
    expected = reactions.set_index(["event_id", "asset"])
    path_groups = paths.set_index(["canonical_event_id", "asset", "minute_offset"])
    records: list[dict[str, Any]] = []
    for event_id in sample_ids:
        row = output.loc[output.event_id.eq(event_id)].iloc[0]
        compared = 0
        max_difference = 0.0
        formula_checks = 0
        for asset in ASSETS:
            key = (event_id, asset)
            if key not in expected.index:
                continue
            source_row = expected.loc[key]
            for horizon in HORIZONS:
                actual = row[f"{asset.lower()}_{horizon}"]
                source_value = source_row[horizon]
                if pd.isna(actual) and pd.isna(source_value):
                    continue
                difference = abs(float(actual) - float(source_value))
                max_difference = max(max_difference, difference)
                compared += 1
                if row.archive_dataset_source != "A":
                    base_key = (event_id, asset, 0)
                    endpoint_key = (event_id, asset, PATH_OFFSETS[horizon])
                    if base_key in path_groups.index and endpoint_key in path_groups.index:
                        base = float(path_groups.loc[base_key, "open"])
                        endpoint = float(path_groups.loc[endpoint_key, "open"])
                        formula = (endpoint / base - 1.0) * 100.0
                        max_difference = max(max_difference, abs(float(actual) - formula))
                        formula_checks += 1
        records.append({
            "event_id": str(event_id),
            "archive_family": row.archive_dataset_source,
            "compared_cells": compared,
            "price_formula_checks": formula_checks,
            "max_abs_difference": max_difference,
            "status": "PASS" if max_difference <= TOLERANCE else "FAIL",
        })
    if len(records) < 20 or any(item["status"] != "PASS" for item in records):
        raise RuntimeError("Twenty-event source validation failed")
    return records


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def render_report(
    events: pd.DataFrame,
    coverage: pd.DataFrame,
    periods: pd.DataFrame,
    title_audit: dict[str, Any],
    conflict: dict[str, Any],
    fallback: dict[str, Any],
    sample: list[dict[str, Any]],
) -> str:
    reaction_columns = [f"{asset.lower()}_{horizon}" for asset in ASSETS for horizon in HORIZONS]
    all_three = int(events[reaction_columns].notna().all(axis=1).sum())
    any_full = pd.concat([
        events[[f"{asset.lower()}_{h}" for h in HORIZONS]].notna().all(axis=1).rename(asset)
        for asset in ASSETS
    ], axis=1).any(axis=1)
    primary_full = 0
    for row in events.itertuples(index=False):
        if row.primary_asset in ASSETS:
            primary_full += all(pd.notna(getattr(row, f"{row.primary_asset.lower()}_{h}")) for h in HORIZONS)

    coverage_rows = []
    for _, row in coverage.iterrows():
        coverage_rows.append([
            row["asset"],
            *[f"{int(row[h]):,} ({row[h + '_pct']:.1f}%)" for h in HORIZONS],
            f"{int(row['full_6']):,} ({row['full_6_pct']:.1f}%)",
        ])
    period_rows = [[row["period"], row["asset"], f"{int(row['events']):,}", *[f"{int(row[h]):,}" for h in HORIZONS], f"{int(row['full_6']):,}"] for _, row in periods.iterrows()]
    sample_rows = [[item["event_id"], item["archive_family"], item["compared_cells"], item["price_formula_checks"], f"{item['max_abs_difference']:.3g}", item["status"]] for item in sample]

    missing_by_column = {column: int(events[column].isna().sum()) for column in reaction_columns}
    values = events[reaction_columns].to_numpy(dtype=float)
    finite_values = values[np.isfinite(values)]
    infinite_count = int(np.isinf(values).sum())
    impossible_count = int((finite_values <= -100.0).sum())
    duplicate_url_mask = events.source_url.notna() & events.source_url.duplicated(keep=False)
    reference_counts = {
        asset: events[f"{asset.lower()}_reaction_source"].fillna("<NULL>").astype(str).value_counts().to_dict()
        for asset in ASSETS
    }

    columns = "\n".join(f"- `{column}`" for column in events.columns)
    missing_title_mask = events.title.isna() | events.title.fillna("").str.strip().eq("")
    missing_url_mask = events.source_url.isna() | events.source_url.fillna("").str.strip().eq("")
    return f"""# Website MVP dataset report

Generated from immutable local artifacts by `scripts/processing/build_website_dataset.py`.

## 1. Event count and identity

- Total rows: **{len(events):,}**.
- Unique `event_id`: **{events.event_id.nunique():,}**.
- Duplicate `event_id`: **{int(events.event_id.duplicated().sum()):,}**.
- Publication range: **{events.published_at.min().isoformat()}** to **{events.published_at.max().isoformat()}**.
- Missing titles: **{int(missing_title_mask.sum()):,}**.
- Missing source URLs: **{int(missing_url_mask.sum()):,}**.
- Ambiguous `primary_asset` left NULL: **{int(events.primary_asset.isna().sum()):,}**. `related_assets` remains authoritative.
- Full article `body` is deliberately absent; it remains only in the master archive.

## 2. Final columns

{columns}

`related_assets` is a JSON array string so Parquet and CSV carry the same import-safe representation. Reaction values are percentage points; `0.5` means `+0.5%`.

## 3. Reaction sources and priority rules

1. **Dataset A (6,851 canonical events):** Stage 13A supplies BTC/ETH 1m, 5m and 15m; Stage 11 supplies BTC/ETH 1h, 4h and 24h. Both use the same baseline and open-to-open percentage-return formula. Their overlapping 5m/15m values match exactly.
2. **Dataset B/C:** Stage 18b canonical market supplies 5m, 1h, 4h and 24h; Stage 18 price paths supply 1m and 15m. Values present in both Stage 18 sources match exactly.
3. **Stage 16 fallback:** only `latency_minutes=1` rows are eligible, and only for 1m/5m/1h missing cells because that latency matches Stage 18. Fallback result: `{json.dumps(fallback, sort_keys=True)}`.
4. A lower-priority value never overwrites a non-NULL higher-priority value. Missing values remain NULL; no zero filling or interpolation is used.

Per-asset source counts: `{json.dumps(reference_counts, sort_keys=True, default=str)}`.

## 4. Reference-price methodology

- Dataset A: `reference_time = floor(published_at to minute) + 1 minute`; reference price is the 1m candle **open** at that time. Horizon return is `(open(reference_time + horizon) / reference_open - 1) × 100`. This is latency 0 relative to the next-full-minute baseline.
- Dataset B/C: `reference_time = floor(published_at to minute) + 2 minutes`; equivalently next full minute plus one latency minute. The same open-to-open percentage formula is used.
- Stage 16 `latency_minutes=1` uses the same B/C reference definition and was verified against Stage 18 paths.
- Dataset A was not silently shifted to Stage 18 latency 1: the required BTC endpoint candles are not locally preserved. The chosen methodology is explicit in `reaction_methodology`, per-asset source, reference-time and latency columns.

Conflict audit: `{json.dumps(conflict, sort_keys=True, default=str)}`.

## 5. Overall coverage

{markdown_table(['Asset', *HORIZONS, 'full 6'], coverage_rows)}

- Events with a full six-horizon set for at least one asset: **{int(any_full.sum()):,}**.
- Events with a full set for their unambiguous primary asset: **{primary_full:,}**.
- Events with all 18 BTC/ETH/SOL reaction fields: **{all_three:,}**.

## 6. Coverage by period

{markdown_table(['Period', 'Asset', 'Events', *HORIZONS, 'full 6'], period_rows)}

For 2023–2026, dataset A BTC/ETH values survive only as trusted derived Stage 11/13A outputs; the complete local raw candle archive is absent. Stage 18 paths permit direct OHLC verification for related-asset B/C values and for A/ETH latency-1 values, but the MVP deliberately retains the internally consistent latency-0 A family.

## 7. Quality checks

- NULL counts per reaction column: `{json.dumps(missing_by_column, sort_keys=True)}`.
- Missing category / sentiment / importance: **{int(events.category.isna().sum()):,} / {int(events.sentiment.isna().sum()):,} / {int(events.importance.isna().sum()):,}**.
- Infinite reaction values: **{infinite_count}**.
- Returns at or below -100%: **{impossible_count}**.
- Events participating in duplicate `source_url` values: **{int(duplicate_url_mask.sum())}** across **{int(events.loc[duplicate_url_mask, 'source_url'].nunique())}** URLs.
- Exact normalized-title duplicate events: **{title_audit['exact_normalized_duplicate_events']}** in **{title_audit['exact_normalized_duplicate_groups']}** groups.
- Near-duplicate title pairs with char-ngram cosine similarity ≥ 0.92: **{title_audit['near_duplicate_pairs_similarity_gte_0_92']}**.
- Near-duplicate examples: `{json.dumps(title_audit['near_duplicate_examples'], ensure_ascii=False)}`.

## 8. Deterministic 20-event validation sample

Seed: `{SAMPLE_SEED}`. Ten events were sampled from dataset A and ten from B/C. Dataset A output cells were compared with Stage 13A/Stage 11 source values. B/C values were additionally recalculated from path baseline/endpoint opens.

{markdown_table(['event_id', 'family', 'cells', 'formula checks', 'max abs diff', 'status'], sample_rows)}

## 9. Detected problems

- The archive has two valid reference families: latency 0 for A and latency 1 for B/C. They are disclosed, not blended within an event family.
- SOL coverage is sparse and correctly NULL before listing/when no trustworthy related-asset path exists.
- Cross-asset BTC/ETH/SOL reactions are unavailable for many B/C events; only preserved related-asset paths are used.
- `primary_asset` is NULL when multiple assets tie for the highest semantic relevance; `related_assets` preserves all associations.
- Exact and near-duplicate URLs/titles need editorial review before public search indexing; they were not dropped automatically.
- The latest event (`2026-07-01`) lacks a complete Stage 18 24-hour path. Stage 16 latency 1 safely fills only 1m/5m/1h; 15m/4h/24h remain NULL because that source does not provide compatible values for those horizons.

## 10. Recommendations before PostgreSQL/Supabase import

1. Keep `event_id` as the immutable natural identifier and enforce a unique constraint.
2. Parse `related_assets` into an `event_assets` join table during normalized import.
3. Preserve per-asset `reaction_source`, `reference_time` and `reference_latency_minutes`; do not hide the two methodologies.
4. Review ambiguous primary assets, duplicate URLs/titles, and missing AI values without destructive deduplication.
5. If a uniform reference definition and complete three-asset coverage are required, first recover/reacquire the full 1m BTC/ETH/SOL candle archive and rebuild every event under one versioned methodology.
6. Retain NULLs as SQL NULL and record a reaction-calculation version during import.
"""


def main() -> int:
    inventory = pd.read_parquet(INVENTORY_PATH)
    inventory["published_at"] = pd.to_datetime(inventory.published_at, utc=True)
    events = build_events(inventory)
    mapping = build_source_mapping(inventory)
    paths = load_path_endpoints()
    market = pd.read_parquet(MARKET_PATH)
    market["entry_timestamp"] = pd.to_datetime(market.entry_timestamp, utc=True)

    a_reactions, a_merged, _ = build_a_reactions(mapping)
    stage18_reactions, market_conflicts = build_stage18_reactions(events, market, paths)
    reactions = pd.concat([a_reactions, stage18_reactions], ignore_index=True)
    reactions, fallback_stats, stage16_mapped = apply_stage16_fallback(reactions, mapping)

    output = build_wide(events, reactions)
    for asset in ASSETS:
        column = f"{asset.lower()}_reference_latency_minutes"
        output[column] = pd.array(output[column], dtype="Int64")
    reaction_columns = [f"{asset.lower()}_{horizon}" for asset in ASSETS for horizon in HORIZONS]
    numeric = output[reaction_columns].to_numpy(dtype=float)
    if np.isinf(numeric).any():
        raise RuntimeError("Infinite reaction value detected")
    finite = numeric[np.isfinite(numeric)]
    if (finite <= -100.0).any():
        raise RuntimeError("Impossible return at or below -100% detected")
    if "body" in output.columns:
        raise RuntimeError("Commercial MVP dataset must not contain body")

    coverage = coverage_table(output)
    periods = period_coverage(output)
    titles = normalized_title_audit(output)
    conflicts = conflict_audit(a_merged, market_conflicts, stage16_mapped, paths, mapping)
    sample = validate_sample(output, reactions, paths)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output.to_parquet(PARQUET_OUTPUT, index=False)
    output.to_csv(CSV_OUTPUT, index=False, encoding="utf-8", na_rep="")
    REPORT_OUTPUT.write_text(
        render_report(output, coverage, periods, titles, conflicts, fallback_stats, sample),
        encoding="utf-8",
    )
    print(json.dumps({
        "events": len(output),
        "unique_event_id": int(output.event_id.nunique()),
        "parquet": str(PARQUET_OUTPUT.relative_to(ROOT)),
        "csv": str(CSV_OUTPUT.relative_to(ROOT)),
        "report": str(REPORT_OUTPUT.relative_to(ROOT)),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
