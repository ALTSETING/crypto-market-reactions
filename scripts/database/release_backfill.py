"""Manifest-driven insert-new-only release preflight and transactional import."""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2

from scripts.database.release_contract import (
    PROTECTED_OLD_COLUMNS,
    RELEASE_COLUMNS,
    canonical_value,
    load_manifest,
    validate_manifest,
)


class ReleasePreflightError(RuntimeError):
    """Raised before writes when target state is incompatible with the release."""


REACTION_VALUE_COLUMNS = {
    f"{asset}_{horizon}"
    for asset in ("btc", "eth", "sol")
    for horizon in ("1m", "5m", "15m", "1h", "4h", "24h")
}


def normalize_database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("postgresql+psycopg2://"):
        return "postgresql://" + value.removeprefix("postgresql+psycopg2://")
    if value.startswith("postgres://"):
        return "postgresql://" + value.removeprefix("postgres://")
    return value


def verify_target_project(database_url: str, expected_project_ref: str) -> None:
    parsed = urlparse(normalize_database_url(database_url))
    identity = f"{parsed.hostname or ''} {parsed.username or ''}"
    if expected_project_ref not in identity:
        raise ReleasePreflightError("DATABASE_URL does not identify the manifest target project")


def copy_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return r"\N"
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return r"\N"
    if isinstance(value, pd.Timestamp):
        return r"\N" if pd.isna(value) else value.isoformat()
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, list):
        return "{" + ",".join(str(item) for item in value) + "}"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def copy_buffer(frame: pd.DataFrame) -> io.StringIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in frame.itertuples(index=False, name=None):
        writer.writerow([copy_value(value) for value in row])
    buffer.seek(0)
    return buffer


def values_equal(left: Any, right: Any, *, reaction_float: bool = False) -> bool:
    if reaction_float:
        left_value = canonical_value(left)
        right_value = canonical_value(right)
        if left_value is None or right_value is None:
            return left_value is right_value
        return math.isclose(
            float(left_value), float(right_value), rel_tol=1e-12, abs_tol=1e-12
        )
    return canonical_value(left) == canonical_value(right)


def table_columns(cursor: Any) -> set[str]:
    cursor.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='events'
        """
    )
    return {row[0] for row in cursor.fetchall()}


def _fetch_frame(cursor: Any, columns: list[str]) -> pd.DataFrame:
    cursor.execute(
        "SELECT " + ",".join(f'"{column}"' for column in columns)
        + " FROM public.events ORDER BY event_id"
    )
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def validate_identity_sets(live_set: set[str], old_set: set[str], new_set: set[str]) -> str:
    if old_set & new_set:
        raise ReleasePreflightError("New identity set intersects protected old IDs")
    all_set = old_set | new_set
    unexpected = live_set - all_set
    missing_old = old_set - live_set
    present_new = live_set & new_set
    if unexpected or missing_old:
        raise ReleasePreflightError(
            f"Live identity mismatch: missing_old={len(missing_old)}, unexpected={len(unexpected)}"
        )
    if present_new and present_new != new_set:
        raise ReleasePreflightError(f"Partial backfill detected: {len(present_new)}/{len(new_set)} new IDs")
    if live_set == old_set:
        return "ready_to_insert"
    if live_set == all_set:
        return "already_applied"
    raise ReleasePreflightError("Live identity is neither pre-import nor fully imported")


def preflight_cursor(
    cursor: Any,
    release: pd.DataFrame,
    manifest: dict[str, Any],
    *,
    require_insert_schema: bool = True,
) -> dict[str, Any]:
    identity = manifest["identity"]
    ids_path = Path(manifest["_manifest_path"]).parent / manifest["new_ids"]["path"]
    new_ids = ids_path.read_text(encoding="utf-8").splitlines()
    new_set = set(new_ids)
    all_set = set(release.event_id)
    old_set = all_set - new_set

    existing_columns = table_columns(cursor)
    missing_columns = sorted(set(RELEASE_COLUMNS) - existing_columns)
    if require_insert_schema and missing_columns:
        raise ReleasePreflightError(f"Target table is missing release columns: {missing_columns}")
    compare_columns = [column for column in PROTECTED_OLD_COLUMNS if column in existing_columns]
    if compare_columns != PROTECTED_OLD_COLUMNS:
        raise ReleasePreflightError("Target table is missing protected production columns")
    live = _fetch_frame(cursor, compare_columns)
    live_set = set(live.event_id)
    present_new = live_set & new_set
    mode = validate_identity_sets(live_set, old_set, new_set)

    candidate_old = release[release.event_id.isin(old_set)][compare_columns].sort_values("event_id")
    live_old = live[live.event_id.isin(old_set)].sort_values("event_id")
    mismatches: dict[str, int] = {}
    for column in compare_columns:
        changed = sum(
            not values_equal(left, right, reaction_float=column in REACTION_VALUE_COLUMNS)
            for left, right in zip(candidate_old[column], live_old[column])
        )
        if changed:
            mismatches[column] = changed
    if mismatches:
        raise ReleasePreflightError(f"Protected old rows differ from release candidate: {mismatches}")

    already_applied = mode == "already_applied"
    if already_applied:
        # Repeated preflight is idempotent only when all protected fields for the
        # inserted rows still equal the release candidate.
        candidate_new = release[release.event_id.isin(new_set)][compare_columns].sort_values("event_id")
        live_new = live[live.event_id.isin(new_set)].sort_values("event_id")
        new_mismatch = {}
        for column in compare_columns:
            changed = sum(
                not values_equal(left, right, reaction_float=column in REACTION_VALUE_COLUMNS)
                for left, right in zip(candidate_new[column], live_new[column])
            )
            if changed:
                new_mismatch[column] = changed
        if new_mismatch:
            raise ReleasePreflightError(f"Existing new IDs conflict with release: {new_mismatch}")

    return {
        "status": "PASS",
        "mode": "already_applied" if already_applied else "ready_to_insert",
        "live_rows": len(live),
        "expected_old_rows": identity["old_rows"],
        "expected_new_rows": identity["new_rows"],
        "present_new_rows": len(present_new),
        "missing_old_ids": 0,
        "unexpected_ids": 0,
        "protected_old_mismatches": {},
        "target_schema_missing_columns": missing_columns,
        "production_updated": False,
    }


def preflight_database(
    database_url: str,
    manifest_path: Path,
    *,
    require_insert_schema: bool = True,
) -> dict[str, Any]:
    release, manifest, _ = validate_manifest(manifest_path)
    manifest["_manifest_path"] = str(manifest_path.resolve())
    verify_target_project(database_url, manifest["expected_project_ref"])
    connection = psycopg2.connect(normalize_database_url(database_url))
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            result = preflight_cursor(
                cursor, release, manifest, require_insert_schema=require_insert_schema
            )
        connection.rollback()
        return result
    finally:
        connection.close()


def insert_new_events(
    database_url: str,
    manifest_path: Path,
    confirmation: str,
) -> dict[str, Any]:
    release, manifest, _ = validate_manifest(manifest_path)
    manifest["_manifest_path"] = str(manifest_path.resolve())
    expected_confirmation = f"INSERT-{manifest['identity']['new_rows']}-NEW-EVENTS"
    if confirmation != expected_confirmation:
        raise ReleasePreflightError(
            f"Production write requires --confirm-production-write {expected_confirmation}"
        )
    verify_target_project(database_url, manifest["expected_project_ref"])
    ids_path = manifest_path.parent / manifest["new_ids"]["path"]
    new_ids = set(ids_path.read_text(encoding="utf-8").splitlines())
    new_rows = release[release.event_id.isin(new_ids)][RELEASE_COLUMNS]
    columns_sql = ",".join(f'"{column}"' for column in RELEASE_COLUMNS)

    connection = psycopg2.connect(normalize_database_url(database_url))
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("LOCK TABLE public.events IN SHARE ROW EXCLUSIVE MODE")
                preflight = preflight_cursor(cursor, release, manifest)
                if preflight["mode"] == "already_applied":
                    return {**preflight, "inserted_rows": 0, "production_updated": False}
                cursor.execute(
                    "CREATE TEMP TABLE events_release_import "
                    "(LIKE public.events INCLUDING DEFAULTS) ON COMMIT DROP"
                )
                cursor.copy_expert(
                    f"COPY pg_temp.events_release_import ({columns_sql}) "
                    "FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
                    copy_buffer(new_rows),
                )
                cursor.execute(
                    f"INSERT INTO public.events ({columns_sql}) "
                    f"SELECT {columns_sql} FROM pg_temp.events_release_import"
                )
                inserted = int(cursor.rowcount)
                if inserted != manifest["identity"]["new_rows"]:
                    raise ReleasePreflightError(
                        f"Inserted {inserted} rows, expected {manifest['identity']['new_rows']}"
                    )
                cursor.execute(
                    "SELECT count(*), count(DISTINCT event_id), count(DISTINCT slug) "
                    "FROM public.events"
                )
                final_rows, final_unique_ids, final_unique_slugs = map(int, cursor.fetchone())
                expected_total = manifest["identity"]["total_rows"]
                if (final_rows, final_unique_ids, final_unique_slugs) != (
                    expected_total, expected_total, expected_total
                ):
                    raise ReleasePreflightError(
                        "Pre-commit final row/ID/slug identity validation failed"
                    )
                cursor.execute("SELECT event_id FROM public.events ORDER BY event_id")
                final_ids = [row[0] for row in cursor.fetchall()]
                if final_ids != sorted(release.event_id.tolist()):
                    raise ReleasePreflightError("Final identity set differs from release manifest")
                cursor.execute(
                    "SELECT count(*) FROM public.events WHERE event_id = ANY(%s)",
                    (sorted(new_ids),),
                )
                present_new_rows = int(cursor.fetchone()[0])
                if present_new_rows != manifest["identity"]["new_rows"]:
                    raise ReleasePreflightError(
                        "Pre-commit new-ID presence validation failed"
                    )
                post_insert = preflight_cursor(cursor, release, manifest)
                if (
                    post_insert["mode"] != "already_applied"
                    or post_insert["missing_old_ids"] != 0
                    or post_insert["unexpected_ids"] != 0
                    or post_insert["protected_old_mismatches"]
                ):
                    raise ReleasePreflightError(
                        f"Pre-commit protected identity validation failed: {post_insert}"
                    )
        return {
            "status": "PASS",
            "mode": "insert_new_only",
            "inserted_rows": inserted,
            "final_rows": final_rows,
            "final_unique_event_ids": final_unique_ids,
            "final_unique_slugs": final_unique_slugs,
            "present_new_rows": present_new_rows,
            "missing_old_ids": post_insert["missing_old_ids"],
            "unexpected_ids": post_insert["unexpected_ids"],
            "protected_old_mismatches": post_insert["protected_old_mismatches"],
            "reaction_v2_mismatches": 0,
            "precommit_validation": "PASS",
            "production_updated": True,
        }
    finally:
        connection.close()
