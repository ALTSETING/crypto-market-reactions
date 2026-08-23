"""Run the explicitly authorized 50x2 Stage 9 synchronous A/B test."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from analysis.eth_ab_test import (
    MINI_MODEL_ID,
    MODEL_IDS,
    NANO_MODEL_ID,
    PreparedArticle,
    build_preflight,
    deterministic_sample,
    prepare_sample,
    result_envelope,
    run_requests,
)
from analysis.openai_analyzer import PROMPT_VERSION
from app.config import settings
from database.db import session_scope
from database.models import NewsAnalysis
from database.repositories.analysis_repository import AnalysisRepository

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
PREFLIGHT_PATH = REPORTS_DIR / "stage9_eth_ab_preflight.json"
RESULTS_PATH = REPORTS_DIR / "stage9_eth_ab_results.json"
COMPARISON_PATH = REPORTS_DIR / "stage9_eth_model_comparison.json"
HUMAN_REVIEW_PATH = REPORTS_DIR / "stage9_eth_human_review.csv"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _persist(session, result: dict[str, Any], prompt_version: str) -> None:
    statement = select(NewsAnalysis).where(
        NewsAnalysis.news_id == result["news_id"],
        NewsAnalysis.asset_focus == "ETH",
        NewsAnalysis.model_name == result["model_name"],
        NewsAnalysis.prompt_version == prompt_version,
    )
    row = session.scalar(statement) or NewsAnalysis(
        news_id=result["news_id"],
        asset_focus="ETH",
        model_name=result["model_name"],
        prompt_version=prompt_version,
    )
    payload = result.get("structured_response") or {}
    row.sentiment = payload.get("sentiment")
    row.importance = payload.get("importance")
    row.novelty = payload.get("novelty")
    row.credibility = payload.get("credibility")
    row.expected_direction = payload.get("direction")
    row.category = payload.get("category")
    row.impact_duration = payload.get("horizon")
    row.confidence = payload.get("confidence")
    row.asset_relevance = payload.get("eth_relevance")
    row.input_tokens = result["input_tokens"]
    row.output_tokens = result["output_tokens"]
    row.total_tokens = result["total_tokens"]
    row.actual_cost_usd = Decimal(str(result["actual_cost_usd"]))
    row.estimated_cost_usd = Decimal(str(result["actual_cost_usd"]))
    row.input_hash = result["input_hash"]
    row.raw_response_json = result_envelope(result)
    row.status = result["status"]
    row.error_message = result["error_message"]
    row.analyzed_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()


def _comparison(results: list[dict[str, Any]], prompt_version: str) -> dict[str, Any]:
    by_model = {model: [row for row in results if row["model_name"] == model] for model in MODEL_IDS}
    summaries: dict[str, Any] = {}
    for model, rows in by_model.items():
        successes = [row for row in rows if row["status"] == "success"]
        summaries[model] = {
            "success": len(successes),
            "failed": len(rows) - len(successes),
            "schema_success_rate": round(len(successes) / len(rows), 4) if rows else 0,
            "actual_cost_usd": round(sum(row["actual_cost_usd"] for row in rows), 8),
            "average_cost_per_article_usd": round(
                sum(row["actual_cost_usd"] for row in rows) / len(rows), 8
            ) if rows else 0,
            "input_tokens": sum(row["input_tokens"] for row in rows),
            "output_tokens": sum(row["output_tokens"] for row in rows),
            "total_tokens": sum(row["total_tokens"] for row in rows),
            "average_latency_seconds": round(statistics.mean(row["latency_seconds"] for row in rows), 4) if rows else 0,
            "retries": sum(row["retries"] for row in rows),
            "direction_distribution": dict(Counter(row["structured_response"]["direction"] for row in successes)),
            "category_distribution": dict(Counter(row["structured_response"]["category"] for row in successes)),
            "horizon_distribution": dict(Counter(row["structured_response"]["horizon"] for row in successes)),
        }

    indexed = {(row["news_id"], row["model_name"]): row for row in results}
    numeric_fields = ("sentiment", "importance", "novelty", "credibility", "confidence", "eth_relevance")
    categorical_fields = ("direction", "category", "horizon")
    numeric_differences: dict[str, list[float]] = {field: [] for field in numeric_fields}
    agreements: dict[str, list[bool]] = {field: [] for field in categorical_fields}
    significant_news_ids: list[int] = []
    paired = 0
    for news_id in sorted({row["news_id"] for row in results}):
        nano = indexed.get((news_id, NANO_MODEL_ID))
        mini = indexed.get((news_id, MINI_MODEL_ID))
        if not nano or not mini or nano["status"] != "success" or mini["status"] != "success":
            continue
        paired += 1
        a, b = nano["structured_response"], mini["structured_response"]
        for field in numeric_fields:
            numeric_differences[field].append(abs(a[field] - b[field]))
        for field in categorical_fields:
            agreements[field].append(a[field] == b[field])
        opposite_direction = {a["direction"], b["direction"]} == {"bearish", "bullish"}
        if (
            abs(a["sentiment"] - b["sentiment"]) >= 30
            or abs(a["importance"] - b["importance"]) >= 25
            or abs(a["confidence"] - b["confidence"]) >= 25
            or abs(a["eth_relevance"] - b["eth_relevance"]) >= 25
            or opposite_direction
        ):
            significant_news_ids.append(news_id)

    mean_diffs = {
        field: round(statistics.mean(values), 3) if values else None
        for field, values in numeric_differences.items()
    }
    all_numeric = [value for values in numeric_differences.values() for value in values]
    categorical_agreement = {
        field: round(sum(values) / len(values), 4) if values else None
        for field, values in agreements.items()
    }
    nano_summary, mini_summary = summaries[NANO_MODEL_ID], summaries[MINI_MODEL_ID]
    recommend_nano = (
        nano_summary["schema_success_rate"] >= 0.99
        and nano_summary["schema_success_rate"] >= mini_summary["schema_success_rate"] - 0.01
        and len(significant_news_ids) <= max(5, round(paired * 0.15))
    )
    return {
        "prompt_version": prompt_version,
        "model_ids": list(MODEL_IDS),
        "paired_successes": paired,
        "models": summaries,
        "mean_absolute_score_differences": mean_diffs,
        "overall_mean_absolute_score_difference": round(statistics.mean(all_numeric), 3) if all_numeric else None,
        "categorical_agreement_rates": categorical_agreement,
        "significant_divergence_definition": "sentiment>=30, importance/confidence/eth_relevance>=25, or bearish-vs-bullish",
        "significant_divergences": len(significant_news_ids),
        "significant_divergence_news_ids": significant_news_ids,
        "total_actual_cost_usd": round(sum(row["actual_cost_usd"] for row in results), 8),
        "recommendation": NANO_MODEL_ID if recommend_nano else MINI_MODEL_ID,
        "recommendation_basis": (
            "nano met schema/stability thresholds at lower cost"
            if recommend_nano else "mini preferred because nano did not meet schema/stability thresholds"
        ),
    }


def _write_human_review(results: list[dict[str, Any]], seed: int) -> None:
    successful = [row for row in results if row["status"] == "success"]
    sample = random.Random(seed + 1).sample(successful, min(30, len(successful)))
    fields = [
        "news_id", "model_name", "title", "excerpt", "ai_sentiment", "ai_importance",
        "ai_direction", "ai_category", "ai_horizon", "ai_confidence", "ai_eth_relevance",
        "human_sentiment", "human_importance", "human_direction", "human_category", "reviewer_notes",
    ]
    with HUMAN_REVIEW_PATH.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in sample:
            payload = row["structured_response"]
            writer.writerow({
                "news_id": row["news_id"], "model_name": row["model_name"], "title": row["title"],
                "excerpt": row.get("input_excerpt", "")[:300], "ai_sentiment": payload["sentiment"], "ai_importance": payload["importance"],
                "ai_direction": payload["direction"], "ai_category": payload["category"],
                "ai_horizon": payload["horizon"], "ai_confidence": payload["confidence"],
                "ai_eth_relevance": payload["eth_relevance"], "human_sentiment": "",
                "human_importance": "", "human_direction": "", "human_category": "", "reviewer_notes": "",
            })


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--canary", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--prompt-version", default=PROMPT_VERSION)
    args = parser.parse_args()
    if args.sample_size != 50:
        parser.error("This authorized A/B runner is locked to exactly 50 news articles.")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with session_scope() as session:
        candidates = AnalysisRepository(session).get_eth_news_candidates()
        selected = deterministic_sample(candidates, args.sample_size, args.seed)
        prepared = prepare_sample(selected, settings.openai_max_article_tokens)
        preflight = build_preflight(
            prepared, prompt_version=args.prompt_version, seed=args.seed,
            max_output_tokens=settings.openai_max_output_tokens, max_cost_usd=args.max_cost_usd,
        )
        if args.preflight_only:
            _write_json(PREFLIGHT_PATH, preflight)
            print(json.dumps(preflight, indent=2, ensure_ascii=False))
            return

        if not settings.openai_api_key:
            raise SystemExit("OPENAI_API_KEY is not configured; no API request was made.")
        if not PREFLIGHT_PATH.exists():
            raise SystemExit("Preflight file is missing; no API request was made.")
        locked = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
        if locked["news_ids"] != preflight["news_ids"] or locked["input_hashes"] != preflight["input_hashes"]:
            raise SystemExit("Sample/input hashes differ from approved preflight; no API request was made.")

        selected_ids = {item.news_id for item in prepared}
        existing_statement = select(NewsAnalysis).where(
            NewsAnalysis.news_id.in_(selected_ids),
            NewsAnalysis.asset_focus == "ETH",
            NewsAnalysis.model_name.in_(MODEL_IDS),
            NewsAnalysis.prompt_version == args.prompt_version,
            NewsAnalysis.status == "success",
        )
        existing_results: list[dict[str, Any]] = []
        for row in session.scalars(existing_statement):
            if row.raw_response_json:
                existing_results.append(json.loads(row.raw_response_json))

        if args.canary:
            canary_news_id = prepared[0].news_id
            canary_existing = [
                result for result in existing_results if result["news_id"] == canary_news_id
            ]
            canary_results = run_requests(
                settings.openai_api_key,
                prepared[:1],
                max_output_tokens=settings.openai_max_output_tokens,
                existing_results=canary_existing,
                on_result=lambda result: _persist(session, result, args.prompt_version),
                workers=2,
            )
            _write_json(REPORTS_DIR / "stage9_eth_ab_canary.json", canary_results)
            print(json.dumps(canary_results, indent=2, ensure_ascii=False))
            return

        results = run_requests(
            settings.openai_api_key, prepared,
            max_output_tokens=settings.openai_max_output_tokens,
            existing_results=existing_results,
            on_result=lambda result: _persist(session, result, args.prompt_version),
        )
        actual_total = sum(row["actual_cost_usd"] for row in results)
        if actual_total > args.max_cost_usd:
            raise RuntimeError("Actual A/B cost exceeded the approved limit")
        _write_json(RESULTS_PATH, results)
        comparison = _comparison(results, args.prompt_version)
        _write_json(COMPARISON_PATH, comparison)
        _write_human_review(results, args.seed)
        print(json.dumps(comparison, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
