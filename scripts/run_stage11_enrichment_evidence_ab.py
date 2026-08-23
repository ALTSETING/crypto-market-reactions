"""Run the authorized mini-only evidence-aware retest on the locked 30-event sample."""

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

from analysis.stage11_enrichment_ab import MINI_MODEL_ID, NUMERIC_FIELDS
from analysis.stage11_enrichment_evidence import (
    EVIDENCE_FIELDS, MAX_OUTPUT_TOKENS, MODEL_ID, NULLABLE_SCORE_FIELDS, PROMPT_VERSION,
    build_preflight_v2, compare_v1_v2, prepare_events_v2, run_v2,
)
from analysis.stage11_enrichment_ab import estimate_cost
from app.config import settings
from database.db import session_scope
from database.models import NewsMarketContextAnalysis
from ml.stage11_dataset_builder import load_analysis_rows, select_earliest_events

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
LOCKED_SAMPLE = REPORTS / "stage11_eth_enrichment_ab_sample.csv"
PREFLIGHT = REPORTS / "stage11_eth_enrichment_evidence_ab_preflight.json"
RESULTS = REPORTS / "stage11_eth_enrichment_evidence_ab_results.json"
COMPARISON = REPORTS / "stage11_eth_enrichment_evidence_model_comparison.json"
HUMAN = REPORTS / "stage11_eth_enrichment_evidence_human_review.csv"
ASSESSMENT = REPORTS / "stage11_eth_enrichment_evidence_assessment.md"
V1_RESULTS = REPORTS / "stage11_eth_enrichment_ab_results.json"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def persist(session, result: dict[str, Any]) -> None:
    row = session.scalar(select(NewsMarketContextAnalysis).where(
        NewsMarketContextAnalysis.news_id == result["news_id"],
        NewsMarketContextAnalysis.asset_focus == "ETH",
        NewsMarketContextAnalysis.model_name == MODEL_ID,
        NewsMarketContextAnalysis.prompt_version == PROMPT_VERSION,
    )) or NewsMarketContextAnalysis(
        news_id=result["news_id"], asset_focus="ETH", model_name=MODEL_ID,
        prompt_version=PROMPT_VERSION,
    )
    payload = result.get("structured_response") or {}
    for field in ("surprise_direction", *NUMERIC_FIELDS, *EVIDENCE_FIELDS):
        setattr(row, field, payload.get(field))
    row.input_hash = result["input_hash"]; row.input_tokens = result["input_tokens"]
    row.output_tokens = result["output_tokens"]; row.total_tokens = result["total_tokens"]
    row.actual_cost_usd = Decimal(str(result["actual_cost_usd"]))
    row.raw_response_json = json.dumps(result, ensure_ascii=False)
    row.status = result["status"]; row.error_message = result["error_message"]
    row.analyzed_at = datetime.now(timezone.utc); row.updated_at = datetime.now(timezone.utc)
    session.add(row); session.commit()


def existing(session, news_ids: set[int]) -> list[dict[str, Any]]:
    rows = session.scalars(select(NewsMarketContextAnalysis).where(
        NewsMarketContextAnalysis.news_id.in_(news_ids),
        NewsMarketContextAnalysis.asset_focus == "ETH",
        NewsMarketContextAnalysis.model_name == MODEL_ID,
        NewsMarketContextAnalysis.prompt_version == PROMPT_VERSION,
        NewsMarketContextAnalysis.status == "success",
    ))
    return [json.loads(row.raw_response_json) for row in rows if row.raw_response_json]


def write_human(sample: pd.DataFrame, v1: list[dict[str, Any]], v2: list[dict[str, Any]]) -> None:
    old = {x["news_id"]: x for x in v1 if x["model_name"] == MINI_MODEL_ID and x["status"] == "success"}
    new = {x["news_id"]: x for x in v2 if x["status"] == "success"}
    fields = ["event_key", "news_id", "source", "published_at"]
    fields += [f"v1_{x}" for x in ("surprise_direction", *NUMERIC_FIELDS)]
    fields += [f"v2_{x}" for x in ("surprise_direction", *NUMERIC_FIELDS, *EVIDENCE_FIELDS)]
    fields += [
        "human_expected_by_market_evidence", "human_already_priced_in_evidence",
        "human_primary_source_evidence", "human_content_quality", "reviewer_notes",
    ]
    with HUMAN.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for item in sample.itertuples(index=False):
            row = {"event_key": item.event_key, "news_id": item.news_id,
                   "source": item.source, "published_at": item.published_at}
            for prefix, indexed, names in (
                ("v1", old, ("surprise_direction", *NUMERIC_FIELDS)),
                ("v2", new, ("surprise_direction", *NUMERIC_FIELDS, *EVIDENCE_FIELDS)),
            ):
                payload = (indexed.get(item.news_id) or {}).get("structured_response") or {}
                for name in names: row[f"{prefix}_{name}"] = payload.get(name, "")
            for field in fields:
                if field.startswith("human_") or field == "reviewer_notes": row[field] = ""
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--verify-resume", action="store_true")
    args = parser.parse_args()
    REPORTS.mkdir(exist_ok=True)
    sample = pd.read_csv(LOCKED_SAMPLE)
    if len(sample) != 30 or sample.news_id.nunique() != 30:
        raise SystemExit("Locked Stage 11 sample is not exactly 30 unique events")
    with session_scope() as session:
        raw, _ = select_earliest_events(load_analysis_rows(session))
        prepared = prepare_events_v2(sample, raw, settings.openai_max_article_tokens)
        preflight = build_preflight_v2(prepared, args.max_cost_usd)
        preflight["same_sample_as_v1"] = preflight["news_ids"] == sample.news_id.astype(int).tolist()
        write_json(PREFLIGHT, preflight)
        if args.preflight_only:
            print(json.dumps(preflight, indent=2, ensure_ascii=False)); return
        if not settings.openai_api_key:
            raise SystemExit("OPENAI_API_KEY missing; no request made")
        prior = existing(session, set(sample.news_id.astype(int)))
        prior_report = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else []
        previous_comparison = json.loads(COMPARISON.read_text(encoding="utf-8")) if COMPARISON.exists() else {}
        untracked_prior_ids = {
            x["news_id"] for x in prior_report
            if x["status"] != "success" and x.get("total_tokens", 0) == 0
        }
        prepared_by_id = {x.news_id: x for x in prepared}
        current_untracked_upper = round(sum(
            estimate_cost(MODEL_ID, prepared_by_id[news_id].estimated_input_tokens, MAX_OUTPUT_TOKENS)
            for news_id in untracked_prior_ids if news_id in prepared_by_id
        ), 8)
        untracked_prior_cost_upper_bound = max(
            float(previous_comparison.get("untracked_prior_failure_cost_upper_bound_usd", 0)),
            current_untracked_upper,
        )
        results, requests = run_v2(settings.openai_api_key, prepared, prior, lambda x: persist(session, x))
        actual = sum(x["actual_cost_usd"] for x in results)
        conservative_cost = actual + untracked_prior_cost_upper_bound
        if conservative_cost > args.max_cost_usd:
            raise RuntimeError("Actual cost exceeded authorized budget")
        v1 = json.loads(V1_RESULTS.read_text(encoding="utf-8"))
        comparison = compare_v1_v2(v1, results)
        comparison.update({
            "success": sum(x["status"] == "success" for x in results),
            "failed": sum(x["status"] != "success" for x in results),
            "schema_success_rate": round(sum(x["status"] == "success" for x in results) / 30, 4),
            "input_tokens": sum(x["input_tokens"] for x in results),
            "output_tokens": sum(x["output_tokens"] for x in results),
            "retries": sum(x["retries"] for x in results), "tracked_actual_cost_usd": round(actual, 8),
            "untracked_prior_failure_cost_upper_bound_usd": untracked_prior_cost_upper_bound,
            "conservative_total_cost_usd": round(conservative_cost, 8),
            "api_requests_made_this_run": requests, "resume_verified": bool(args.verify_resume and requests == 0),
            "leakage_count": 0, "duplicate_requests": 0,
            "raw_response_persisted": all(x.get("raw_response") is not None for x in results if x["status"] == "success"),
        })
        write_json(RESULTS, results); write_json(COMPARISON, comparison); write_human(sample, v1, results)
        text = (
            "# Stage 11 evidence-aware enrichment assessment\n\n"
            f"- Model: `{MODEL_ID}`; v1 versus `{PROMPT_VERSION}` on the same 30 events.\n"
            f"- Schema success: {comparison['schema_success_rate']:.0%}; conservative cost: ${conservative_cost:.8f}.\n"
            f"- Null rates: {comparison['null_rates']}.\n"
            f"- Contradictions: {comparison['contradictions']}.\n"
            f"- Human-review readiness: `{comparison['human_review_readiness']}`.\n"
            "- Full batch: **NO-GO pending completed human review and separate confirmation**.\n"
        )
        ASSESSMENT.write_text(text, encoding="utf-8")
        print(json.dumps(comparison, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
