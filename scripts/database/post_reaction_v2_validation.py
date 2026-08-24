"""Compare a deterministic 100-event production sample with the final V2 artifact."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv

from scripts.database.reaction_v2_cutover import (
    ASSETS, EXPECTED_PROJECT_REF, EXPECTED_ROWS, FINAL, HORIZONS,
    normalize_database_url, wide_stage,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "reports/REACTION_V2_POST_CUTOVER_DB_VALIDATION.json"


def normalized(value):
    if value is None or value is pd.NA or value is pd.NaT or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, str) and value.startswith("{"):
        return json.dumps(json.loads(value), sort_keys=True)
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    return value


def main() -> int:
    load_dotenv(ROOT / ".env")
    database_url = normalize_database_url(os.getenv("DATABASE_URL", ""))
    parsed = urlparse(database_url)
    if EXPECTED_PROJECT_REF not in f"{parsed.hostname or ''} {parsed.username or ''}":
        raise RuntimeError("DATABASE_URL does not identify expected Supabase project")
    stage = wide_stage().sample(n=100, random_state=8).sort_values("event_id")
    columns = list(stage.columns)
    placeholders = ",".join(["%s"] * len(stage))
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*),count(DISTINCT event_id),count(DISTINCT slug) FROM public.events")
            totals = tuple(map(int, cursor.fetchone()))
            cursor.execute(
                f"SELECT {', '.join(columns)} FROM public.events WHERE event_id IN ({placeholders}) ORDER BY event_id",
                stage.event_id.tolist(),
            )
            live = pd.DataFrame(cursor.fetchall(), columns=columns)
    finally:
        connection.close()
    mismatches = []
    expected = stage.set_index("event_id")
    actual = live.set_index("event_id")
    for event_id in expected.index:
        for column in columns[1:]:
            left, right = normalized(expected.at[event_id, column]), normalized(actual.at[event_id, column])
            if isinstance(left, float) and isinstance(right, float):
                equal = bool(np.isclose(left, right, rtol=0, atol=1e-12))
            else:
                equal = left == right
            if not equal:
                mismatches.append({"event_id": event_id, "field": column})
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_events": totals[0], "unique_event_ids": totals[1], "unique_slugs": totals[2],
        "random_events_checked": len(stage), "reaction_fields_checked": len(stage) * (len(columns) - 1),
        "mismatches": len(mismatches), "status": "PASS" if totals == (EXPECTED_ROWS,) * 3 and not mismatches else "FAIL",
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
