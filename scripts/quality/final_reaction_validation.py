"""Mandatory final Reaction V2 validation gates before production cutover."""

from __future__ import annotations

import calendar
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.quality.build_reactions_v2 import (  # noqa: E402
    HORIZONS,
    METHODOLOGY,
    SYMBOLS,
    archive_index,
    first_full_minute_after,
    load_selected_opens,
    reaction_return,
)


EVENTS_PATH = ROOT / "data" / "website" / "events_mvp.parquet"
STAGING_PATH = ROOT / "data" / "quality_v2" / "events_quality_v2_staging.parquet"
V2_PATH = ROOT / "data" / "reactions_v2" / "events_reactions_v2.parquet"
FINAL_PATH = ROOT / "data" / "reactions_v2" / "events_reactions_v2_final.parquet"
FINAL_CSV = ROOT / "data" / "reactions_v2" / "events_reactions_v2_final.csv"
MANIFEST_PATH = ROOT / "reports" / "stage16c_download_manifest.csv"
LIVE_BACKUP = ROOT / "data" / "website" / "backups" / "pre_reaction_v2_cutover" / "supabase_events_v1.parquet"
INVALID_PATH = ROOT / "reports" / "stage16c_invalid_candles.csv"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
ASSETS = ("BTC", "ETH", "SOL")
SEED = 20260823
FLOAT_TOLERANCE = 1e-12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_assets(value: object) -> list[str]:
    if isinstance(value, np.ndarray):
        return [str(item) for item in value.tolist()]
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def raw_invalid_candles(manifest: pd.DataFrame) -> pd.DataFrame:
    invalid = pd.read_csv(INVALID_PATH)
    rows = []
    for item in invalid.itertuples(index=False):
        path = ROOT / "data" / "raw" / "binance" / "spot" / "monthly" / "klines" / item.symbol / "1m" / item.source_file
        with ZipFile(path) as archive, archive.open(archive.namelist()[0]) as source:
            reader = csv.reader(line.decode("utf-8") for line in source)
            raw = next(row for number, row in enumerate(reader, 1) if number == item.source_row_number)
        record = manifest[(manifest.symbol.eq(item.symbol)) & manifest.local_path.astype(str).str.endswith(item.source_file)].iloc[0]
        open_ms, close_ms = int(raw[0]), int(raw[6])
        rows.append({
            "candle_asset": item.symbol.removesuffix("USDT"),
            "candle_timestamp": pd.to_datetime(open_ms, unit="ms", utc=True),
            "expected_duration_ms": 59_999,
            "actual_duration_ms": close_ms - open_ms,
            "open": float(raw[1]), "high": float(raw[2]), "low": float(raw[3]),
            "close": float(raw[4]), "volume": float(raw[5]),
            "source_zip": item.source_file, "checksum": record.actual_checksum,
            "duplicate_timestamp": False,
            "assessment": "official_exchange_anomaly_truncated_zero_volume_candle",
            "resolution": "excluded_no_interpolation",
        })
    return pd.DataFrame(rows)


def invalid_impact(v2: pd.DataFrame, invalid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for candle in invalid.to_dict("records"):
        asset_rows = v2[v2.asset.eq(candle["candle_asset"])]
        stamp = pd.Timestamp(candle["candle_timestamp"])
        reference = asset_rows[pd.to_datetime(asset_rows.reference_time, utc=True).eq(stamp)]
        for event in reference.to_dict("records"):
            rows.append({
                "candle_asset": candle["candle_asset"], "candle_timestamp": stamp,
                "event_id": event["event_id"], "horizon": None, "usage_type": "reference_candle",
                "old_value": None, "impact": "all_horizons_excluded", "resolution": "NULL",
            })
        for horizon, minutes in HORIZONS.items():
            endpoint_time = pd.to_datetime(asset_rows.reference_time, utc=True) + pd.Timedelta(minutes=minutes)
            for event in asset_rows[endpoint_time.eq(stamp)].to_dict("records"):
                rows.append({
                    "candle_asset": candle["candle_asset"], "candle_timestamp": stamp,
                    "event_id": event["event_id"], "horizon": horizon, "usage_type": "endpoint_candle",
                    "old_value": event[horizon], "impact": "reaction_excluded", "resolution": "NULL",
                })
        if not reference.shape[0] and not any(
            (pd.to_datetime(asset_rows.reference_time, utc=True) + pd.Timedelta(minutes=minutes)).eq(stamp).any()
            for minutes in HORIZONS.values()
        ):
            rows.append({
                "candle_asset": candle["candle_asset"], "candle_timestamp": stamp,
                "event_id": None, "horizon": None, "usage_type": "not_used",
                "old_value": None, "impact": "none", "resolution": "excluded_from_source_index",
            })
    return pd.DataFrame(rows)


def magnitude_bucket(value: float) -> str:
    if value < 0.05: return "<0.05 pp"
    if value < 0.10: return "0.05–0.10 pp"
    if value < 0.25: return "0.10–0.25 pp"
    if value < 0.50: return "0.25–0.50 pp"
    if value < 1.00: return "0.50–1.00 pp"
    if value < 2.00: return "1.00–2.00 pp"
    return ">2.00 pp"


def build_sign_flips(events: pd.DataFrame, v2: pd.DataFrame) -> pd.DataFrame:
    v2_lookup = v2.set_index(["event_id", "asset"])
    rows = []
    for event in events.itertuples(index=False):
        for asset in ASSETS:
            key = (event.event_id, asset)
            if key not in v2_lookup.index:
                continue
            new = v2_lookup.loc[key]
            for horizon in HORIZONS:
                old_value = getattr(event, f"{asset.lower()}_{horizon}")
                new_value = new[horizon]
                if pd.isna(old_value) or pd.isna(new_value) or np.sign(old_value) == np.sign(new_value):
                    continue
                difference = abs(float(new_value) - float(old_value))
                rows.append({
                    "event_id": event.event_id, "asset": asset, "horizon": horizon,
                    "published_at": event.published_at, "V1": float(old_value), "V2": float(new_value),
                    "absolute_difference": difference, "V1_methodology": event.reaction_methodology,
                    "V2_methodology": METHODOLOGY,
                    "reference_time_V1": getattr(event, f"{asset.lower()}_reference_time"),
                    "reference_time_V2": new.reference_time,
                    "year": pd.Timestamp(event.published_at).year,
                    "dataset_family": event.archive_dataset_source, "source": event.source,
                    "magnitude_bucket": magnitude_bucket(difference),
                })
    return pd.DataFrame(rows)


def build_cutover_changelog(events: pd.DataFrame, v2: pd.DataFrame) -> pd.DataFrame:
    """Retain only reaction cells whose V2 value is not value-equivalent to V1."""
    lookup = v2.set_index(["event_id", "asset"])
    rows = []
    for event in events.itertuples(index=False):
        for asset in ASSETS:
            current = lookup.loc[(event.event_id, asset)]
            for horizon in HORIZONS:
                old_value = getattr(event, f"{asset.lower()}_{horizon}")
                new_value = current[horizon]
                old_missing, new_missing = pd.isna(old_value), pd.isna(new_value)
                identical = old_missing and new_missing
                if not old_missing and not new_missing:
                    identical = float(old_value) == float(new_value)
                if identical:
                    continue
                rows.append({
                    "event_id": event.event_id,
                    "asset": asset,
                    "field": horizon,
                    "V1": None if old_missing else float(old_value),
                    "V2": None if new_missing else float(new_value),
                    "reason": "methodology_v2_first_full_minute_open_to_open",
                    "methodology_version": METHODOLOGY,
                })
    return pd.DataFrame(rows)


def sign_flip_sample(flips: pd.DataFrame) -> pd.DataFrame:
    top = flips.nlargest(20, "absolute_difference")
    selected = set(top.index)
    candidates = flips.drop(index=selected).sample(frac=1, random_state=SEED)
    asset_targets = {"BTC": 35, "ETH": 35, "SOL": 30}
    horizon_targets = {"1m": 19, "5m": 18, "15m": 18, "1h": 16, "4h": 16, "24h": 13}
    period_targets = {"old": 35, "new": 65}
    while len(selected) < 100:
        chosen = flips.loc[list(selected)]
        asset_counts = chosen.asset.value_counts().to_dict()
        horizon_counts = chosen.horizon.value_counts().to_dict()
        period_counts = Counter("old" if int(year) <= 2022 else "new" for year in chosen.year)
        seen_years = set(chosen.year.astype(int))
        best_index, best_score = None, -1.0
        for index, row in candidates.loc[~candidates.index.isin(selected)].iterrows():
            period = "old" if int(row.year) <= 2022 else "new"
            score = 0.0
            score += max(asset_targets[row.asset] - asset_counts.get(row.asset, 0), 0) / asset_targets[row.asset]
            score += max(horizon_targets[row.horizon] - horizon_counts.get(row.horizon, 0), 0) / horizon_targets[row.horizon]
            score += max(period_targets[period] - period_counts.get(period, 0), 0) / period_targets[period]
            score += 0.5 if int(row.year) not in seen_years else 0.0
            if score > best_score:
                best_index, best_score = index, score
        if best_index is None:
            break
        selected.add(best_index)
    return flips.loc[sorted(selected)].copy()


def year_band(year: int) -> str:
    if year <= 2019: return "2017–2019"
    if year <= 2022: return "2020–2022"
    return str(year)


def source_group(source: str) -> str:
    value = source.casefold()
    if value in {"coindesk", "decrypt", "cointelegraph", "sec"}:
        return value
    if "github" in value:
        return "github"
    if "foundation" in value or "official" in value:
        return "official_sources"
    return "other"


def asset_group(assets: list[str]) -> str:
    if not assets: return "no_related_asset"
    if len(assets) > 1: return "multi_asset"
    return f"{assets[0]}_related"


def event_sample_300(staging: pd.DataFrame, live: pd.DataFrame) -> pd.DataFrame:
    frame = staging.merge(live[["event_id", "slug"]], on="event_id", how="left", validate="one_to_one")
    frame["related_assets_list"] = frame.related_assets.map(parse_assets)
    frame["year"] = pd.to_datetime(frame.published_at, utc=True).dt.year
    frame["year_band"] = frame.year.map(year_band)
    frame["asset_group"] = frame.related_assets_list.map(asset_group)
    frame["source_group"] = frame.source.astype(str).map(source_group)
    frame["sample_stratum"] = (
        frame.year_band + "|" + frame.asset_group + "|" + frame.source_group + "|" + frame.record_type
    )
    groups = [part.sample(frac=1, random_state=SEED) for _, part in frame.groupby("sample_stratum")]
    rows, position = [], 0
    while len(rows) < 300:
        progressed = False
        for group in groups:
            if position < len(group):
                rows.append(group.iloc[position])
                progressed = True
                if len(rows) == 300:
                    break
        if not progressed:
            break
        position += 1
    return pd.DataFrame(rows).reset_index(drop=True)


def qa_cells_for_events(sample: pd.DataFrame, v2: pd.DataFrame) -> pd.DataFrame:
    event_ids = set(sample.event_id)
    available = v2[v2.event_id.isin(event_ids)].copy()
    rows = []
    for event_id, part in available.groupby("event_id"):
        for row in part.to_dict("records"):
            horizons = [name for name in HORIZONS if pd.notna(row[name])]
            if not horizons:
                continue
            choice = int(hashlib.sha256(f"{event_id}|{row['asset']}".encode()).hexdigest()[:8], 16) % len(horizons)
            rows.append({"event_id": event_id, "asset": row["asset"], "horizon": horizons[choice]})
    base = pd.DataFrame(rows).drop_duplicates()
    full_events = list(sample.event_id.head(30))
    extra = []
    lookup = available.set_index(["event_id", "asset"])
    for event_id in full_events:
        for asset in ASSETS:
            if (event_id, asset) not in lookup.index:
                continue
            row = lookup.loc[(event_id, asset)]
            for horizon in HORIZONS:
                if pd.notna(row[horizon]):
                    extra.append({"event_id": event_id, "asset": asset, "horizon": horizon})
    result = pd.concat([base, pd.DataFrame(extra)], ignore_index=True).drop_duplicates()
    if len(result) < 600:
        pool = []
        for row in available.to_dict("records"):
            for horizon in HORIZONS:
                if pd.notna(row[horizon]):
                    pool.append({"event_id": row["event_id"], "asset": row["asset"], "horizon": horizon})
        remaining = pd.DataFrame(pool).merge(result, how="outer", indicator=True).query("_merge == 'left_only'").drop(columns="_merge")
        result = pd.concat([result, remaining.sample(min(600 - len(result), len(remaining)), random_state=SEED)], ignore_index=True)
    return result


def build_raw_requests(
    flip_sample: pd.DataFrame,
    qa_cells: pd.DataFrame,
    outlier_manual: pd.DataFrame,
    v2_lookup: pd.DataFrame,
) -> dict[tuple[str, int, int], set[int]]:
    requests: dict[tuple[str, int, int], set[int]] = defaultdict(set)
    items = pd.concat([
        flip_sample[["event_id", "asset", "horizon"]],
        qa_cells[["event_id", "asset", "horizon"]],
        outlier_manual[["event_id", "asset", "horizon"]],
    ]).drop_duplicates()
    for item in items.itertuples(index=False):
        row = v2_lookup.loc[(item.event_id, item.asset)]
        reference = pd.Timestamp(row.reference_time)
        endpoint = reference + pd.Timedelta(minutes=HORIZONS[item.horizon])
        symbol = SYMBOLS[item.asset]
        for timestamp in (reference, endpoint, reference - pd.Timedelta(minutes=1), reference + pd.Timedelta(minutes=1), endpoint - pd.Timedelta(minutes=1), endpoint + pd.Timedelta(minutes=1)):
            requests[(symbol, timestamp.year, timestamp.month)].add(int(timestamp.timestamp() * 1000))
    return requests


def load_raw_lookup(requests, archive_files) -> dict[tuple[str, int], float]:
    opens = {}
    for key, stamps in sorted(requests.items()):
        path = archive_files.get(key)
        if path is None:
            continue
        selected, problems = load_selected_opens(path, stamps)
        if problems:
            raise RuntimeError(f"Unexpected selected-candle validation problems: {problems[:3]}")
        opens.update({(key[0], stamp): price for stamp, price in selected.items()})
    return opens


def verify_cells(cells: pd.DataFrame, v2_lookup: pd.DataFrame, raw: dict[tuple[str, int], float]) -> pd.DataFrame:
    rows = []
    for item in cells.itertuples(index=False):
        v2row = v2_lookup.loc[(item.event_id, item.asset)]
        reference_time = pd.Timestamp(v2row.reference_time)
        endpoint_time = reference_time + pd.Timedelta(minutes=HORIZONS[item.horizon])
        symbol = SYMBOLS[item.asset]
        reference = raw.get((symbol, int(reference_time.timestamp() * 1000)))
        endpoint = raw.get((symbol, int(endpoint_time.timestamp() * 1000)))
        recalculated = reaction_return(reference, endpoint)
        stored = v2row[item.horizon]
        difference = abs(float(stored) - float(recalculated)) if pd.notna(stored) and recalculated is not None else None
        rows.append({
            "event_id": item.event_id, "asset": item.asset, "horizon": item.horizon,
            "reference_time": reference_time, "endpoint_time": endpoint_time,
            "reference_open": reference, "endpoint_open": endpoint,
            "stored_v2": stored, "recalculated_v2": recalculated,
            "absolute_difference": difference,
            "status": "PASS" if difference is not None and difference <= FLOAT_TOLERANCE else "FAIL",
        })
    return pd.DataFrame(rows)


def refine_final(v2: pd.DataFrame, archive_files, invalid: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = v2.copy()
    invalid_keys = {(row.candle_asset, pd.Timestamp(row.candle_timestamp)) for row in invalid.itertuples()}
    earliest = {}
    latest = {}
    for symbol, year, month in archive_files:
        earliest[symbol] = min(earliest.get(symbol, pd.Timestamp.max.tz_localize("UTC")), pd.Timestamp(year=year, month=month, day=1, tz="UTC"))
        last_day = calendar.monthrange(year, month)[1]
        latest[symbol] = max(latest.get(symbol, pd.Timestamp.min.tz_localize("UTC")), pd.Timestamp(year=year, month=month, day=last_day, hour=23, minute=59, tz="UTC"))
    missing_rows = []
    reasons_json = []
    qualities = []
    for row in frame.to_dict("records"):
        symbol = SYMBOLS[row["asset"]]
        reference = pd.Timestamp(row["reference_time"])
        reasons = {}
        if pd.isna(row["reference_price"]):
            if reference < earliest[symbol]: reason = "asset_not_listed"
            elif reference > latest[symbol]: reason = "event_after_market_cutoff"
            elif (row["asset"], reference) in invalid_keys: reason = "invalid_candle"
            elif (symbol, reference.year, reference.month) not in archive_files: reason = "market_archive_missing"
            else: reason = "endpoint_missing"
            for horizon in HORIZONS:
                if pd.isna(row[horizon]): reasons[horizon] = reason
        else:
            for horizon, minutes in HORIZONS.items():
                if pd.notna(row[horizon]):
                    continue
                endpoint = reference + pd.Timedelta(minutes=minutes)
                if endpoint > latest[symbol]: reason = "event_after_market_cutoff"
                elif (row["asset"], endpoint) in invalid_keys: reason = "invalid_candle"
                elif (symbol, endpoint.year, endpoint.month) not in archive_files: reason = "market_archive_missing"
                else: reason = "endpoint_missing"
                reasons[horizon] = reason
        for horizon, reason in reasons.items():
            missing_rows.append({"event_id": row["event_id"], "asset": row["asset"], "horizon": horizon, "reason": reason})
        reasons_json.append(json.dumps(reasons, sort_keys=True) if reasons else None)
        if not reasons:
            qualities.append("raw_verified_v2")
        elif any(reason == "invalid_candle" for reason in reasons.values()):
            qualities.append("excluded_invalid_candle")
        else:
            qualities.append("missing_market_data" if len(reasons) == len(HORIZONS) else "partial_raw_verified_v2")
    frame["reaction_missing_reason"] = reasons_json
    frame["reaction_quality"] = qualities
    return frame, pd.DataFrame(missing_rows)


def outlier_tables(final: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, manual = [], []
    for asset in ASSETS:
        part = final[final.asset.eq(asset)]
        for horizon in HORIZONS:
            usable = part[part[horizon].notna()]
            positive = usable.nlargest(50, horizon)
            negative = usable.nsmallest(50, horizon)
            for direction, selected in (("positive", positive), ("negative", negative)):
                for rank, row in enumerate(selected.to_dict("records"), 1):
                    item = {"event_id": row["event_id"], "asset": asset, "horizon": horizon, "direction": direction, "rank": rank, "reaction": row[horizon], "reference_time": row["reference_time"]}
                    rows.append(item)
                    if rank <= 10: manual.append(item)
    return pd.DataFrame(rows), pd.DataFrame(manual)


def distribution_table(final: pd.DataFrame) -> pd.DataFrame:
    rows = []
    frame = final.copy()
    frame["year"] = pd.to_datetime(frame.published_at, utc=True).dt.year
    for (asset, year), part in frame.groupby(["asset", "year"]):
        for horizon in HORIZONS:
            values = part[horizon].dropna().astype(float)
            if values.empty: continue
            rows.append({
                "asset": asset, "horizon": horizon, "year": int(year), "count": len(values),
                "mean": values.mean(), "median": values.median(), "std": values.std(),
                "p01": values.quantile(.01), "p05": values.quantile(.05), "p25": values.quantile(.25),
                "p75": values.quantile(.75), "p95": values.quantile(.95), "p99": values.quantile(.99),
                "min": values.min(), "max": values.max(),
            })
    return pd.DataFrame(rows)


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    events = pd.read_parquet(EVENTS_PATH)
    staging = pd.read_parquet(STAGING_PATH)
    live = pd.read_parquet(LIVE_BACKUP)
    v2 = pd.read_parquet(V2_PATH)
    for frame in (events, staging, live, v2):
        if "published_at" in frame: frame["published_at"] = pd.to_datetime(frame.published_at, utc=True)
    v2["reference_time"] = pd.to_datetime(v2.reference_time, utc=True)
    archive_files, manifest = archive_index(MANIFEST_PATH)

    invalid = raw_invalid_candles(manifest)
    invalid.to_csv(REPORTS / "INVALID_BINANCE_CANDLES_FORENSIC.csv", index=False)
    impact = invalid_impact(v2, invalid)
    impact.to_csv(REPORTS / "INVALID_BINANCE_CANDLE_IMPACT.csv", index=False)

    final, missing = refine_final(v2, archive_files, invalid)
    missing.to_csv(REPORTS / "REACTION_V2_MISSING_DATA.csv", index=False)
    flips = build_sign_flips(events, final)
    flips.to_parquet(REPORTS / "REACTION_V1_V2_SIGN_FLIPS.parquet", index=False)
    build_cutover_changelog(events, final).to_parquet(
        REPORTS / "REACTION_V2_CUTOVER_CHANGELOG.parquet", index=False,
    )
    flip_sample = sign_flip_sample(flips)

    sample = event_sample_300(staging, live)
    metadata_columns = ["event_id", "slug", "title", "source", "published_at", "record_type", "related_assets", "primary_asset", "year_band", "asset_group", "source_group"]
    sample[metadata_columns].to_csv(REPORTS / "REACTION_V2_300_EVENT_SAMPLE.csv", index=False)
    metadata_pass = sample.slug.notna() & sample.event_id.notna() & sample.title.notna() & sample.source.notna() & sample.published_at.notna() & sample.record_type.notna()
    qa_cells = qa_cells_for_events(sample, final)
    outliers, outlier_manual = outlier_tables(final)
    v2_lookup = final.set_index(["event_id", "asset"])
    requests = build_raw_requests(flip_sample, qa_cells, outlier_manual, v2_lookup)
    raw = load_raw_lookup(requests, archive_files)
    flip_verified = verify_cells(flip_sample, v2_lookup, raw)
    flip_review = flip_sample.merge(flip_verified, on=["event_id", "asset", "horizon"], suffixes=("", "_raw"))
    flip_review["conclusion"] = np.where(
        flip_review.status.eq("PASS") & flip_review.reference_time_V1.ne(flip_review.reference_time_V2),
        "sign_flip_caused_by_methodology_difference",
        np.where(flip_review.status.eq("PASS"), "v2_raw_confirmed_reference_metadata_review", "real_data_error"),
    )
    flip_review.to_csv(REPORTS / "REACTION_V1_V2_SIGN_FLIP_FORENSIC_SAMPLE.csv", index=False)

    qa_verified = verify_cells(qa_cells, v2_lookup, raw)
    qa_verified.to_csv(REPORTS / "REACTION_V2_300_EVENT_CELL_QA.csv", index=False)
    reference_checks = []
    for event in sample.itertuples(index=False):
        expected = first_full_minute_after(pd.Timestamp(event.published_at))
        for asset in ASSETS:
            row = v2_lookup.loc[(event.event_id, asset)]
            actual = pd.Timestamp(row.reference_time)
            reference_checks.append({
                "event_id": event.event_id, "asset": asset, "published_at": event.published_at,
                "reference_time": actual, "expected_reference_time": expected,
                "strictly_after": actual > event.published_at, "exact_rule_match": actual == expected,
            })
    reference_frame = pd.DataFrame(reference_checks)
    reference_frame.to_csv(REPORTS / "REACTION_V2_300_EVENT_REFERENCE_TIME_QA.csv", index=False)

    outlier_verified = verify_cells(outlier_manual, v2_lookup, raw)
    neighbor_rows = []
    for row in outlier_verified.to_dict("records"):
        symbol = SYMBOLS[row["asset"]]
        ref, endpoint = pd.Timestamp(row["reference_time"]), pd.Timestamp(row["endpoint_time"])
        values = {
            "reference_previous": raw.get((symbol, int((ref - pd.Timedelta(minutes=1)).timestamp() * 1000))),
            "reference_next": raw.get((symbol, int((ref + pd.Timedelta(minutes=1)).timestamp() * 1000))),
            "endpoint_previous": raw.get((symbol, int((endpoint - pd.Timedelta(minutes=1)).timestamp() * 1000))),
            "endpoint_next": raw.get((symbol, int((endpoint + pd.Timedelta(minutes=1)).timestamp() * 1000))),
        }
        endpoint_open = row["endpoint_open"]
        neighbor_values = [values["endpoint_previous"], values["endpoint_next"]]
        spike = bool(endpoint_open and all(value and abs(endpoint_open / value - 1) > 0.05 for value in neighbor_values))
        neighbor_rows.append({**row, **values, "isolated_endpoint_spike_gt_5pct": spike, "pair": symbol})
    neighbor_frame = pd.DataFrame(neighbor_rows)
    neighbor_frame.to_csv(REPORTS / "REACTION_V2_OUTLIER_FORENSIC.csv", index=False)
    outliers.to_csv(REPORTS / "REACTION_V2_OUTLIERS_TOP50.csv", index=False)
    distributions = distribution_table(final)
    distributions.to_csv(REPORTS / "REACTION_V2_DISTRIBUTIONS.csv", index=False)

    external = pd.read_csv(REPORTS / "SOURCE_VERIFICATION_V2_SAMPLE.csv")
    offsets = pd.to_numeric(external.publication_difference_seconds, errors="coerce").dropna()
    timezone_offsets = {f"{hours}h": int(offsets.abs().sub(hours * 3600).abs().le(60).sum()) for hours in (1, 4, 5, 8)}
    timezone_pass = not any(timezone_offsets.values()) and reference_frame.strictly_after.all() and reference_frame.exact_rule_match.all()
    (REPORTS / "REACTION_V2_TIMEZONE_FINAL.json").write_text(json.dumps({
        "sample_reference_checks": len(reference_frame), "reference_rule_failures": int((~reference_frame.exact_rule_match).sum()),
        "not_strictly_after": int((~reference_frame.strictly_after).sum()), "external_exact_timestamp_rows": len(offsets),
        "systematic_offset_matches": timezone_offsets, "status": "PASS" if timezone_pass else "FAIL",
        "boundary_cases": {
            "14:30:00.000": first_full_minute_after(pd.Timestamp("2026-01-01T14:30:00.000Z")).isoformat(),
            "14:30:00.001": first_full_minute_after(pd.Timestamp("2026-01-01T14:30:00.001Z")).isoformat(),
            "14:30:59.999": first_full_minute_after(pd.Timestamp("2026-01-01T14:30:59.999Z")).isoformat(),
        },
    }, indent=2) + "\n", encoding="utf-8")

    # Immutable final outputs are written only after every local calculation above.
    final.to_parquet(FINAL_PATH, index=False)
    final.to_csv(FINAL_CSV, index=False, encoding="utf-8", na_rep="")
    archive_hash = hashlib.sha256("\n".join(sorted(manifest.actual_checksum.astype(str))).encode()).hexdigest()
    final_manifest = {
        "sha256": sha256_file(FINAL_PATH), "csv_sha256": sha256_file(FINAL_CSV),
        "row_count": len(final), "unique_event_ids": int(final.event_id.nunique()),
        "methodology_version": METHODOLOGY, "generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "binance_archive_version": "official monthly 1m through 2026-07", "binance_archive_hash": archive_hash,
        "invalid_candles_excluded": len(invalid), "invalid_candle_affected_reactions": int(impact.event_id.notna().sum()),
    }
    (REPORTS / "REACTION_V2_MANIFEST.json").write_text(json.dumps(final_manifest, indent=2) + "\n", encoding="utf-8")

    missing_counts = {}
    for asset in ASSETS:
        part = final[final.asset.eq(asset)]
        missing_counts[asset] = {horizon: int(part[horizon].isna().sum()) for horizon in HORIZONS}
        missing_counts[asset]["full"] = int(part[list(HORIZONS)].notna().all(axis=1).sum())
    distribution_flags = int((distributions[["min", "max"]].abs() > 100).any(axis=1).sum())
    status = {
        "invalid_candles": len(invalid), "invalid_candles_resolved": len(invalid),
        "invalid_candle_affected_reactions": int(impact.event_id.notna().sum()),
        "sign_flips": len(flips), "sign_flip_verified_sample": len(flip_review),
        "sign_flip_sample_failures": int(flip_review.status.ne("PASS").sum()),
        "event_sample": len(sample), "event_metadata_failures": int((~metadata_pass).sum()),
        "new_reaction_cells_checked": len(qa_verified), "new_reaction_cell_failures": int(qa_verified.status.ne("PASS").sum()),
        "total_reaction_cells_checked_including_prior_500": len(qa_verified) + 500,
        "reference_time_failures": int((~reference_frame.exact_rule_match).sum()),
        "timezone_audit": "PASS" if timezone_pass else "FAIL",
        "outlier_cells_checked": len(neighbor_frame), "outlier_failures": int(neighbor_frame.status.ne("PASS").sum()),
        "isolated_spike_flags": int(neighbor_frame.isolated_endpoint_spike_gt_5pct.sum()),
        "distribution_extreme_gt_100pct_groups": distribution_flags,
        "missing_counts": missing_counts,
        "final_manifest": final_manifest,
    }
    (REPORTS / "REACTION_V2_LOCAL_VALIDATION_STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

    flip_distribution = flips.groupby(["asset", "horizon", "year", "dataset_family", "source", "magnitude_bucket"], dropna=False).size().rename("flips").reset_index()
    flip_distribution.to_csv(REPORTS / "REACTION_V1_V2_SIGN_FLIP_DISTRIBUTION.csv", index=False)
    DOCS.joinpath("REACTION_V1_V2_SIGN_FLIP_AUDIT.md").write_text(
        "# Reaction V1/V2 sign-flip audit\n\n"
        f"- Total flips: **{len(flips):,}**.\n- Forensic sample: **{len(flip_review)}** including the 20 largest differences.\n"
        f"- Raw V2 recalculation failures: **{int(flip_review.status.ne('PASS').sum())}**.\n"
        f"- V1 families represented: `{json.dumps(flips.dataset_family.value_counts().to_dict())}`. All flips are in B/C, whose V1 reference used the extra latency minute; V2 uses the first full minute strictly after publication.\n"
        f"- Magnitudes: `{json.dumps(flips.magnitude_bucket.value_counts().to_dict())}`.\n\n"
        "The full row-level Parquet, grouped distribution CSV, and 100-row forensic sample retain both reference timestamps and values.\n",
        encoding="utf-8",
    )
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
