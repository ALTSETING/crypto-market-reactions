"""Shared manifest and schema contract for the 9,073-event release candidate."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = ROOT / "data" / "website" / "release_candidates" / "news_quality_v3"
DEFAULT_RELEASE_DATASET = RELEASE_DIR / "events_release_candidate.parquet"
DEFAULT_RELEASE_MANIFEST = RELEASE_DIR / "events_release_manifest.json"
DEFAULT_NEW_IDS = RELEASE_DIR / "new_event_ids.txt"
BUILDER_VERSION = "news-quality-v3-release-v1"
MANIFEST_VERSION = 1
ASSETS = {"BTC", "ETH", "SOL"}
HORIZONS = ("1m", "5m", "15m", "1h", "4h", "24h")

CORE_COLUMNS = [
    "event_id", "slug", "title", "published_at", "source", "source_url",
    "primary_asset", "related_assets", "category", "sentiment",
    "sentiment_score", "importance", "ai_schema_version", "ai_prompt_version",
    "ai_original_scale", "archive_dataset_source", "archive_member_id",
    "reaction_methodology", "reaction_value_unit",
]

METADATA_COLUMNS = [
    "record_type", "story_id", "captured_title", "current_source_title",
    "display_title", "source_type", "source_name", "capture_method",
    "publication_time_source", "publication_time_confidence",
    "publication_time_verified_at", "event_at", "event_time_source",
    "event_time_confidence", "primary_asset_confidence", "source_http_status",
    "source_final_url", "source_verified_at", "quality_status", "is_public",
    "dataset_version", "dataset_release",
]

REACTION_COLUMNS: list[str] = []
PROTECTED_REACTION_COLUMNS: list[str] = []
for _asset in ("btc", "eth", "sol"):
    _values = [f"{_asset}_{horizon}" for horizon in HORIZONS]
    REACTION_COLUMNS.extend(
        [
            *_values,
            f"{_asset}_reference_time",
            f"{_asset}_reference_latency_minutes",
            f"{_asset}_reaction_quality",
            f"{_asset}_reaction_source",
            f"{_asset}_reaction_missing_reason",
        ]
    )
    PROTECTED_REACTION_COLUMNS.extend(
        [
            *_values,
            f"{_asset}_reaction_source",
            f"{_asset}_reference_time",
            f"{_asset}_reference_latency_minutes",
            f"{_asset}_reaction_quality",
        ]
    )

RELEASE_COLUMNS = [*CORE_COLUMNS, *METADATA_COLUMNS, *REACTION_COLUMNS]
PROTECTED_OLD_COLUMNS = [*CORE_COLUMNS, *PROTECTED_REACTION_COLUMNS]
assert len(PROTECTED_OLD_COLUMNS) == 49

REQUIRED_NON_NULL = {
    "event_id", "slug", "title", "published_at", "source", "source_url",
    "related_assets", "category", "ai_schema_version", "ai_original_scale",
    "archive_dataset_source", "archive_member_id", "reaction_methodology",
    "reaction_value_unit", "record_type", "quality_status", "is_public",
    "dataset_version", "dataset_release",
}


class ReleaseValidationError(ValueError):
    """Raised when a release artifact or manifest violates the frozen contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_lines(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def parse_assets(value: Any) -> list[str]:
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        assets = [str(item).upper() for item in value]
    elif value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        assets = []
    else:
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError as exc:
            raise ReleaseValidationError(f"Invalid related_assets JSON: {value!r}") from exc
        if not isinstance(parsed, list):
            raise ReleaseValidationError("related_assets must be an array")
        assets = [str(item).upper() for item in parsed]
    if len(assets) != len(set(assets)) or not set(assets) <= ASSETS:
        raise ReleaseValidationError(f"Invalid related_assets values: {assets!r}")
    return assets


def canonical_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, np.ndarray):
        return [canonical_value(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, pd.Timestamp):
        return value.isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return canonical_value(value.item())
    return value


def content_sha256(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    ordered = frame.sort_values("event_id").reset_index(drop=True)
    for record in ordered[RELEASE_COLUMNS].to_dict("records"):
        payload = json.dumps(
            {key: canonical_value(record[key]) for key in RELEASE_COLUMNS},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest.update(payload.encode("utf-8") + b"\n")
    return digest.hexdigest()


def normalize_release_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(RELEASE_COLUMNS) - set(frame.columns))
    if missing:
        raise ReleaseValidationError(f"Release dataset columns are missing: {missing}")
    frame = frame[RELEASE_COLUMNS].copy()
    frame["related_assets"] = frame.related_assets.map(parse_assets)
    for column in ("published_at", "publication_time_verified_at", "event_at", "source_verified_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    for asset in ("btc", "eth", "sol"):
        column = f"{asset}_reference_time"
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
        reason = f"{asset}_reaction_missing_reason"
        frame[reason] = frame[reason].map(
            lambda value: None
            if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value))
            else json.dumps(canonical_value(value), sort_keys=True, separators=(",", ":"))
            if not isinstance(value, str)
            else value
        )
    return frame.sort_values("event_id").reset_index(drop=True)


def validate_release_frame(frame: pd.DataFrame) -> dict[str, Any]:
    if list(frame.columns) != RELEASE_COLUMNS:
        raise ReleaseValidationError("Release dataset has an unexpected schema or column order")
    if frame.event_id.duplicated().any() or frame.slug.duplicated().any() or frame.source_url.duplicated().any():
        raise ReleaseValidationError("Release identity, slug, or source URL is not unique")
    for column in REQUIRED_NON_NULL:
        if frame[column].isna().any():
            raise ReleaseValidationError(f"Required release column contains NULL: {column}")
    for column in ("event_id", "slug", "title", "source", "source_url", "category"):
        if frame[column].astype(str).str.strip().eq("").any():
            raise ReleaseValidationError(f"Required release column is empty: {column}")
    invalid_primary = frame.primary_asset.notna() & ~frame.primary_asset.isin(ASSETS)
    if invalid_primary.any():
        raise ReleaseValidationError("Unsupported primary_asset in release dataset")
    if frame.reaction_value_unit.ne("percent").any():
        raise ReleaseValidationError("Reaction units must be percent")
    if not frame.archive_dataset_source.isin(["A", "B", "C"]).all():
        raise ReleaseValidationError("Unexpected archive dataset source")

    reaction_values = [f"{asset}_{horizon}" for asset in ("btc", "eth", "sol") for horizon in HORIZONS]
    numeric = frame[reaction_values].to_numpy(dtype=float)
    if np.isinf(numeric).any():
        raise ReleaseValidationError("Infinite reaction value detected")
    finite = numeric[np.isfinite(numeric)]
    if (finite <= -100).any():
        raise ReleaseValidationError("Impossible reaction value at or below -100%")

    published = pd.to_datetime(frame.published_at, utc=True)
    return {
        "rows": len(frame),
        "unique_event_ids": int(frame.event_id.nunique()),
        "unique_slugs": int(frame.slug.nunique()),
        "unique_source_urls": int(frame.source_url.nunique()),
        "min_published_at": published.min().isoformat(),
        "max_published_at": published.max().isoformat(),
        "null_reaction_cells": int(frame[reaction_values].isna().sum().sum()),
        "events_without_reactions": int(frame[reaction_values].isna().all(axis=1).sum()),
        "empty_related_assets": int(frame.related_assets.map(len).eq(0).sum()),
    }


def load_manifest(path: Path = DEFAULT_RELEASE_MANIFEST) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseValidationError(f"Cannot read release manifest: {path}") from exc
    required = {
        "manifest_version", "builder_version", "dataset", "new_ids", "identity",
        "schema", "source_artifacts", "expected_project_ref",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ReleaseValidationError(f"Manifest fields are missing: {missing}")
    if manifest["manifest_version"] != MANIFEST_VERSION:
        raise ReleaseValidationError("Unsupported release manifest version")
    return manifest


def validate_manifest(
    manifest_path: Path = DEFAULT_RELEASE_MANIFEST,
    dataset_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    manifest = load_manifest(manifest_path)
    dataset = dataset_path or (manifest_path.parent / manifest["dataset"]["path"])
    ids_path = manifest_path.parent / manifest["new_ids"]["path"]
    if sha256_file(dataset) != manifest["dataset"]["sha256"]:
        raise ReleaseValidationError("Release dataset SHA-256 does not match manifest")
    if sha256_file(ids_path) != manifest["new_ids"]["sha256"]:
        raise ReleaseValidationError("New-ID manifest SHA-256 does not match")

    frame = normalize_release_frame(pd.read_parquet(dataset))
    stats = validate_release_frame(frame)
    identity = manifest["identity"]
    if stats["rows"] != identity["total_rows"]:
        raise ReleaseValidationError("Manifest-derived row count does not match dataset")
    new_ids = ids_path.read_text(encoding="utf-8").splitlines()
    if new_ids != sorted(new_ids) or len(new_ids) != len(set(new_ids)):
        raise ReleaseValidationError("New-ID manifest must be sorted and unique")
    if sha256_lines(new_ids) != identity["new_ids_sha256"]:
        raise ReleaseValidationError("New identity hash does not match manifest")
    actual_ids = set(frame.event_id)
    new_set = set(new_ids)
    if not new_set <= actual_ids or len(new_ids) != identity["new_rows"]:
        raise ReleaseValidationError("New identity set is incomplete or extra")
    old_ids = sorted(actual_ids - new_set)
    if len(old_ids) != identity["old_rows"] or sha256_lines(old_ids) != identity["old_ids_sha256"]:
        raise ReleaseValidationError("Old identity set does not match manifest")
    if content_sha256(frame) != manifest["dataset"]["content_sha256"]:
        raise ReleaseValidationError("Canonical release content hash does not match manifest")

    parquet_schema = [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in pq.ParquetFile(dataset).schema_arrow
    ]
    if parquet_schema != manifest["schema"]["arrow_fields"]:
        raise ReleaseValidationError("Arrow schema does not match manifest")
    return frame, manifest, {**stats, "old_rows": len(old_ids), "new_rows": len(new_ids)}
