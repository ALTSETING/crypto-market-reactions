"""Calculate and independently re-check Reaction V2 for V3 candidates."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from build_reactions_v2 import HORIZONS, archive_index, build, qa_sample


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/backfill_v3/historical_candidates_qa.parquet"
OUTPUT = ROOT / "data/backfill_v3/historical_candidate_reactions_v2.parquet"
MANIFEST = ROOT / "reports/stage16c_download_manifest.csv"
REPORTS = ROOT / "reports"


def main() -> int:
    candidates = pd.read_parquet(INPUT)
    accepted = candidates[candidates.quality_status.eq("accepted")].copy()
    accepted = accepted.rename(columns={"candidate_id": "event_id"})
    accepted["related_assets"] = accepted.related_assets.map(
        lambda values: json.dumps(list(values)) if not isinstance(values, str) else values
    )
    index, _ = archive_index(MANIFEST)
    reactions, problems, opens = build(accepted[["event_id", "published_at", "related_assets"]], index)
    reactions.to_parquet(OUTPUT, index=False)
    _, cells = qa_sample(reactions, opens)
    cells.to_csv(REPORTS / "HISTORICAL_CANDIDATE_REACTION_V2_QA.csv", index=False)
    coverage = reactions.groupby("asset").reaction_quality.value_counts().unstack(fill_value=0).to_dict("index")
    payload = {
        "candidate_events": len(accepted),
        "reaction_rows": len(reactions),
        "verified_raw_rows": int(reactions.reaction_quality.eq("verified_raw").sum()),
        "partial_rows": int(reactions.reaction_quality.eq("partial_verified_raw").sum()),
        "missing_rows": int(reactions.reaction_quality.eq("missing").sum()),
        "selected_candle_problems": len(problems),
        "independent_qa_cells": len(cells),
        "independent_qa_failures": int(cells.status.ne("pass").sum()),
        "qa_max_absolute_difference": float(cells.absolute_difference.max()) if len(cells) else None,
        "coverage": coverage,
        "methodology": "reaction_v2_next_full_minute_open_to_open",
        "horizons": HORIZONS,
    }
    (REPORTS / "HISTORICAL_CANDIDATE_REACTION_V2.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
