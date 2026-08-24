"""Restore the pre-cutover V1 reaction state transactionally from the final backup."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "data/website/backups/pre_reaction_v2_cutover/supabase_events_v1.parquet"
BACKUP_REPORT = ROOT / "reports/REACTION_V2_PRE_CUTOVER_BACKUP.json"
EXPECTED_PROJECT_REF = "ickflwksigaotygtdyko"
EXPECTED_ROWS = 7_878
ASSETS = ("btc", "eth", "sol")
HORIZONS = ("1m", "5m", "15m", "1h", "4h", "24h")
REACTION_COLUMNS = ["reaction_methodology"]
for asset in ASSETS:
    REACTION_COLUMNS.extend(
        [*[f"{asset}_{h}" for h in HORIZONS], f"{asset}_reaction_source",
         f"{asset}_reference_time", f"{asset}_reference_latency_minutes"]
    )


def normalize_database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("postgresql+psycopg2://"):
        return "postgresql://" + value.removeprefix("postgresql+psycopg2://")
    if value.startswith("postgres://"):
        return "postgresql://" + value.removeprefix("postgres://")
    return value


def copy_buffer(frame: pd.DataFrame) -> io.StringIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in frame.itertuples(index=False, name=None):
        values = []
        for value in row:
            if value is None or value is pd.NA or value is pd.NaT or (isinstance(value, float) and np.isnan(value)):
                values.append(r"\N")
            elif isinstance(value, pd.Timestamp):
                values.append(value.isoformat())
            else:
                values.append(value)
        writer.writerow(values)
    buffer.seek(0)
    return buffer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-backup", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.verify_backup == args.apply:
        parser.error("choose exactly one of --verify-backup or --apply")

    backup = pd.read_parquet(BACKUP)
    report = json.loads(BACKUP_REPORT.read_text(encoding="utf-8"))
    if len(backup) != EXPECTED_ROWS or backup.event_id.nunique() != EXPECTED_ROWS or backup.slug.nunique() != EXPECTED_ROWS:
        raise RuntimeError("V1 backup identity gate failed")
    load_dotenv(ROOT / ".env")
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    parsed = urlparse(database_url)
    if EXPECTED_PROJECT_REF not in f"{parsed.hostname or ''} {parsed.username or ''}":
        raise RuntimeError("DATABASE_URL does not identify expected Supabase project")

    connection = psycopg2.connect(database_url)
    result = {"backup_rows": len(backup), "backup_hash": report["backup_hash"], "status": "PASS"}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug) FROM public.events")
            totals = tuple(map(int, cursor.fetchone()))
            if totals != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS):
                raise RuntimeError(f"Live identity gate failed: {totals}")
            if args.verify_backup:
                cursor.execute("CREATE TEMP TABLE v1_ids(event_id text PRIMARY KEY) ON COMMIT DROP")
                cursor.copy_expert("COPY pg_temp.v1_ids(event_id) FROM STDIN WITH (FORMAT CSV)", copy_buffer(backup[["event_id"]]))
                cursor.execute("SELECT count(*) FROM pg_temp.v1_ids b JOIN public.events e USING(event_id)")
                result["matched_live_ids"] = int(cursor.fetchone()[0])
                if result["matched_live_ids"] != EXPECTED_ROWS:
                    raise RuntimeError("Backup/live ID mismatch")
                connection.rollback()
            else:
                definitions = ["event_id text PRIMARY KEY", "reaction_methodology text"]
                definitions.extend(f"{asset}_{h} double precision" for asset in ASSETS for h in HORIZONS)
                for asset in ASSETS:
                    definitions.extend([f"{asset}_reaction_source text", f"{asset}_reference_time timestamptz", f"{asset}_reference_latency_minutes integer"])
                cursor.execute(f"CREATE TEMP TABLE v1_restore ({', '.join(definitions)}) ON COMMIT DROP")
                columns = ["event_id", *REACTION_COLUMNS]
                cursor.copy_expert(f"COPY pg_temp.v1_restore ({', '.join(columns)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", copy_buffer(backup[columns]))
                assignments = ", ".join(f"{column}=old.{column}" for column in REACTION_COLUMNS)
                cursor.execute(f"UPDATE public.events live SET {assignments} FROM pg_temp.v1_restore old WHERE live.event_id=old.event_id")
                result["rows_restored"] = int(cursor.rowcount)
                comparisons = " OR ".join(f"live.{column} IS DISTINCT FROM old.{column}" for column in REACTION_COLUMNS)
                cursor.execute(f"SELECT count(*) FROM public.events live JOIN pg_temp.v1_restore old USING(event_id) WHERE {comparisons}")
                result["reaction_mismatches"] = int(cursor.fetchone()[0])
                if result["rows_restored"] != EXPECTED_ROWS or result["reaction_mismatches"]:
                    raise RuntimeError(f"Rollback validation failed: {result}")
                for asset in ASSETS:
                    cursor.execute(f"ALTER TABLE public.events DROP COLUMN IF EXISTS {asset}_reaction_quality, DROP COLUMN IF EXISTS {asset}_reaction_missing_reason")
                connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
