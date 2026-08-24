"""Rehearse or transactionally apply the final Reaction V2 artifact."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "data" / "reactions_v2" / "events_reactions_v2_final.parquet"
MIGRATION = ROOT / "database" / "migrations" / "007_reaction_v2_cutover.sql"
EXPECTED_PROJECT_REF = "ickflwksigaotygtdyko"
EXPECTED_ROWS = 7_878
ASSETS = ("btc", "eth", "sol")
HORIZONS = ("1m", "5m", "15m", "1h", "4h", "24h")
NON_REACTION_COLUMNS = (
    "event_id", "slug", "title", "published_at", "source", "source_url",
    "primary_asset", "related_assets", "category", "sentiment", "sentiment_score",
    "importance", "ai_schema_version", "ai_prompt_version", "ai_original_scale",
    "archive_dataset_source", "archive_member_id", "reaction_value_unit",
)
STAGE_COLUMNS = ["event_id", "reaction_methodology"]
for asset in ASSETS:
    STAGE_COLUMNS.extend([
        *[f"{asset}_{horizon}" for horizon in HORIZONS],
        f"{asset}_reaction_source", f"{asset}_reference_time",
        f"{asset}_reference_latency_minutes", f"{asset}_reaction_quality",
        f"{asset}_reaction_missing_reason",
    ])


def normalize_database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("postgresql+psycopg2://"):
        return "postgresql://" + value.removeprefix("postgresql+psycopg2://")
    if value.startswith("postgres://"):
        return "postgresql://" + value.removeprefix("postgres://")
    return value


def copy_value(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return r"\N"
    if isinstance(value, float) and np.isnan(value):
        return r"\N"
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def copy_buffer(frame: pd.DataFrame) -> io.StringIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in frame.itertuples(index=False, name=None):
        writer.writerow([copy_value(value) for value in row])
    buffer.seek(0)
    return buffer


def wide_stage() -> pd.DataFrame:
    final = pd.read_parquet(FINAL)
    if len(final) != EXPECTED_ROWS * 3 or final.event_id.nunique() != EXPECTED_ROWS:
        raise RuntimeError("Final V2 artifact identity gate failed")
    result = pd.DataFrame({"event_id": sorted(final.event_id.unique())})
    result["reaction_methodology"] = "reaction_v2_next_full_minute_open_to_open"
    for asset in ASSETS:
        part = final[final.asset.str.casefold().eq(asset)].copy()
        has_reaction = part[list(HORIZONS)].notna().any(axis=1).to_numpy()
        part = part.rename(columns={
            **{horizon: f"{asset}_{horizon}" for horizon in HORIZONS},
            "source": f"{asset}_reaction_source",
            "reference_time": f"{asset}_reference_time",
            "reaction_quality": f"{asset}_reaction_quality",
            "reaction_missing_reason": f"{asset}_reaction_missing_reason",
        })
        part[f"{asset}_reaction_source"] = np.where(
            has_reaction,
            "Binance Vision official monthly 1m archive", None,
        )
        part[f"{asset}_reference_latency_minutes"] = 0
        columns = [
            "event_id", *[f"{asset}_{horizon}" for horizon in HORIZONS],
            f"{asset}_reaction_source", f"{asset}_reference_time",
            f"{asset}_reference_latency_minutes", f"{asset}_reaction_quality",
            f"{asset}_reaction_missing_reason",
        ]
        result = result.merge(part[columns], on="event_id", validate="one_to_one")
    if list(result.columns) != STAGE_COLUMNS:
        raise RuntimeError("Unexpected V2 staging schema")
    return result


def create_stage(cursor, stage: pd.DataFrame) -> None:
    quality_check = "text"
    cursor.execute(f"""
        CREATE TEMP TABLE reaction_v2_stage (
            event_id text PRIMARY KEY,
            reaction_methodology text NOT NULL,
            {', '.join(f'{asset}_{horizon} double precision NULL' for asset in ASSETS for horizon in HORIZONS)},
            {', '.join(f'{asset}_reaction_source text NULL, {asset}_reference_time timestamptz NOT NULL, {asset}_reference_latency_minutes integer NOT NULL, {asset}_reaction_quality {quality_check} NOT NULL, {asset}_reaction_missing_reason jsonb NULL' for asset in ASSETS)}
        ) ON COMMIT DROP
    """)
    cursor.copy_expert(
        f"COPY pg_temp.reaction_v2_stage ({', '.join(STAGE_COLUMNS)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
        copy_buffer(stage),
    )


def update_sql(table: str) -> str:
    assignments = ["reaction_methodology = staged.reaction_methodology"]
    for asset in ASSETS:
        assignments.extend(f"{asset}_{horizon} = staged.{asset}_{horizon}" for horizon in HORIZONS)
        assignments.extend([
            f"{asset}_reaction_source = staged.{asset}_reaction_source",
            f"{asset}_reference_time = staged.{asset}_reference_time",
            f"{asset}_reference_latency_minutes = staged.{asset}_reference_latency_minutes",
            f"{asset}_reaction_quality = staged.{asset}_reaction_quality",
            f"{asset}_reaction_missing_reason = staged.{asset}_reaction_missing_reason",
        ])
    return f"UPDATE {table} live SET {', '.join(assignments)} FROM pg_temp.reaction_v2_stage staged WHERE live.event_id=staged.event_id"


def identity_gate(cursor) -> dict[str, int]:
    cursor.execute("SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug) FROM public.events")
    total, event_ids, slugs = map(int, cursor.fetchone())
    cursor.execute("SELECT count(*) FROM pg_temp.reaction_v2_stage")
    staged = int(cursor.fetchone()[0])
    cursor.execute("SELECT count(*) FROM pg_temp.reaction_v2_stage s JOIN public.events e USING(event_id)")
    matched = int(cursor.fetchone()[0])
    cursor.execute("SELECT count(*) FROM pg_temp.reaction_v2_stage s LEFT JOIN public.events e USING(event_id) WHERE e.event_id IS NULL")
    unknown = int(cursor.fetchone()[0])
    cursor.execute("SELECT count(*) FROM public.events e LEFT JOIN pg_temp.reaction_v2_stage s USING(event_id) WHERE s.event_id IS NULL")
    missing = int(cursor.fetchone()[0])
    result = {"production_rows": total, "unique_event_ids": event_ids, "unique_slugs": slugs, "staged_rows": staged, "matched_rows": matched, "unknown_ids": unknown, "missing_production_ids": missing}
    if set(result.values()) != {0, EXPECTED_ROWS} or any(result[key] != EXPECTED_ROWS for key in ("production_rows", "unique_event_ids", "unique_slugs", "staged_rows", "matched_rows")) or unknown or missing:
        raise RuntimeError(f"Identity gate failed: {result}")
    return result


def v2_mismatches(cursor, table: str) -> int:
    comparisons = []
    for asset in ASSETS:
        comparisons.extend(f"live.{asset}_{horizon} IS DISTINCT FROM staged.{asset}_{horizon}" for horizon in HORIZONS)
        comparisons.extend([
            f"live.{asset}_reaction_source IS DISTINCT FROM staged.{asset}_reaction_source",
            f"live.{asset}_reference_time IS DISTINCT FROM staged.{asset}_reference_time",
            f"live.{asset}_reference_latency_minutes IS DISTINCT FROM staged.{asset}_reference_latency_minutes",
            f"live.{asset}_reaction_quality IS DISTINCT FROM staged.{asset}_reaction_quality",
            f"live.{asset}_reaction_missing_reason IS DISTINCT FROM staged.{asset}_reaction_missing_reason",
        ])
    cursor.execute(f"SELECT count(*) FROM {table} live JOIN pg_temp.reaction_v2_stage staged USING(event_id) WHERE {' OR '.join(comparisons)}")
    return int(cursor.fetchone()[0])


def rehearsal(cursor, stage: pd.DataFrame) -> dict:
    create_stage(cursor, stage)
    identity = identity_gate(cursor)
    cursor.execute("CREATE TEMP TABLE events_rehearsal AS SELECT * FROM public.events")
    cursor.execute("CREATE TEMP TABLE events_v1_rehearsal AS SELECT * FROM pg_temp.events_rehearsal")
    for asset in ASSETS:
        cursor.execute(f"ALTER TABLE pg_temp.events_rehearsal ADD COLUMN {asset}_reaction_quality text NULL, ADD COLUMN {asset}_reaction_missing_reason jsonb NULL")
    cursor.execute(update_sql("pg_temp.events_rehearsal"))
    applied = int(cursor.rowcount)
    first_mismatch = v2_mismatches(cursor, "pg_temp.events_rehearsal")
    restore_columns = ["reaction_methodology"]
    for asset in ASSETS:
        restore_columns.extend([*[f"{asset}_{h}" for h in HORIZONS], f"{asset}_reaction_source", f"{asset}_reference_time", f"{asset}_reference_latency_minutes"])
    cursor.execute(f"UPDATE pg_temp.events_rehearsal r SET {', '.join(f'{column}=v.{column}' for column in restore_columns)} FROM pg_temp.events_v1_rehearsal v WHERE r.event_id=v.event_id")
    cursor.execute(f"SELECT count(*) FROM pg_temp.events_rehearsal r JOIN pg_temp.events_v1_rehearsal v USING(event_id) WHERE {' OR '.join(f'r.{column} IS DISTINCT FROM v.{column}' for column in restore_columns)}")
    rollback_mismatches = int(cursor.fetchone()[0])
    cursor.execute(update_sql("pg_temp.events_rehearsal"))
    reapplied = int(cursor.rowcount)
    second_mismatch = v2_mismatches(cursor, "pg_temp.events_rehearsal")
    status = "PASS" if applied == reapplied == EXPECTED_ROWS and first_mismatch == rollback_mismatches == second_mismatch == 0 else "FAIL"
    return {**identity, "first_apply_rows": applied, "first_v2_mismatches": first_mismatch, "rollback_v1_mismatches": rollback_mismatches, "second_apply_rows": reapplied, "second_v2_mismatches": second_mismatch, "status": status}


def apply_live(cursor, stage: pd.DataFrame) -> dict:
    cursor.execute(MIGRATION.read_text(encoding="utf-8"))
    create_stage(cursor, stage)
    identity = identity_gate(cursor)
    cursor.execute(f"CREATE TEMP TABLE nonreaction_before AS SELECT {', '.join(NON_REACTION_COLUMNS)} FROM public.events")
    cursor.execute(update_sql("public.events"))
    updated = int(cursor.rowcount)
    mismatches = v2_mismatches(cursor, "public.events")
    cursor.execute(f"SELECT count(*) FROM public.events live JOIN pg_temp.nonreaction_before old USING(event_id) WHERE {' OR '.join(f'live.{column} IS DISTINCT FROM old.{column}' for column in NON_REACTION_COLUMNS if column != 'event_id')}")
    nonreaction_changes = int(cursor.fetchone()[0])
    cursor.execute("SELECT count(*),count(DISTINCT event_id),count(DISTINCT slug) FROM public.events")
    totals = tuple(map(int, cursor.fetchone()))
    if updated != EXPECTED_ROWS or mismatches or nonreaction_changes or totals != (EXPECTED_ROWS, EXPECTED_ROWS, EXPECTED_ROWS):
        raise RuntimeError(f"Post-update gate failed: updated={updated}, mismatches={mismatches}, nonreaction={nonreaction_changes}, totals={totals}")
    return {**identity, "rows_updated": updated, "v2_mismatches": mismatches, "nonreaction_rows_changed": nonreaction_changes, "post_total": totals[0], "post_unique_event_ids": totals[1], "post_unique_slugs": totals[2], "status": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rehearse", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    parsed = urlparse(database_url)
    if EXPECTED_PROJECT_REF not in f"{parsed.hostname or ''} {parsed.username or ''}":
        raise RuntimeError("DATABASE_URL does not identify expected Supabase project")
    stage = wide_stage()
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            if args.rehearse:
                result = rehearsal(cursor, stage)
                connection.rollback()
                output = ROOT / "reports" / "REACTION_V2_ROLLBACK_REHEARSAL.json"
            else:
                result = apply_live(cursor, stage)
                connection.commit()
                result["cutover_time"] = datetime.now(timezone.utc).isoformat()
                output = ROOT / "reports" / "REACTION_V2_PRODUCTION_DATABASE_RESULT.json"
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
