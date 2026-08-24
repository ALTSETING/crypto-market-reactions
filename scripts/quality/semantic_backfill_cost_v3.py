"""Estimate (but never execute) the paid semantic backfill for V3 gaps."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
MODEL = "gpt-5-mini"
INPUT_USD_PER_M = 0.25
OUTPUT_USD_PER_M = 2.00
BATCH_DISCOUNT = 0.50
MAX_BODY_CHARS = 10_000
PROMPT_TOKENS_PER_ROW = 300
OUTPUT_TOKENS_PER_ROW = 140


def main() -> int:
    gaps = pd.read_csv(REPORTS / "SEMANTIC_GAPS_V3.csv")
    inventory = pd.read_parquet(
        ROOT / "data/stage18b/canonical_inventory.parquet",
        columns=["canonical_event_id", "body"],
    )
    inventory["body"] = inventory.body.fillna("").astype(str)
    inventory = inventory.assign(body_chars=inventory.body.str.len()).sort_values("body_chars").drop_duplicates(
        "canonical_event_id", keep="last"
    )
    joined = gaps.merge(inventory, left_on="event_id", right_on="canonical_event_id", how="left", validate="one_to_one")
    joined = joined[["event_id", "title", "body"]]
    candidates = pd.read_parquet(ROOT / "data/backfill_v3/historical_candidates_qa.parquet")
    candidates = candidates[candidates.quality_status.eq("accepted")][["candidate_id", "title"]].rename(
        columns={"candidate_id": "event_id"}
    )
    candidates["body"] = ""
    joined = pd.concat([joined, candidates], ignore_index=True)
    # Conservative tokenizer-independent estimate: four UTF-8-ish text characters per token.
    text_chars = joined.title.fillna("").str.len() + joined.body.fillna("").str.slice(0, MAX_BODY_CHARS).str.len()
    estimated_input = int((text_chars / 4).apply(lambda value: int(value) + PROMPT_TOKENS_PER_ROW).sum())
    estimated_output = len(joined) * OUTPUT_TOKENS_PER_ROW
    standard = estimated_input / 1_000_000 * INPUT_USD_PER_M + estimated_output / 1_000_000 * OUTPUT_USD_PER_M
    payload = {
        "status": "approval_required_not_executed",
        "rows": len(joined),
        "existing_gap_rows": len(gaps),
        "new_candidate_rows": len(candidates),
        "model": MODEL,
        "max_body_chars_per_row": MAX_BODY_CHARS,
        "estimated_input_tokens": estimated_input,
        "estimated_output_tokens": estimated_output,
        "standard_api_estimated_usd": round(standard, 4),
        "batch_api_estimated_usd": round(standard * BATCH_DISCOUNT, 4),
        "recommended_approval_cap_usd": round(max(0.25, standard * BATCH_DISCOUNT * 2), 2),
        "pricing_checked_at": "2026-08-23",
        "pricing_sources": [
            "https://developers.openai.com/api/docs/models/gpt-5-mini",
            "https://platform.openai.com/docs/guides/batch",
        ],
    }
    (REPORTS / "SEMANTIC_BACKFILL_COST_V3.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
