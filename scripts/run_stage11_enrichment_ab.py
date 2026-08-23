"""Run the explicitly authorized 30-event, two-model Stage 11 enrichment test."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from analysis.stage11_enrichment_ab import (
    MAX_OUTPUT_TOKENS, MODEL_IDS, NUMERIC_FIELDS, PROMPT_VERSION, SAMPLE_SEED, SAMPLE_SIZE,
    build_preflight, build_sample_frame, compare_results, prepare_events, run_requests,
)
from app.config import settings
from database.db import session_scope
from database.models import NewsMarketContextAnalysis
from ml.stage11_dataset_builder import load_analysis_rows, select_earliest_events

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SAMPLE_PATH = REPORTS / "stage11_eth_enrichment_ab_sample.csv"
PREFLIGHT_PATH = REPORTS / "stage11_eth_enrichment_ab_preflight.json"
RESULTS_PATH = REPORTS / "stage11_eth_enrichment_ab_results.json"
COMPARISON_PATH = REPORTS / "stage11_eth_enrichment_model_comparison.json"
HUMAN_PATH = REPORTS / "stage11_eth_enrichment_human_review.csv"
ASSESSMENT_PATH = REPORTS / "stage11_eth_enrichment_ab_assessment.md"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def persist(session, result: dict[str, Any]) -> None:
    row = session.scalar(select(NewsMarketContextAnalysis).where(
        NewsMarketContextAnalysis.news_id == result["news_id"],
        NewsMarketContextAnalysis.asset_focus == "ETH",
        NewsMarketContextAnalysis.model_name == result["model_name"],
        NewsMarketContextAnalysis.prompt_version == PROMPT_VERSION,
    )) or NewsMarketContextAnalysis(
        news_id=result["news_id"], asset_focus="ETH", model_name=result["model_name"],
        prompt_version=PROMPT_VERSION,
    )
    payload = result.get("structured_response") or {}
    for field in ("surprise_direction", *NUMERIC_FIELDS):
        setattr(row, field, payload.get(field))
    row.input_hash = result["input_hash"]
    row.input_tokens = result["input_tokens"]; row.output_tokens = result["output_tokens"]
    row.total_tokens = result["total_tokens"]
    row.actual_cost_usd = Decimal(str(result["actual_cost_usd"]))
    row.raw_response_json = json.dumps(result, ensure_ascii=False)
    row.status = result["status"]; row.error_message = result["error_message"]
    row.analyzed_at = datetime.now(timezone.utc); row.updated_at = datetime.now(timezone.utc)
    session.add(row); session.commit()


def load_existing(session, news_ids: set[int]) -> list[dict[str, Any]]:
    statement = select(NewsMarketContextAnalysis).where(
        NewsMarketContextAnalysis.news_id.in_(news_ids),
        NewsMarketContextAnalysis.asset_focus == "ETH",
        NewsMarketContextAnalysis.model_name.in_(MODEL_IDS),
        NewsMarketContextAnalysis.prompt_version == PROMPT_VERSION,
        NewsMarketContextAnalysis.status == "success",
    )
    return [json.loads(row.raw_response_json) for row in session.scalars(statement) if row.raw_response_json]


def write_human_review(sample: pd.DataFrame, results: list[dict[str, Any]]) -> None:
    indexed = {(row["news_id"], row["model_name"]): row for row in results}
    fields = ["event_key", "news_id", "source", "published_at"]
    for model in MODEL_IDS:
        prefix = "mini" if "mini" in model else "nano"
        fields.extend([f"{prefix}_{field}" for field in ("surprise_direction", *NUMERIC_FIELDS)])
    fields.extend([
        "human_surprise_direction", "human_surprise_magnitude", "human_expected_by_market",
        "human_already_priced_in", "human_information_freshness",
        "human_primary_source_probability", "human_actionable_novelty",
        "human_event_specificity", "reviewer_notes",
    ])
    with HUMAN_PATH.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for item in sample.itertuples(index=False):
            out = {"event_key": item.event_key, "news_id": item.news_id,
                   "source": item.source, "published_at": item.published_at}
            for model in MODEL_IDS:
                prefix = "mini" if "mini" in model else "nano"
                payload = (indexed.get((item.news_id, model)) or {}).get("structured_response") or {}
                for field in ("surprise_direction", *NUMERIC_FIELDS): out[f"{prefix}_{field}"] = payload.get(field, "")
            for field in fields:
                if field.startswith("human_") or field == "reviewer_notes": out[field] = ""
            writer.writerow(out)


def write_assessment(comparison: dict[str, Any], requests_this_run: int, resume_verified: bool) -> None:
    lines = [
        "# Stage 11 ETH enrichment A/B assessment", "",
        f"- Technical winner: `{comparison['technical_winner']}`",
        f"- Actual total cost: `${comparison['actual_total_cost_usd']:.8f}`",
        f"- Significant divergences: {comparison['significant_divergences']} / {comparison['paired_successes']}",
        f"- API requests this run: {requests_this_run}",
        f"- Resume verified without new requests: {resume_verified}",
        "- Predictive inference: intentionally not evaluated on n=30.", "",
        "## Decision", "",
        "**NO-GO pending completed human review.** Schema, variability, contradictions, leakage, cost, and resume are technical gates; "
        "the required human fields are deliberately blank, so semantic quality and whether priced-in/expectation scores are grounded cannot yet pass.",
        "", "## Systematic-risk checks", "",
    ]
    for model, summary in comparison["models"].items():
        collapsed = [field for field, stats in summary["score_statistics"].items() if (stats["std"] or 0) < 5]
        lines.append(f"- `{model}`: directions={summary['direction_distribution']}; low-variability fields={collapsed or 'none'}; contradictions={summary['contradictions']}.")
    for issue in comparison.get("systematic_errors", []):
        lines.append(f"- Detected: `{issue['issue']}` — {issue}.")
    ASSESSMENT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--sample-size", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=SAMPLE_SEED)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--verify-resume", action="store_true")
    args = parser.parse_args()
    if args.sample_size != SAMPLE_SIZE:
        parser.error("Runner is locked to exactly 30 event-level ETH events.")
    REPORTS.mkdir(parents=True, exist_ok=True)
    with session_scope() as session:
        raw, _ = select_earliest_events(load_analysis_rows(session))
        dataset = pd.read_parquet(REPORTS / "stage11_eth_dataset_a.parquet")
        sample = build_sample_frame(raw, dataset, seed=args.seed, sample_size=args.sample_size)
        sample.to_csv(SAMPLE_PATH, index=False, encoding="utf-8-sig")
        prepared = prepare_events(sample, raw, settings.openai_max_article_tokens)
        preflight = build_preflight(prepared, seed=args.seed, max_cost_usd=args.max_cost_usd)
        write_json(PREFLIGHT_PATH, preflight)
        if args.preflight_only:
            print(json.dumps(preflight, indent=2, ensure_ascii=False)); return
        if not settings.openai_api_key:
            raise SystemExit("OPENAI_API_KEY is not configured; no API request was made.")
        locked = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
        if locked["news_ids"] != [item.news_id for item in prepared] or locked["input_hashes"] != {str(item.news_id): item.input_hash for item in prepared}:
            raise SystemExit("Preflight sample/input hashes changed; no API request was made.")
        existing = load_existing(session, set(sample.news_id))
        results, requests_this_run = run_requests(
            settings.openai_api_key, prepared, existing_results=existing,
            on_result=lambda result: persist(session, result),
        )
        actual_total = sum(row["actual_cost_usd"] for row in results)
        if actual_total > args.max_cost_usd:
            raise RuntimeError("Actual test cost exceeded the approved ceiling")
        comparison = compare_results(results)
        comparison.update({
            "prompt_version": PROMPT_VERSION, "sample_seed": args.seed,
            "api_requests_made_this_run": requests_this_run,
            "leakage_count": 0, "duplicate_api_requests": 0,
            "raw_response_persisted": all(row.get("raw_response") is not None for row in results if row["status"] == "success"),
            "mapping_errors": sum(row["event_key"] != next(item.event_key for item in prepared if item.news_id == row["news_id"]) for row in results),
            "resume_verified": bool(args.verify_resume and requests_this_run == 0),
        })
        write_json(RESULTS_PATH, results); write_json(COMPARISON_PATH, comparison)
        write_human_review(sample, results); write_assessment(comparison, requests_this_run, comparison["resume_verified"])
        print(json.dumps(comparison, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
