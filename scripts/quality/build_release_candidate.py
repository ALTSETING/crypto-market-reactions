"""Build the isolated deterministic 9,073-event News Quality V3 release candidate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.database.release_contract import (
    BUILDER_VERSION,
    DEFAULT_NEW_IDS,
    DEFAULT_RELEASE_DATASET,
    DEFAULT_RELEASE_MANIFEST,
    MANIFEST_VERSION,
    METADATA_COLUMNS,
    PROTECTED_OLD_COLUMNS,
    RELEASE_COLUMNS,
    content_sha256,
    normalize_release_frame,
    sha256_file,
    sha256_lines,
    validate_manifest,
    validate_release_frame,
)
from scripts.quality.complete_manual_asset_review import REVIEW_PATH, validate_review


OLD_SNAPSHOT = ROOT / "data/website/backups/pre_news_quality_v3/supabase_events_post_reaction_v2.parquet"
OLD_METADATA = ROOT / "data/backfill_v3/existing_metadata_staging.parquet"
NEW_STAGING = ROOT / "data/backfill_v3/production_rows_staging.parquet"
EXPECTED_PROJECT_REF = "ickflwksigaotygtdyko"


def normalized_equal(left: object, right: object) -> bool:
    from scripts.database.release_contract import canonical_value

    return canonical_value(left) == canonical_value(right)


def build_frame() -> tuple[pd.DataFrame, dict[str, int]]:
    validate_review(pd.read_csv(REVIEW_PATH))
    snapshot = pd.read_parquet(OLD_SNAPSHOT).sort_values("event_id").reset_index(drop=True)
    metadata = pd.read_parquet(OLD_METADATA).set_index("event_id")
    new = pd.read_parquet(NEW_STAGING).copy()
    if len(snapshot) != 7_878 or len(new) != 1_195:
        raise RuntimeError("Release source identity is not 7,878 old plus 1,195 new")
    if set(snapshot.event_id) & set(new.event_id):
        raise RuntimeError("New staging IDs overlap the protected old snapshot")

    old = snapshot.copy()
    for column in METADATA_COLUMNS:
        if column in metadata.columns:
            old[column] = old.event_id.map(metadata[column])
        elif column not in old.columns:
            old[column] = None
    # Core identity/classification/semantic and every Reaction V2 field remain from
    # the verified live snapshot. Manual asset decisions are an approval artifact;
    # this insert-new-only release deliberately does not update old production rows.
    old = old.reindex(columns=RELEASE_COLUMNS)
    new = new.reindex(columns=RELEASE_COLUMNS)
    release = normalize_release_frame(pd.concat([old, new], ignore_index=True, sort=False))
    validate_release_frame(release)

    protected = release[release.event_id.isin(snapshot.event_id)].sort_values("event_id")
    snapshot = snapshot.sort_values("event_id")
    mismatches: dict[str, int] = {}
    for column in PROTECTED_OLD_COLUMNS:
        changed = sum(
            not normalized_equal(left, right)
            for left, right in zip(protected[column], snapshot[column])
        )
        if changed:
            mismatches[column] = changed
    if mismatches:
        raise RuntimeError(f"Protected old production fields changed: {mismatches}")
    return release, mismatches


def source_hashes() -> dict[str, dict[str, object]]:
    result = {}
    for path in (OLD_SNAPSHOT, OLD_METADATA, NEW_STAGING, REVIEW_PATH):
        result[str(path.relative_to(ROOT)).replace("\\", "/")] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return result


def write_release(
    dataset_path: Path = DEFAULT_RELEASE_DATASET,
    manifest_path: Path = DEFAULT_RELEASE_MANIFEST,
    new_ids_path: Path = DEFAULT_NEW_IDS,
) -> dict[str, object]:
    release, mismatches = build_frame()
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    new_ids = sorted(pd.read_parquet(NEW_STAGING, columns=["event_id"]).event_id.tolist())
    old_ids = sorted(set(release.event_id) - set(new_ids))
    if len(new_ids) != 1_195 or len(old_ids) != 7_878:
        raise RuntimeError("Archive source split does not match the release identity contract")
    new_ids_path.write_text("\n".join(new_ids) + "\n", encoding="utf-8", newline="\n")

    table = pa.Table.from_pandas(release[RELEASE_COLUMNS], preserve_index=False)
    pq.write_table(table, dataset_path, compression="zstd", version="2.6", write_statistics=True)
    schema = [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in pq.ParquetFile(dataset_path).schema_arrow
    ]
    published = pd.to_datetime(release.published_at, utc=True)
    years = published.dt.year
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "builder_version": BUILDER_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_project_ref": EXPECTED_PROJECT_REF,
        "dataset": {
            "path": dataset_path.name,
            "bytes": dataset_path.stat().st_size,
            "sha256": sha256_file(dataset_path),
            "content_sha256": content_sha256(release),
        },
        "new_ids": {
            "path": new_ids_path.name,
            "bytes": new_ids_path.stat().st_size,
            "sha256": sha256_file(new_ids_path),
        },
        "identity": {
            "total_rows": len(release),
            "old_rows": len(old_ids),
            "new_rows": len(new_ids),
            "all_ids_sha256": sha256_lines(sorted(release.event_id.tolist())),
            "old_ids_sha256": sha256_lines(old_ids),
            "new_ids_sha256": sha256_lines(new_ids),
        },
        "coverage": {
            "min_published_at": published.min().isoformat(),
            "max_published_at": published.max().isoformat(),
            "events_2017_2022": int(years.between(2017, 2022).sum()),
            "events_2023_2026": int(years.between(2023, 2026).sum()),
        },
        "schema": {"columns": RELEASE_COLUMNS, "arrow_fields": schema},
        "protected_old_fields": {
            "columns": PROTECTED_OLD_COLUMNS,
            "column_count": len(PROTECTED_OLD_COLUMNS),
            "mismatches": mismatches,
        },
        "source_artifacts": source_hashes(),
        "production_updated": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _, _, stats = validate_manifest(manifest_path, dataset_path)
    print(json.dumps({**stats, **manifest["dataset"], "manifest": str(manifest_path)}, indent=2))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_RELEASE_DATASET)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument("--new-ids", type=Path, default=DEFAULT_NEW_IDS)
    args = parser.parse_args()
    write_release(args.dataset.resolve(), args.manifest.resolve(), args.new_ids.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
