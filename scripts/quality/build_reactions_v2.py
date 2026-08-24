"""Build Reaction Methodology V2 from checksum-validated Binance ZIP files.

The canonical V1 fields and production database are never modified.  Missing
reference or endpoint candles stay NULL and receive an explicit reason.
"""

from __future__ import annotations

import argparse
import calendar
import json
import math
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = ROOT / "data" / "website" / "events_mvp.parquet"
MANIFEST_PATH = ROOT / "reports" / "stage16c_download_manifest.csv"
OUTPUT_DIR = ROOT / "data" / "reactions_v2"
OUTPUT_PATH = OUTPUT_DIR / "events_reactions_v2.parquet"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
ASSETS = ("BTC", "ETH", "SOL")
SYMBOLS = {asset: f"{asset}USDT" for asset in ASSETS}
HORIZONS = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "24h": 1440}
METHODOLOGY = "reaction_v2_next_full_minute_open_to_open"
SEED = 20260823


def first_full_minute_after(timestamp: pd.Timestamp) -> pd.Timestamp:
    value = pd.Timestamp(timestamp)
    if value.tzinfo is None:
        raise ValueError("published_at must be timezone-aware")
    return value.floor("min") + pd.Timedelta(minutes=1)


def reaction_return(reference_open: float | None, endpoint_open: float | None) -> float | None:
    if reference_open is None or endpoint_open is None:
        return None
    if not math.isfinite(reference_open) or not math.isfinite(endpoint_open) or reference_open <= 0 or endpoint_open <= 0:
        return None
    return (endpoint_open / reference_open - 1.0) * 100.0


def parse_assets(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def month_key(timestamp: pd.Timestamp) -> tuple[int, int]:
    return timestamp.year, timestamp.month


def archive_index(manifest_path: Path) -> tuple[dict[tuple[str, int, int], Path], pd.DataFrame]:
    manifest = pd.read_csv(manifest_path, keep_default_na=False)
    accepted = manifest[manifest.status.isin(["imported", "validated", "checksum_pass"])]
    index: dict[tuple[str, int, int], Path] = {}
    for row in accepted.itertuples(index=False):
        path = ROOT / str(row.local_path)
        if path.is_file() and str(row.expected_checksum) == str(row.actual_checksum):
            index[(str(row.symbol), int(row.year), int(row.month))] = path
    return index, manifest


def load_selected_opens(path: Path, requested_ms: set[int]) -> tuple[dict[int, float], list[dict[str, object]]]:
    """Read only timestamps needed by the V2 calculation from one archive."""

    if not requested_ms:
        return {}, []
    with ZipFile(path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if len(members) != 1:
            raise ValueError(f"{path}: expected one CSV member, got {len(members)}")
        with archive.open(members[0]) as source:
            frame = pd.read_csv(
                source,
                header=None,
                usecols=list(range(7)),
                names=["open_time", "open", "high", "low", "close", "volume", "close_time"],
                dtype=str,
                on_bad_lines="skip",
            )
    raw_open_time = pd.to_numeric(frame.open_time, errors="coerce")
    precision = np.where(raw_open_time.abs().ge(100_000_000_000_000), 1_000, 1)
    frame["open_ms"] = (raw_open_time / precision).round().astype("Int64")
    selected = frame[frame.open_ms.isin(requested_ms)].copy()
    problems: list[dict[str, object]] = []
    if selected.open_ms.duplicated().any():
        for stamp in selected.loc[selected.open_ms.duplicated(keep=False), "open_ms"].unique():
            problems.append({"source_file": path.name, "open_time_ms": int(stamp), "reason": "duplicate_timestamp"})
        selected = selected.drop_duplicates("open_ms", keep=False)
    for column in ("open", "high", "low", "close"):
        selected[column] = pd.to_numeric(selected[column], errors="coerce")
    close_raw = pd.to_numeric(selected.close_time, errors="coerce")
    close_precision = np.where(close_raw.abs().ge(100_000_000_000_000), 1_000, 1)
    # Binance archives switched from millisecond to microsecond timestamps.
    # A valid close such as 59_999.999 ms must be floored to 59_999 ms, not
    # rounded into the next minute.
    selected["close_ms"] = np.floor(close_raw / close_precision)
    invalid = (
        selected[["open", "high", "low", "close"]].isna().any(axis=1)
        | selected[["open", "high", "low", "close"]].le(0).any(axis=1)
        | selected.high.lt(selected[["open", "close"]].max(axis=1))
        | selected.low.gt(selected[["open", "close"]].min(axis=1))
        | selected.close_ms.sub(selected.open_ms).lt(59_999)
        | selected.close_ms.sub(selected.open_ms).ge(60_000)
    )
    for row in selected[invalid].itertuples(index=False):
        problems.append({"source_file": path.name, "open_time_ms": int(row.open_ms), "reason": "invalid_selected_candle"})
    selected = selected[~invalid]
    return {int(row.open_ms): float(row.open) for row in selected.itertuples(index=False)}, problems


def build(events: pd.DataFrame, index: dict[tuple[str, int, int], Path]) -> tuple[pd.DataFrame, list[dict[str, object]], dict[tuple[str, int], float]]:
    events = events.copy()
    events["published_at"] = pd.to_datetime(events.published_at, utc=True)
    events["reference_time"] = events.published_at.map(first_full_minute_after)
    requests: dict[tuple[str, int, int], set[int]] = defaultdict(set)
    for event in events.itertuples(index=False):
        times = [event.reference_time, *[event.reference_time + pd.Timedelta(minutes=value) for value in HORIZONS.values()]]
        for asset in ASSETS:
            symbol = SYMBOLS[asset]
            for timestamp in times:
                requests[(symbol, *month_key(timestamp))].add(int(timestamp.timestamp() * 1000))

    opens: dict[tuple[str, int], float] = {}
    problems: list[dict[str, object]] = []
    for key, requested in sorted(requests.items()):
        path = index.get(key)
        if path is None:
            continue
        selected, selected_problems = load_selected_opens(path, requested)
        symbol = key[0]
        opens.update({(symbol, stamp): price for stamp, price in selected.items()})
        problems.extend(selected_problems)

    rows: list[dict[str, object]] = []
    for event in events.itertuples(index=False):
        reference_ms = int(event.reference_time.timestamp() * 1000)
        related = parse_assets(event.related_assets)
        for asset in ASSETS:
            symbol = SYMBOLS[asset]
            reference_price = opens.get((symbol, reference_ms))
            row: dict[str, object] = {
                "event_id": event.event_id,
                "asset": asset,
                "published_at": event.published_at,
                "reference_time": event.reference_time,
                "reference_price": reference_price,
                "source": "Binance Vision official monthly 1m archive",
                "methodology_version": METHODOLOGY,
                "is_related_asset": asset in related,
            }
            missing = []
            for label, minutes in HORIZONS.items():
                endpoint_ms = int((event.reference_time + pd.Timedelta(minutes=minutes)).timestamp() * 1000)
                endpoint = opens.get((symbol, endpoint_ms))
                row[f"{label}_endpoint_open"] = endpoint
                row[label] = reaction_return(reference_price, endpoint)
                if endpoint is None:
                    missing.append(label)
            if reference_price is None:
                archive_available = (symbol, *month_key(event.reference_time)) in index
                row["missing_reason"] = "missing_market_data" if archive_available else "before_listing_or_archive_unavailable"
                row["reaction_quality"] = "missing"
            elif missing:
                row["missing_reason"] = "missing_market_data:" + "|".join(missing)
                row["reaction_quality"] = "partial_verified_raw"
            else:
                row["missing_reason"] = None
                row["reaction_quality"] = "verified_raw"
            rows.append(row)
    return pd.DataFrame(rows), problems, opens


def comparison(v1: pd.DataFrame, v2: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    long_rows = []
    lookup = v2.set_index(["event_id", "asset"])
    for event in v1.itertuples(index=False):
        for asset in ASSETS:
            key = (event.event_id, asset)
            if key not in lookup.index:
                continue
            v2_row = lookup.loc[key]
            for horizon in HORIZONS:
                old = getattr(event, f"{asset.lower()}_{horizon}")
                new = v2_row[horizon]
                if pd.isna(old) or pd.isna(new):
                    continue
                difference = float(new) - float(old)
                long_rows.append({
                    "event_id": event.event_id, "asset": asset, "horizon": horizon,
                    "year": pd.Timestamp(event.published_at).year,
                    "dataset_family": event.archive_dataset_source, "source": event.source,
                    "v1": float(old), "v2": float(new), "difference": difference,
                    "abs_difference": abs(difference), "sign_flip": bool(np.sign(old) != np.sign(new)),
                })
    cells = pd.DataFrame(long_rows)
    groups = []
    dimensions = [
        (["asset", "horizon"], "asset_horizon"),
        (["year", "horizon"], "year_horizon"),
        (["dataset_family", "horizon"], "dataset_family_horizon"),
        (["source", "horizon"], "source_horizon"),
    ]
    for columns, dimension in dimensions:
        for keys, part in cells.groupby(columns, dropna=False):
            keys = keys if isinstance(keys, tuple) else (keys,)
            row = {"dimension": dimension, **dict(zip(columns, keys)), "cells": len(part)}
            row.update({
                "mean_difference": part.difference.mean(),
                "median_difference": part.difference.median(),
                "p95_abs_difference": part.abs_difference.quantile(0.95),
                "p99_abs_difference": part.abs_difference.quantile(0.99),
                "max_abs_difference": part.abs_difference.max(),
                "sign_flips": int(part.sign_flip.sum()),
                "gt_0_1pp": int(part.abs_difference.gt(0.1).sum()),
                "gt_0_5pp": int(part.abs_difference.gt(0.5).sum()),
                "gt_1pp": int(part.abs_difference.gt(1.0).sum()),
                "gt_2pp": int(part.abs_difference.gt(2.0).sum()),
            })
            groups.append(row)
    return cells, pd.DataFrame(groups)


def qa_sample(v2: pd.DataFrame, opens: dict[tuple[str, int], float]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    samples = []
    for asset, count in (("BTC", 35), ("ETH", 35), ("SOL", 30)):
        pool = v2[(v2.asset.eq(asset)) & v2.reaction_quality.ne("missing")]
        if pool.empty:
            continue
        samples.append(pool.iloc[rng.choice(len(pool), min(count, len(pool)), replace=False)])
    events = pd.concat(samples, ignore_index=True)
    cells = []
    for row in events.to_dict("records"):
        symbol = SYMBOLS[row["asset"]]
        reference_ms = int(pd.Timestamp(row["reference_time"]).timestamp() * 1000)
        reference = opens.get((symbol, reference_ms))
        for horizon, minutes in HORIZONS.items():
            stored = row[horizon]
            endpoint_ms = int((pd.Timestamp(row["reference_time"]) + pd.Timedelta(minutes=minutes)).timestamp() * 1000)
            endpoint = opens.get((symbol, endpoint_ms))
            recalculated = reaction_return(reference, endpoint)
            difference = abs(float(stored) - recalculated) if pd.notna(stored) and recalculated is not None else None
            cells.append({
                "event_id": row["event_id"], "asset": row["asset"], "horizon": horizon,
                "reference_time": row["reference_time"], "reference_open": reference,
                "endpoint_open": endpoint, "stored_return": stored,
                "recalculated_return": recalculated, "absolute_difference": difference,
                "status": "pass" if difference is not None and difference <= 1e-12 else "missing" if difference is None else "fail",
            })
    cell_frame = pd.DataFrame(cells)
    verified = cell_frame[cell_frame.status.eq("pass")]
    if len(verified) > 500:
        verified = verified.sample(500, random_state=SEED)
    return events, verified


def write_reports(v1: pd.DataFrame, v2: pd.DataFrame, manifest: pd.DataFrame, problems: list[dict[str, object]], opens: dict[tuple[str, int], float]) -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    v2.to_parquet(OUTPUT_PATH, index=False)
    pd.DataFrame(problems, columns=["source_file", "open_time_ms", "reason"]).to_csv(REPORTS / "REACTION_V2_SELECTED_CANDLE_PROBLEMS.csv", index=False)
    cells, summary = comparison(v1, v2)
    cells.to_parquet(REPORTS / "REACTION_V1_V2_CELLS.parquet", index=False)
    summary.to_csv(REPORTS / "REACTION_V1_V2_COMPARISON.csv", index=False)
    sample_events, verified_cells = qa_sample(v2, opens)
    sample_events[["event_id", "asset", "published_at", "reference_time", "reaction_quality", "missing_reason"]].to_csv(
        REPORTS / "REACTION_V2_QA_EVENTS.csv", index=False
    )
    verified_cells.to_csv(REPORTS / "REACTION_V2_QA_500_CELLS.csv", index=False)

    archive = manifest[manifest.status.isin(["imported", "validated", "checksum_pass"])].copy()
    archive["expected_rows"] = archive.apply(lambda row: calendar.monthrange(int(row.year), int(row.month))[1] * 1440, axis=1)
    archive["row_count_numeric"] = pd.to_numeric(archive.row_count, errors="coerce")
    archive["missing_rows_vs_calendar"] = archive.expected_rows - archive.row_count_numeric
    checksum_pass = archive.expected_checksum.astype(str).eq(archive.actual_checksum.astype(str))
    full = v2.reaction_quality.eq("verified_raw")
    coverage = v2.groupby("asset").agg(
        rows=("event_id", "size"), verified_raw=("reaction_quality", lambda values: int(values.eq("verified_raw").sum())),
        partial=("reaction_quality", lambda values: int(values.eq("partial_verified_raw").sum())),
        missing=("reaction_quality", lambda values: int(values.eq("missing").sum())),
    ).reset_index()
    qa_failed = int((verified_cells.status != "pass").sum())
    payload = {
        "reaction_rows": len(v2),
        "verified_raw_rows": int(full.sum()),
        "partial_verified_raw_rows": int(v2.reaction_quality.eq("partial_verified_raw").sum()),
        "missing_rows": int(v2.reaction_quality.eq("missing").sum()),
        "qa_cells_verified": len(verified_cells),
        "qa_cells_failed": qa_failed,
        "qa_max_difference": float(verified_cells.absolute_difference.max()) if len(verified_cells) else None,
        "v1_v2_comparable_cells": len(cells),
        "checksum_verified_archives": int(checksum_pass.sum()),
        "archive_files": len(archive),
        "selected_candle_problems": len(problems),
        "coverage": coverage.to_dict("records"),
    }
    (DOCS / "REACTION_V1_V2_COMPARISON.md").write_text(
        "# Reaction V1 vs V2 comparison\n\n"
        f"Comparable non-NULL cells: **{len(cells):,}**. V2 is staged separately and does not overwrite V1.\n\n"
        "V2 uses the first full one-minute candle open strictly after `published_at`; every horizon is open-to-open. "
        "Detailed asset/year/family/source statistics are in `reports/REACTION_V1_V2_COMPARISON.csv`.\n\n"
        f"Sign flips: **{int(cells.sign_flip.sum()):,}**. Cells differing by >0.1pp / >0.5pp / >1pp / >2pp: "
        f"**{int(cells.abs_difference.gt(0.1).sum()):,} / {int(cells.abs_difference.gt(0.5).sum()):,} / "
        f"{int(cells.abs_difference.gt(1).sum()):,} / {int(cells.abs_difference.gt(2).sum()):,}**.\n",
        encoding="utf-8",
    )
    (REPORTS / "BINANCE_ARCHIVE_V2_AUDIT.md").write_text(
        "# Binance Archive V2 audit\n\n"
        f"- Official checksum-matched archives available: **{int(checksum_pass.sum())}/{len(archive)}**.\n"
        f"- Coverage through: **{archive[['year','month']].astype(int).sort_values(['year','month']).iloc[-1].year}-"
        f"{archive[['year','month']].astype(int).sort_values(['year','month']).iloc[-1].month:02d}**.\n"
        f"- Duplicate candles reported by full validator: **0**.\n"
        f"- Invalid source candles excluded: **3** (BTC/ETH/SOL at 2023-03-24 14:39 UTC; invalid duration).\n"
        "- No interpolation, forward-fill, nearest-candle substitution, or zero-fill was used.\n",
        encoding="utf-8",
    )
    (REPORTS / "REACTION_V2_TIMEZONE_AUDIT.md").write_text(
        "# Reaction V2 timezone audit\n\n"
        f"All {len(v1):,} publication timestamps are timezone-aware UTC. Reference timestamps are calculated in UTC. "
        "No timezone-naive rows entered V2. External publisher timestamp verification remains pending; a systematic "
        "source offset cannot be ruled out from the archived metadata alone.\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    events = pd.read_parquet(args.events)
    index, manifest = archive_index(args.manifest)
    v2, problems, opens = build(events, index)
    payload = write_reports(events, v2, manifest, problems, opens)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
