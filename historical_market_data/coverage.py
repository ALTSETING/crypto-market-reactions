from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

from database.db import engine
from high_impact_sources.parsers.timestamp_parser import next_full_minute
from historical_market_data.importer import store_reaction


HORIZONS = {"1m": 1, "5m": 5, "10m": 10, "20m": 20, "40m": 40, "1h": 60, "3h": 180, "5h": 300, "8h": 480, "12h": 720}


def _window(symbol: str, start, end) -> pd.DataFrame:
    with engine.connect() as connection:
        frame = pd.read_sql(text("""SELECT open_time,open::double precision open,high::double precision high,
          low::double precision low,close::double precision close,volume::double precision volume
          FROM market_candles WHERE symbol=:symbol AND interval='1m' AND open_time BETWEEN :start AND :end ORDER BY open_time"""),
          connection, params={"symbol": symbol, "start": start, "end": end})
    frame["open_time"] = pd.to_datetime(frame.open_time, utc=True)
    return frame


def coverage_audit(stage16b_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    original = pd.read_csv(stage16b_path)
    original["published_at"] = pd.to_datetime(original.published_at, utc=True)
    with engine.connect() as connection:
        availability = pd.read_sql(text("""SELECT symbol,min(open_time) earliest,max(open_time) latest,count(*) candles
          FROM market_candles WHERE interval='1m' AND symbol=ANY(:symbols) GROUP BY symbol"""), connection,
          params={"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]}).set_index("symbol")
    rows = []
    for event in original.itertuples(index=False):
        baseline = pd.Timestamp(next_full_minute(event.published_at.to_pydatetime())).tz_convert("UTC")
        start, end = baseline - pd.Timedelta(minutes=720), baseline + pd.Timedelta(minutes=720)
        earliest = pd.Timestamp(availability.loc[event.symbol, "earliest"]).tz_convert("UTC")
        latest = pd.Timestamp(availability.loc[event.symbol, "latest"]).tz_convert("UTC")
        pre_listing = bool(event.published_at < earliest)
        asset = _window(event.symbol, start.to_pydatetime(), end.to_pydatetime()) if not pre_listing else pd.DataFrame()
        benchmark = asset if event.symbol == "BTCUSDT" else (_window("BTCUSDT", start.to_pydatetime(), end.to_pydatetime()) if not pre_listing else pd.DataFrame())
        expected = pd.date_range(start, end, freq="min", tz="UTC")
        aset = set(asset.open_time) if len(asset) else set(); bset = set(benchmark.open_time) if len(benchmark) else set()
        missing_asset = expected.difference(pd.DatetimeIndex(sorted(aset)))
        missing_btc = expected.difference(pd.DatetimeIndex(sorted(bset)))
        pre_complete = all((baseline - pd.Timedelta(minutes=i)) in aset for i in range(1, 721)) and all((baseline - pd.Timedelta(minutes=i)) in bset for i in range(1, 721))
        missing_horizons = [label for label, minute in HORIZONS.items() if baseline + pd.Timedelta(minutes=minute) not in aset or baseline + pd.Timedelta(minutes=minute) not in bset]
        baseline_ok = baseline in aset and baseline in bset
        fully = baseline_ok and pre_complete and not missing_horizons and not len(missing_asset) and not len(missing_btc)
        reason = "fully_covered" if fully else "pre_listing" if pre_listing else "candle_gap_overlap" if len(missing_asset) or len(missing_btc) else "missing_context"
        rows.append({
            "canonical_event_id": event.canonical_event_id, "event_group_id": event.event_group_id,
            "published_at": event.published_at, "asset": event.asset, "symbol": event.symbol,
            "baseline_time": baseline, "fully_covered": fully, "missing_pre_context": not pre_complete,
            "missing_post_context": bool(missing_horizons), "pre_listing": pre_listing,
            "candle_gap_overlap": bool(len(missing_asset) or len(missing_btc)), "missing_horizons": "|".join(missing_horizons),
            "earliest_required_candle": start, "latest_required_candle": end,
            "missing_asset_minutes": len(missing_asset), "missing_btc_minutes": len(missing_btc),
            "coverage_reason": reason, "earliest_available_candle": earliest, "latest_available_candle": latest,
        })
    result = pd.DataFrame(rows)
    joined = result.merge(pd.read_parquet("data/stage16b/canonical_events.parquet")[["canonical_event_id", "source", "calendar_year"]], on="canonical_event_id", how="left")
    summary = {
        "historical_rows_total": len(result), "fully_covered": int(result.fully_covered.sum()),
        "partially_covered": int((~result.fully_covered & ~result.pre_listing).sum()), "pre_listing": int(result.pre_listing.sum()),
        "missing_due_to_gaps": int(result.candle_gap_overlap.sum()), "safe_reactions": int(result.fully_covered.sum()),
        "coverage_by_asset": joined.groupby("asset").agg(rows=("canonical_event_id", "size"), fully_covered=("fully_covered", "sum"), pre_listing=("pre_listing", "sum")).reset_index().to_dict("records"),
        "coverage_by_year": joined.groupby("calendar_year").agg(rows=("canonical_event_id", "size"), fully_covered=("fully_covered", "sum"), pre_listing=("pre_listing", "sum")).reset_index().to_dict("records"),
        "coverage_by_source": joined.groupby("source").agg(rows=("canonical_event_id", "size"), fully_covered=("fully_covered", "sum"), pre_listing=("pre_listing", "sum")).reset_index().to_dict("records"),
    }
    return result, summary


def generate_reactions(coverage: pd.DataFrame) -> dict[str, int]:
    inserted = skipped = 0
    for event in coverage[coverage.fully_covered].itertuples(index=False):
        start, end = event.baseline_time - pd.Timedelta(minutes=720), event.baseline_time + pd.Timedelta(minutes=720)
        asset = _window(event.symbol, start.to_pydatetime(), end.to_pydatetime()).set_index("open_time")
        btc = asset if event.symbol == "BTCUSDT" else _window("BTCUSDT", start.to_pydatetime(), end.to_pydatetime()).set_index("open_time")
        base = float(asset.loc[event.baseline_time, "open"]); btc_base = float(btc.loc[event.baseline_time, "open"])
        pre_asset = np.diff(np.log(asset.loc[start:event.baseline_time - pd.Timedelta(minutes=1), "open"].to_numpy()))
        pre_btc = np.diff(np.log(btc.loc[start:event.baseline_time - pd.Timedelta(minutes=1), "open"].to_numpy()))
        beta = float(np.cov(pre_asset, pre_btc, ddof=1)[0, 1] / np.var(pre_btc, ddof=1)) if event.symbol != "BTCUSDT" and np.var(pre_btc) else 1.0
        metrics: dict[str, Any] = {"beta_btc_12h": beta}
        for label, minutes in HORIZONS.items():
            when = event.baseline_time + pd.Timedelta(minutes=minutes)
            raw = (float(asset.loc[when, "open"]) / base - 1) * 100
            benchmark = (float(btc.loc[when, "open"]) / btc_base - 1) * 100
            metrics[f"return_{label}"] = raw; metrics[f"abs_return_{label}"] = abs(raw)
            metrics[f"abnormal_return_{label}"] = raw if event.symbol == "BTCUSDT" else raw - beta * benchmark
        for label, minutes in (("1h", 60), ("12h", 720)):
            window = asset.loc[event.baseline_time:event.baseline_time + pd.Timedelta(minutes=minutes)]
            metrics[f"max_favorable_{label}"] = float((window.high / base - 1).max() * 100)
            metrics[f"max_adverse_{label}"] = float((window.low / base - 1).min() * 100)
            metrics[f"realized_vol_{label}"] = float(np.sqrt(np.sum(np.diff(np.log(window.open.to_numpy())) ** 2)) * 100)
        pre_volume = asset.loc[event.baseline_time - pd.Timedelta(minutes=60):event.baseline_time - pd.Timedelta(minutes=1), "volume"].mean()
        post_volume = asset.loc[event.baseline_time:event.baseline_time + pd.Timedelta(minutes=59), "volume"].mean()
        metrics["volume_reaction_1h"] = float(post_volume / pre_volume) if pre_volume else None
        if store_reaction(event.canonical_event_id, event.symbol, event.baseline_time.to_pydatetime(), metrics): inserted += 1
        else: skipped += 1
    return {"eligible": int(coverage.fully_covered.sum()), "inserted": inserted, "skipped_existing": skipped}

