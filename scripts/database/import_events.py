"""Validate and idempotently import events_mvp.parquet into PostgreSQL.

The importer uses a temporary staging table, PostgreSQL COPY, and an
``ON CONFLICT (event_id) DO UPDATE`` merge.  It works with ordinary PostgreSQL
and Supabase PostgreSQL connection strings.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import psycopg2
import pyarrow.parquet as pq
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_DATASET = ROOT / "data" / "website" / "events_mvp.parquet"
ASSETS = {"BTC", "ETH", "SOL"}
HORIZONS = ("1m", "5m", "15m", "1h", "4h", "24h")

DATASET_COLUMNS = [
    "event_id", "title", "published_at", "source", "source_url",
    "primary_asset", "related_assets", "category", "sentiment",
    "sentiment_score", "importance", "ai_schema_version",
    "ai_prompt_version", "ai_original_scale", "archive_dataset_source",
    "archive_member_id", "reaction_methodology", "reaction_value_unit",
    "btc_1m", "btc_5m", "btc_15m", "btc_1h", "btc_4h", "btc_24h",
    "btc_reaction_source", "btc_reference_time",
    "btc_reference_latency_minutes",
    "eth_1m", "eth_5m", "eth_15m", "eth_1h", "eth_4h", "eth_24h",
    "eth_reaction_source", "eth_reference_time",
    "eth_reference_latency_minutes",
    "sol_1m", "sol_5m", "sol_15m", "sol_1h", "sol_4h", "sol_24h",
    "sol_reaction_source", "sol_reference_time",
    "sol_reference_latency_minutes",
]

ARROW_TYPES = {
    **{column: "large_string" for column in DATASET_COLUMNS if column not in {
        "published_at", "btc_reference_time", "eth_reference_time", "sol_reference_time",
        "sentiment_score", "importance",
        *[f"{asset}_{horizon}" for asset in ("btc", "eth", "sol") for horizon in HORIZONS],
        "btc_reference_latency_minutes", "eth_reference_latency_minutes", "sol_reference_latency_minutes",
    }},
    "published_at": "timestamp[us, tz=UTC]",
    "btc_reference_time": "timestamp[us, tz=UTC]",
    "eth_reference_time": "timestamp[us, tz=UTC]",
    "sol_reference_time": "timestamp[us, tz=UTC]",
    "sentiment_score": "double",
    "importance": "double",
    **{f"{asset}_{horizon}": "double" for asset in ("btc", "eth", "sol") for horizon in HORIZONS},
    "btc_reference_latency_minutes": "int64",
    "eth_reference_latency_minutes": "int64",
    "sol_reference_latency_minutes": "int64",
}

NON_NULL_COLUMNS = {
    "event_id", "title", "published_at", "source", "source_url",
    "related_assets", "category", "ai_schema_version", "ai_original_scale",
    "archive_dataset_source", "archive_member_id", "reaction_methodology",
    "reaction_value_unit",
}

IMPORT_COLUMNS = ["event_id", "slug", *DATASET_COLUMNS[1:]]
CLASSIFICATION_COLUMNS = ["event_id", "primary_asset", "related_assets"]


class DatasetValidationError(ValueError):
    """Raised when events_mvp no longer matches the database contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return normalized or "event"


def event_suffix(event_id: str, length: int = 8) -> str:
    token = re.sub(r"[^a-z0-9]", "", event_id.lower())
    if token.startswith("evt18"):
        token = token[5:]
    return (token or hashlib.sha256(event_id.encode("utf-8")).hexdigest())[:length]


def make_slug(title: str, published_at: pd.Timestamp, event_id: str, suffix_length: int = 8) -> str:
    year = pd.Timestamp(published_at).year
    suffix = event_suffix(event_id, suffix_length)
    tail = f"-{year}-{suffix}"
    readable = slugify_title(title)[: 180 - len(tail)].rstrip("-")
    return readable + tail


def make_unique_slugs(frame: pd.DataFrame) -> pd.Series:
    slugs = pd.Series(
        [make_slug(row.title, row.published_at, row.event_id, 8) for row in frame.itertuples()],
        index=frame.index,
        dtype="string",
    )
    duplicate_mask = slugs.duplicated(keep=False)
    if duplicate_mask.any():
        slugs.loc[duplicate_mask] = [
            make_slug(row.title, row.published_at, row.event_id, 12)
            for row in frame.loc[duplicate_mask].itertuples()
        ]
    if slugs.duplicated().any():
        raise DatasetValidationError("Stable slug suffix collision remains after 12 characters")
    return slugs


def parse_related_assets(value: Any) -> list[str]:
    if not isinstance(value, str):
        raise DatasetValidationError("related_assets must be a JSON string")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(f"Invalid related_assets JSON: {value!r}") from exc
    if not isinstance(parsed, list):
        raise DatasetValidationError("related_assets must be a JSON array")
    assets = [str(item) for item in parsed]
    if len(assets) != len(set(assets)) or not set(assets).issubset(ASSETS):
        raise DatasetValidationError(f"Invalid related_assets values: {assets!r}")
    return assets


def validate_arrow_schema(path: Path) -> None:
    schema = pq.ParquetFile(path).schema_arrow
    actual_columns = schema.names
    if actual_columns != DATASET_COLUMNS:
        raise DatasetValidationError(
            f"Unexpected Parquet columns/order. Expected {DATASET_COLUMNS!r}, got {actual_columns!r}"
        )
    mismatches = {
        field.name: {"expected": ARROW_TYPES[field.name], "actual": str(field.type)}
        for field in schema
        if str(field.type) != ARROW_TYPES[field.name]
    }
    if mismatches:
        raise DatasetValidationError(f"Unexpected Arrow types: {mismatches}")


def prepare_dataset(path: Path, expected_rows: int | None = None) -> pd.DataFrame:
    path = path.resolve()
    if not path.is_file():
        raise DatasetValidationError(f"Dataset does not exist: {path}")
    validate_arrow_schema(path)
    frame = pd.read_parquet(path)
    if expected_rows is not None and len(frame) != expected_rows:
        raise DatasetValidationError(f"Expected {expected_rows} rows, found {len(frame)}")
    if frame.event_id.nunique(dropna=False) != len(frame):
        raise DatasetValidationError("event_id is not unique")

    for column in NON_NULL_COLUMNS:
        if frame[column].isna().any():
            raise DatasetValidationError(f"Required column contains NULL: {column}")
    for column in ("event_id", "title", "source", "source_url"):
        if frame[column].astype(str).str.strip().eq("").any():
            raise DatasetValidationError(f"Required column contains an empty string: {column}")

    frame["published_at"] = pd.to_datetime(frame.published_at, utc=True, errors="raise")
    for asset in ("btc", "eth", "sol"):
        time_column = f"{asset}_reference_time"
        frame[time_column] = pd.to_datetime(frame[time_column], utc=True, errors="coerce")
        latency_column = f"{asset}_reference_latency_minutes"
        invalid_latency = frame[latency_column].dropna().lt(0)
        if invalid_latency.any():
            raise DatasetValidationError(f"Negative latency in {latency_column}")

    frame["related_assets"] = frame.related_assets.map(parse_related_assets)
    invalid_primary = frame.primary_asset.notna() & ~frame.primary_asset.isin(ASSETS)
    if invalid_primary.any():
        raise DatasetValidationError("primary_asset contains an unsupported value")
    if frame.reaction_value_unit.ne("percent").any():
        raise DatasetValidationError("reaction_value_unit must be percent")

    reaction_columns = [f"{asset}_{horizon}" for asset in ("btc", "eth", "sol") for horizon in HORIZONS]
    numeric = frame[reaction_columns].to_numpy(dtype=float)
    if np.isinf(numeric).any():
        raise DatasetValidationError("Infinite reaction value detected")
    finite = numeric[np.isfinite(numeric)]
    if (finite <= -100.0).any():
        raise DatasetValidationError("Impossible percentage return at or below -100 detected")

    frame.insert(1, "slug", make_unique_slugs(frame))
    if frame.slug.nunique() != len(frame):
        raise DatasetValidationError("Generated slug is not unique")
    return frame[IMPORT_COLUMNS]


def normalize_database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("postgresql+psycopg2://"):
        return "postgresql://" + value.removeprefix("postgresql+psycopg2://")
    if value.startswith("postgres://"):
        return "postgresql://" + value.removeprefix("postgres://")
    return value


def copy_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return r"\N"
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return r"\N"
    if isinstance(value, pd.Timestamp):
        return r"\N" if pd.isna(value) else value.isoformat()
    if isinstance(value, list):
        return "{" + ",".join(value) + "}"
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def batch_rows(frame: pd.DataFrame, batch_size: int) -> Iterable[pd.DataFrame]:
    for start in range(0, len(frame), batch_size):
        yield frame.iloc[start : start + batch_size]


def copy_buffer(frame: pd.DataFrame) -> io.StringIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in frame.itertuples(index=False, name=None):
        writer.writerow([copy_value(value) for value in row])
    buffer.seek(0)
    return buffer


def verify_database_contract(cursor: Any) -> None:
    cursor.execute("SELECT to_regclass('public.events')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError(
            "public.events does not exist; apply database/migrations/001_create_events.sql first"
        )
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'events'
    """)
    existing = {row[0] for row in cursor.fetchall()}
    required = set(IMPORT_COLUMNS) | {"search_vector", "created_at", "updated_at"}
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(f"public.events is missing columns: {missing}")


def import_events(frame: pd.DataFrame, database_url: str, batch_size: int) -> dict[str, int]:
    columns_sql = ", ".join(IMPORT_COLUMNS)
    updates = ",\n            ".join(
        f"{column} = EXCLUDED.{column}" for column in IMPORT_COLUMNS if column != "event_id"
    )
    merge_sql = f"""
        INSERT INTO public.events ({columns_sql})
        SELECT {columns_sql} FROM pg_temp.events_import
        ON CONFLICT (event_id) DO UPDATE SET
            {updates},
            updated_at = now()
    """
    copy_sql = (
        f"COPY pg_temp.events_import ({columns_sql}) "
        "FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
    )

    connection = psycopg2.connect(normalize_database_url(database_url))
    try:
        with connection:
            with connection.cursor() as cursor:
                verify_database_contract(cursor)
                cursor.execute("""
                    CREATE TEMP TABLE events_import
                    (LIKE public.events INCLUDING DEFAULTS)
                    ON COMMIT DROP
                """)
                merged_rows = 0
                for batch in batch_rows(frame, batch_size):
                    cursor.copy_expert(copy_sql, copy_buffer(batch))
                    cursor.execute(merge_sql)
                    merged_rows += cursor.rowcount
                    cursor.execute("TRUNCATE pg_temp.events_import")
                cursor.execute(
                    "SELECT count(*) FROM public.events WHERE event_id = ANY(%s)",
                    (frame.event_id.tolist(),),
                )
                matched_rows = int(cursor.fetchone()[0])
                cursor.execute("SELECT count(*) FROM public.events")
                total_rows = int(cursor.fetchone()[0])
        if matched_rows != len(frame):
            raise RuntimeError(f"Post-import event match count is {matched_rows}, expected {len(frame)}")
        return {"merged_rows": merged_rows, "matched_dataset_rows": matched_rows, "total_table_rows": total_rows}
    finally:
        connection.close()


def update_event_classification(frame: pd.DataFrame, database_url: str) -> dict[str, int]:
    """Atomically update only asset-classification fields for existing events."""

    connection = psycopg2.connect(normalize_database_url(database_url))
    try:
        with connection:
            with connection.cursor() as cursor:
                verify_database_contract(cursor)
                cursor.execute("SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug) FROM public.events")
                before_total, before_event_ids, before_slugs = map(int, cursor.fetchone())
                if before_total != len(frame) or before_event_ids != before_total or before_slugs != before_total:
                    raise RuntimeError(
                        "Target events table must exactly match the unique classification dataset before update"
                    )

                cursor.execute("""
                    CREATE TEMP TABLE events_classification_import (
                        event_id text PRIMARY KEY,
                        primary_asset text NULL,
                        related_assets text[] NOT NULL
                    ) ON COMMIT DROP
                """)
                copy_sql = (
                    "COPY pg_temp.events_classification_import "
                    "(event_id, primary_asset, related_assets) "
                    "FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
                )
                cursor.copy_expert(copy_sql, copy_buffer(frame[CLASSIFICATION_COLUMNS]))
                cursor.execute("""
                    SELECT count(*)
                    FROM pg_temp.events_classification_import staged
                    JOIN public.events live USING (event_id)
                """)
                matched_rows = int(cursor.fetchone()[0])
                if matched_rows != len(frame):
                    raise RuntimeError(
                        f"Classification staging matched {matched_rows} events, expected {len(frame)}"
                    )

                cursor.execute("""
                    UPDATE public.events AS live
                    SET primary_asset = staged.primary_asset,
                        related_assets = staged.related_assets,
                        updated_at = now()
                    FROM pg_temp.events_classification_import AS staged
                    WHERE live.event_id = staged.event_id
                      AND (
                          live.primary_asset IS DISTINCT FROM staged.primary_asset
                          OR live.related_assets IS DISTINCT FROM staged.related_assets
                      )
                """)
                changed_rows = int(cursor.rowcount)
                cursor.execute("SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug) FROM public.events")
                after_total, after_event_ids, after_slugs = map(int, cursor.fetchone())
                if (after_total, after_event_ids, after_slugs) != (
                    before_total,
                    before_event_ids,
                    before_slugs,
                ):
                    raise RuntimeError("Classification update changed event counts or uniqueness")
        return {
            "matched_dataset_rows": matched_rows,
            "changed_rows": changed_rows,
            "total_table_rows": after_total,
            "unique_event_ids": after_event_ids,
            "unique_slugs": after_slugs,
        }
    finally:
        connection.close()


def dry_run_summary(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    reaction_full = {}
    for asset in ("btc", "eth", "sol"):
        columns = [f"{asset}_{horizon}" for horizon in HORIZONS]
        reaction_full[asset.upper()] = int(frame[columns].notna().all(axis=1).sum())
    return {
        "mode": "dry-run",
        "dataset": str(path.resolve()),
        "dataset_sha256": sha256_file(path),
        "rows": len(frame),
        "unique_event_id": int(frame.event_id.nunique()),
        "unique_slug": int(frame.slug.nunique()),
        "asset_counts": {
            asset: int(frame.related_assets.map(lambda assets: asset in assets).sum())
            for asset in sorted(ASSETS)
        },
        "empty_related_assets": int(frame.related_assets.map(len).eq(0).sum()),
        "slug_examples": frame[["event_id", "slug"]].head(5).to_dict("records"),
        "null_sentiment": int(frame.sentiment.isna().sum()),
        "null_importance": int(frame.importance.isna().sum()),
        "full_reaction_coverage": reaction_full,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument(
        "--manifest", type=Path,
        help="Validate or insert only the new IDs from a release manifest",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and generate slugs without connecting to PostgreSQL",
    )
    parser.add_argument(
        "--preflight", action="store_true",
        help="Run manifest and read-only target validation without writing",
    )
    parser.add_argument(
        "--confirm-production-write",
        help="Exact confirmation token required for every database write",
    )
    parser.add_argument(
        "--classification-only",
        action="store_true",
        help="Update only primary_asset and related_assets for existing event IDs",
    )
    return parser.parse_args()


def run_manifest_mode(args: argparse.Namespace) -> int:
    from scripts.database.release_backfill import (
        ReleasePreflightError,
        insert_new_events,
        preflight_database,
    )
    from scripts.database.release_contract import ReleaseValidationError, validate_manifest

    try:
        if args.classification_only:
            raise ReleasePreflightError("--classification-only is incompatible with --manifest")
        if args.dry_run:
            _, manifest, stats = validate_manifest(args.manifest)
            result = {
                "status": "PASS", "mode": "dry-run", **stats,
                "dataset_sha256": manifest["dataset"]["sha256"],
                "content_sha256": manifest["dataset"]["content_sha256"],
                "new_ids_sha256": manifest["identity"]["new_ids_sha256"],
                "production_updated": False,
            }
        else:
            load_dotenv(ROOT / ".env")
            database_url = os.getenv("DATABASE_URL", "").strip()
            if not database_url:
                raise ReleasePreflightError("DATABASE_URL is required for manifest preflight/import")
            if args.preflight:
                result = preflight_database(database_url, args.manifest)
            elif args.confirm_production_write:
                result = insert_new_events(
                    database_url, args.manifest, args.confirm_production_write
                )
            else:
                raise ReleasePreflightError(
                    "Manifest mode requires --dry-run, --preflight, or explicit production confirmation"
                )
        print(json.dumps(result, indent=2))
        return 0
    except (ReleasePreflightError, ReleaseValidationError) as exc:
        print(json.dumps({
            "status": "FAIL",
            "mode": "preflight" if args.preflight else "manifest-validation",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "production_updated": False,
        }, indent=2))
        return 1


def main() -> int:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    if args.manifest:
        return run_manifest_mode(args)

    if args.preflight:
        raise ValueError("--preflight requires --manifest")
    frame = prepare_dataset(args.dataset)
    if args.dry_run:
        print(json.dumps(dry_run_summary(frame, args.dataset), ensure_ascii=False, indent=2))
        return 0

    load_dotenv(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required; copy .env.example to .env outside version control")
    expected_confirmation = (
        "LEGACY-CLASSIFICATION-UPDATE" if args.classification_only else "LEGACY-FULL-IMPORT"
    )
    if args.confirm_production_write != expected_confirmation:
        raise RuntimeError(
            f"Legacy database write requires --confirm-production-write {expected_confirmation}"
        )
    if args.classification_only:
        result = update_event_classification(frame, database_url)
        mode = "classification-update"
    else:
        result = import_events(frame, database_url, args.batch_size)
        mode = "import"
    print(json.dumps({"mode": mode, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
