"""Record and validate the News Quality V3 manual empty-asset decisions.

This is intentionally conservative for the reviewed package. The 226 apparent
BTC matches come only from synthetic SEC issuer-relevance metadata (and semantic
outputs derived from that same text), not verified filing text. The two apparent
SOL matches are geographic references to Solana Beach. None satisfies the direct
source-evidence rule, so all remain unassigned.
"""

from __future__ import annotations

import argparse
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REVIEW_PATH = ROOT / "reports" / "USER_REVIEW_PACKAGE" / "empty_assets.csv"
REPORT_PATH = ROOT / "reports" / "MANUAL_ASSET_REVIEW_V3.json"
EXPECTED_ROWS = 228
FALSE_SOL_IDS = {
    "evt18-13c6d2ac71aedd092210",
    "evt18-7d4631c9d48bac72c469",
}
DECISION_COLUMNS = (
    "user_decision",
    "decision_related_assets",
    "decision_reason",
    "decision_confidence",
    "reviewed_at",
)


def parse_evidence(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    parsed = ast.literal_eval(str(value))
    if not isinstance(parsed, list):
        raise ValueError(f"Expected evidence list, received {type(parsed).__name__}")
    return [str(item).upper() for item in parsed]


def validate_review(frame: pd.DataFrame) -> dict[str, object]:
    if len(frame) != EXPECTED_ROWS or frame.event_id.nunique() != EXPECTED_ROWS:
        raise ValueError("Manual asset package identity is not the reviewed 228-row set")
    missing_columns = sorted(set(DECISION_COLUMNS) - set(frame.columns))
    if missing_columns:
        raise ValueError(f"Manual decision columns are missing: {missing_columns}")
    undecided = frame.user_decision.fillna("").astype(str).str.strip().eq("")
    if undecided.any():
        raise ValueError(f"Manual asset review has {int(undecided.sum())} undecided rows")

    allowed_decisions = {"KEEP_EMPTY"}
    if not set(frame.user_decision) <= allowed_decisions:
        raise ValueError("Unsupported manual asset decision")
    if not frame.decision_confidence.isin(["high"]).all():
        raise ValueError("Every reviewed decision must have explicit high confidence")
    if frame.decision_reason.fillna("").astype(str).str.strip().eq("").any():
        raise ValueError("Every reviewed decision must have an evidence reason")

    false_sol = frame.event_id.isin(FALSE_SOL_IDS)
    if set(frame.loc[false_sol, "user_decision"]) != {"KEEP_EMPTY"}:
        raise ValueError("Solana Beach false positives must remain unassigned")
    if not frame.loc[false_sol, "decision_related_assets"].eq("[]").all():
        raise ValueError("Solana Beach decisions must preserve an empty asset list")

    metadata_btc = ~false_sol
    if not frame.user_decision.eq("KEEP_EMPTY").all():
        raise ValueError("Metadata-only asset cues must remain unassigned")
    if not frame.decision_related_assets.eq("[]").all():
        raise ValueError("Conservative manual decisions must preserve empty asset lists")
    if not frame.loc[metadata_btc, "body_evidence"].map(parse_evidence).map(lambda value: value == ["BTC"]).all():
        raise ValueError("The reviewed synthetic BTC metadata evidence set changed")
    if not frame.source.eq("sec").all() or not frame.title_evidence.map(parse_evidence).map(lambda value: value == []).all():
        raise ValueError("The reviewed source/title evidence package changed")

    semantic = pd.read_parquet(
        ROOT / "data/stage18b/canonical_inventory.parquet",
        columns=["canonical_event_id", "asset", "sem_directness"],
    )
    semantic = semantic[semantic.canonical_event_id.isin(frame.event_id)].drop_duplicates(
        "canonical_event_id"
    ).set_index("canonical_event_id")
    if set(semantic.index) != set(frame.event_id):
        raise ValueError("Semantic evidence is incomplete for the manual review package")
    metadata_btc_ids = set(frame.loc[metadata_btc, "event_id"])
    if not semantic.loc[sorted(metadata_btc_ids), "asset"].eq("BTC").all():
        raise ValueError("The semantic output derived from synthetic BTC metadata changed")
    if not semantic.loc[sorted(metadata_btc_ids), "sem_directness"].eq("direct").all():
        raise ValueError("The semantic directness output derived from metadata changed")
    if semantic.loc[sorted(FALSE_SOL_IDS), "sem_directness"].notna().any():
        raise ValueError("A Solana Beach false positive unexpectedly has direct semantic evidence")

    return {
        "status": "PASS",
        "rows": len(frame),
        "completed": int((~undecided).sum()),
        "remaining": int(undecided.sum()),
        "assign_btc": 0,
        "keep_empty": int(frame.user_decision.eq("KEEP_EMPTY").sum()),
        "false_sol_geographic_matches": len(FALSE_SOL_IDS),
        "metadata_only_btc_matches_rejected": len(metadata_btc_ids),
        "production_updated": False,
    }


def complete_review(path: Path = REVIEW_PATH) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if len(frame) != EXPECTED_ROWS or frame.event_id.nunique() != EXPECTED_ROWS:
        raise ValueError("Refusing to edit an unexpected manual-review package")
    if set(frame.loc[frame.event_id.isin(FALSE_SOL_IDS), "body_evidence"]) != {"['SOL']"}:
        raise ValueError("The reviewed Solana Beach evidence set changed")
    metadata_btc = ~frame.event_id.isin(FALSE_SOL_IDS)
    if not frame.loc[metadata_btc, "body_evidence"].map(parse_evidence).map(lambda value: value == ["BTC"]).all():
        raise ValueError("The reviewed Bitcoin evidence set changed")

    reviewed_at = datetime.now(timezone.utc).isoformat()
    frame["user_decision"] = "KEEP_EMPTY"
    frame["decision_related_assets"] = "[]"
    frame["decision_reason"] = (
        "BTC cue exists only in synthetic SEC issuer metadata; title and verified filing text provide no direct evidence."
    )
    frame["decision_confidence"] = "high"
    frame["reviewed_at"] = reviewed_at

    false_sol = frame.event_id.isin(FALSE_SOL_IDS)
    frame.loc[false_sol, "user_decision"] = "KEEP_EMPTY"
    frame.loc[false_sol, "decision_related_assets"] = "[]"
    frame.loc[false_sol, "decision_reason"] = (
        "Geographic Solana Beach reference; no Solana blockchain or uppercase SOL evidence."
    )
    result = validate_review(frame)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    REPORT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--complete", action="store_true", help="Write the reviewed decisions")
    args = parser.parse_args()
    frame = complete_review() if args.complete else pd.read_csv(REVIEW_PATH)
    result = validate_review(frame)
    REPORT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
