from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from sqlalchemy import text

from database.db import engine
from historical_market_data.parser import iter_zip_rows, raw_row_hash
from historical_market_data.validator import validate_candle


STAGING_DDL = """
CREATE UNLOGGED TABLE IF NOT EXISTS historical_market_candles_staging (
 symbol varchar(20) NOT NULL, interval varchar(10) NOT NULL,
 open_time timestamptz NOT NULL, close_time timestamptz NOT NULL,
 open numeric(30,12) NOT NULL, high numeric(30,12) NOT NULL,
 low numeric(30,12) NOT NULL, close numeric(30,12) NOT NULL,
 volume numeric(38,12) NOT NULL, quote_volume numeric(38,12) NOT NULL,
 trade_count bigint NOT NULL, taker_buy_base_volume numeric(38,12) NOT NULL,
 taker_buy_quote_volume numeric(38,12) NOT NULL, source_type varchar(20) NOT NULL,
 source_file text NOT NULL, source_sha256 varchar(64) NOT NULL,
 timestamp_precision varchar(20) NOT NULL, imported_at_utc timestamptz NOT NULL
)
"""

REACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS stage16c_market_reactions (
 id bigserial PRIMARY KEY, canonical_event_id varchar(64) NOT NULL,
 symbol varchar(20) NOT NULL, baseline_time timestamptz NOT NULL,
 latency_minutes integer NOT NULL, reaction_version varchar(50) NOT NULL,
 metrics_json jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(canonical_event_id,symbol,latency_minutes,reaction_version)
)
"""


def ensure_tables() -> None:
    with engine.begin() as connection:
        connection.execute(text(STAGING_DDL))
        connection.execute(text(REACTIONS_DDL))


def prepare_zip(path: Path, symbol: str, interval: str, checksum: str, temp_dir: Path) -> dict[str, Any]:
    temp_dir.mkdir(parents=True, exist_ok=True)
    handle = NamedTemporaryFile("w", newline="", encoding="utf-8", suffix=".tsv", dir=temp_dir, delete=False)
    writer = csv.writer(handle, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    invalid, duplicates, seen = [], [], set()
    rows = 0; first = last = None; precisions = set()
    try:
        for row_number, raw, candle, parse_error in iter_zip_rows(path, symbol, interval, "monthly", checksum):
            errors = [parse_error] if parse_error else validate_candle(candle, symbol, interval)
            if errors:
                invalid.append({"symbol": symbol, "source_file": path.name, "source_row_number": row_number, "open_time_raw": raw[0] if raw else None, "validation_error": "|".join(errors), "raw_row_hash": raw_row_hash(raw)})
                continue
            assert candle is not None
            identity = candle.open_time
            if identity in seen:
                duplicates.append({"symbol": symbol, "interval": interval, "open_time": identity.isoformat(), "source_file": path.name, "reason": "duplicate_within_source_file"})
                continue
            seen.add(identity); rows += 1; first = first or candle.open_time; last = candle.open_time; precisions.add(candle.timestamp_precision)
            writer.writerow([
                candle.symbol, candle.interval, candle.open_time.isoformat(), candle.close_time.isoformat(),
                str(candle.open), str(candle.high), str(candle.low), str(candle.close), str(candle.volume),
                str(candle.quote_volume), candle.trade_count, str(candle.taker_buy_base_volume),
                str(candle.taker_buy_quote_volume), candle.source_type, candle.source_file, candle.source_sha256,
                candle.timestamp_precision, datetime.now(timezone.utc).isoformat(),
            ])
    finally:
        handle.close()
    return {"temp_path": Path(handle.name), "row_count": rows, "first_open_time": first, "last_open_time": last, "timestamp_precision": "+".join(sorted(precisions)), "invalid": invalid, "duplicates": duplicates}


def import_prepared(prepared: dict[str, Any]) -> dict[str, Any]:
    ensure_tables()
    raw = engine.raw_connection()
    inserted = conflicts = 0
    try:
        cursor = raw.cursor()
        cursor.execute("TRUNCATE historical_market_candles_staging")
        with prepared["temp_path"].open("r", encoding="utf-8", newline="") as handle:
            cursor.copy_expert("""COPY historical_market_candles_staging
              (symbol,interval,open_time,close_time,open,high,low,close,volume,quote_volume,trade_count,
               taker_buy_base_volume,taker_buy_quote_volume,source_type,source_file,source_sha256,timestamp_precision,imported_at_utc)
              FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t')""", handle)
        cursor.execute("""SELECT count(*) FROM historical_market_candles_staging s JOIN market_candles c
          ON c.symbol=s.symbol AND c.interval=s.interval AND c.open_time=s.open_time
          WHERE c.open<>s.open OR c.high<>s.high OR c.low<>s.low OR c.close<>s.close OR c.volume<>s.volume""")
        conflicts = int(cursor.fetchone()[0])
        cursor.execute("""INSERT INTO market_candles(symbol,interval,open_time,close_time,open,high,low,close,volume)
          SELECT symbol,interval,open_time,close_time,open,high,low,close,volume
          FROM historical_market_candles_staging
          ON CONFLICT(symbol,interval,open_time) DO NOTHING""")
        inserted = int(cursor.rowcount)
        cursor.execute("TRUNCATE historical_market_candles_staging")
        raw.commit()
    except Exception:
        raw.rollback(); raise
    finally:
        raw.close()
        prepared["temp_path"].unlink(missing_ok=True)
    return {"staged": int(prepared["row_count"]), "inserted": inserted, "updated": 0, "deleted": 0, "source_conflicts": conflicts}


def store_reaction(canonical_event_id: str, symbol: str, baseline_time: datetime, metrics: dict[str, Any]) -> bool:
    ensure_tables()
    with engine.begin() as connection:
        result = connection.execute(text("""INSERT INTO stage16c_market_reactions
          (canonical_event_id,symbol,baseline_time,latency_minutes,reaction_version,metrics_json)
          VALUES(:event,:symbol,:baseline,1,'stage16c_archive_v1',cast(:metrics AS jsonb))
          ON CONFLICT(canonical_event_id,symbol,latency_minutes,reaction_version) DO NOTHING"""),
          {"event": canonical_event_id, "symbol": symbol, "baseline": baseline_time, "metrics": json.dumps(metrics, allow_nan=False)})
        return bool(result.rowcount)

