"""Delete exactly the manifest's new IDs and preserve every protected old ID."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.database.release_backfill import (  # noqa: E402
    ReleasePreflightError,
    normalize_database_url,
    verify_target_project,
)
from scripts.database.release_contract import (  # noqa: E402
    DEFAULT_RELEASE_MANIFEST,
    validate_manifest,
)


def validate_rollback_identity_sets(live_ids: set[str], old_ids: set[str], new_ids: set[str]) -> str:
    if old_ids & new_ids:
        raise ReleasePreflightError("Rollback new-ID manifest intersects protected old IDs")
    all_ids = old_ids | new_ids
    missing_old = old_ids - live_ids
    unexpected = live_ids - all_ids
    present_new = live_ids & new_ids
    if missing_old or unexpected:
        raise ReleasePreflightError(
            f"Rollback identity mismatch: missing_old={len(missing_old)}, unexpected={len(unexpected)}"
        )
    if present_new and present_new != new_ids:
        raise ReleasePreflightError(f"Partial new-ID set present: {len(present_new)}/{len(new_ids)}")
    if live_ids == all_ids:
        return "ready_to_delete"
    if live_ids == old_ids:
        return "already_rolled_back"
    raise ReleasePreflightError("Rollback target is neither full release nor old-only state")


def rollback_preflight_cursor(cursor, release, manifest):
    ids_path = Path(manifest["_manifest_path"]).parent / manifest["new_ids"]["path"]
    new_ids = set(ids_path.read_text(encoding="utf-8").splitlines())
    old_ids = set(release.event_id) - new_ids
    cursor.execute("SELECT event_id FROM public.events")
    live_ids = {row[0] for row in cursor.fetchall()}
    present_new = live_ids & new_ids
    mode = validate_rollback_identity_sets(live_ids, old_ids, new_ids)
    return {
        "status": "PASS",
        "mode": mode,
        "live_rows": len(live_ids),
        "protected_old_rows": len(old_ids),
        "rows_to_delete": len(present_new),
        "old_ids_at_risk": 0,
        "production_updated": False,
    }


def rollback_database(database_url: str, manifest_path: Path, confirmation: str | None = None):
    release, manifest, _ = validate_manifest(manifest_path)
    manifest["_manifest_path"] = str(manifest_path.resolve())
    verify_target_project(database_url, manifest["expected_project_ref"])
    connection = psycopg2.connect(normalize_database_url(database_url))
    try:
        if confirmation is None:
            connection.set_session(readonly=True, autocommit=False)
            with connection.cursor() as cursor:
                result = rollback_preflight_cursor(cursor, release, manifest)
            connection.rollback()
            return result
        expected = f"DELETE-{manifest['identity']['new_rows']}-BACKFILL-EVENTS"
        if confirmation != expected:
            raise ReleasePreflightError(f"Rollback requires --confirm-production-write {expected}")
        ids_path = manifest_path.parent / manifest["new_ids"]["path"]
        new_ids = ids_path.read_text(encoding="utf-8").splitlines()
        old_ids = set(release.event_id) - set(new_ids)
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("LOCK TABLE public.events IN SHARE ROW EXCLUSIVE MODE")
                preflight = rollback_preflight_cursor(cursor, release, manifest)
                if preflight["mode"] == "already_rolled_back":
                    return {**preflight, "deleted_rows": 0}
                cursor.execute(
                    "DELETE FROM public.events WHERE event_id = ANY(%s) RETURNING event_id",
                    (new_ids,),
                )
                deleted = {row[0] for row in cursor.fetchall()}
                if deleted != set(new_ids):
                    raise ReleasePreflightError("Rollback did not delete exactly the new manifest IDs")
                cursor.execute("SELECT event_id FROM public.events")
                remaining = {row[0] for row in cursor.fetchall()}
                if remaining != old_ids:
                    raise ReleasePreflightError("Rollback final identity is not the protected old set")
        return {
            "status": "PASS", "mode": "rollback", "deleted_rows": len(deleted),
            "final_rows": len(remaining), "production_updated": True,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--confirm-production-write")
    args = parser.parse_args()
    if not (args.dry_run or args.preflight or args.confirm_production_write):
        parser.error("choose --dry-run, --preflight, or explicit --confirm-production-write")
    load_dotenv(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if args.dry_run:
        _, manifest, stats = validate_manifest(args.manifest)
        result = {
            "status": "PASS", "mode": "dry-run", "rows_to_delete": stats["new_rows"],
            "protected_old_rows": stats["old_rows"], "new_ids_sha256": manifest["identity"]["new_ids_sha256"],
            "production_updated": False,
        }
    else:
        if not database_url:
            raise RuntimeError("DATABASE_URL is required")
        result = rollback_database(database_url, args.manifest, args.confirm_production_write)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
