"""Check formatted live event-page reactions against the final V2 artifact."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from scripts.database.reaction_v2_cutover import ASSETS, HORIZONS, ROOT, wide_stage


BASE_URL = "https://crypto-market-reactions-nu.vercel.app"
BACKUP = ROOT / "data/website/backups/pre_reaction_v2_cutover/supabase_events_v1.parquet"
OUTPUT = ROOT / "reports/REACTION_V2_30_EVENT_PAGE_CHECK.json"


def format_reaction(value: float) -> str:
    if value > 0:
        return f"+{value:.2f}%"
    return f"{value:.2f}%"


def main() -> int:
    stage = wide_stage()
    metadata = pd.read_parquet(BACKUP, columns=["event_id", "slug", "related_assets"])
    frame = stage.merge(metadata, on="event_id", validate="one_to_one")
    reaction_columns = [f"{asset}_{h}" for asset in ASSETS for h in HORIZONS]
    frame["peak"] = frame[reaction_columns].abs().max(axis=1)
    frame["missing"] = frame[reaction_columns].isna().any(axis=1)
    frame["sol_related"] = frame.related_assets.map(lambda value: "SOL" in list(value) if value is not None else False)
    frame["multi_asset"] = frame.related_assets.map(lambda value: len(list(value)) > 1 if value is not None else False)
    chosen = []
    for subset in (
        frame.nlargest(5, "peak"), frame.nsmallest(5, "peak"),
        frame[frame.sol_related].sample(5, random_state=81),
        frame[frame.multi_asset].sample(5, random_state=82),
        frame[frame.missing].sample(5, random_state=83),
        frame.sample(30, random_state=84),
    ):
        for event_id in subset.event_id:
            if event_id not in chosen:
                chosen.append(event_id)
            if len(chosen) == 30:
                break
        if len(chosen) == 30:
            break

    failures, cells_checked, semantic_split_pages = [], 0, 0
    for event_id in chosen:
        row = frame.loc[frame.event_id.eq(event_id)].iloc[0]
        response = requests.get(f"{BASE_URL}/events/{row.slug}", timeout=30)
        body = html.unescape(re.sub(r"<[^>]+>", " ", response.text))
        if "Related asset reactions" in body or "Broader market context" in body:
            semantic_split_pages += 1
        if response.status_code != 200:
            failures.append({"event_id": event_id, "reason": f"HTTP {response.status_code}"})
            continue
        checked_for_page = 0
        for column in reaction_columns:
            value = row[column]
            if pd.isna(value):
                continue
            cells_checked += 1
            checked_for_page += 1
            expected = format_reaction(float(value))
            if expected not in body:
                failures.append({"event_id": event_id, "field": column, "expected": expected})
            if checked_for_page == 6:
                break
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(), "event_pages_checked": len(chosen),
        "displayed_reaction_cells_checked": cells_checked, "display_mismatches": len(failures),
        "semantic_split_pages": semantic_split_pages,
        "failure_details": failures,
        "status": "PASS" if len(chosen) == 30 and not failures else "FAIL",
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
