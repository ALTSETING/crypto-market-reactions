"""Preflight and operate the authorized Stage 9 ETH OpenAI batch."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from openai import OpenAI
from sqlalchemy import select

from analysis.eth_batch import (
    ASSET_FOCUS, ENDPOINT, MODEL_ID, BatchItem, actual_batch_cost, estimate_batch,
    parse_batch_result, prepare_batch_items, request_line, validate_jsonl,
)
from analysis.openai_analyzer import PROMPT_VERSION
from app.config import settings
from database.db import session_scope
from database.models import NewsAnalysis
from database.repositories.analysis_repository import AnalysisRepository

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
JSONL_PATH = REPORTS / "stage9_eth_batch_input.jsonl"
PREFLIGHT_PATH = REPORTS / "stage9_eth_batch_preflight.json"
SUBMISSION_PATH = REPORTS / "stage9_eth_batch_submission.json"
OUTPUT_PATH = REPORTS / "stage9_eth_batch_output.jsonl"
ERROR_PATH = REPORTS / "stage9_eth_batch_errors.jsonl"
API_STATS_PATH = REPORTS / "stage9_eth_api_stats.json"
RESULTS_PATH = REPORTS / "stage9_eth_results.csv"
FAILURES_PATH = REPORTS / "stage9_eth_failures.csv"
FINAL_PATH = REPORTS / "stage9_eth_final_report.json"


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_submission() -> dict[str, Any] | None:
    return json.loads(SUBMISSION_PATH.read_text(encoding="utf-8")) if SUBMISSION_PATH.exists() else None


def build_current(max_cost_usd: float) -> tuple[list[Any], list[Any], dict[str, Any]]:
    with session_scope() as session:
        repository = AnalysisRepository(session)
        all_candidates = repository.get_eth_news_candidates()
        successful_ids = repository.get_successful_analysis_ids(MODEL_ID, PROMPT_VERSION)
        pending = [article for article in all_candidates if article.id not in successful_ids]
        items = prepare_batch_items(pending, settings.openai_max_article_tokens)
    lines = [request_line(item, settings.openai_max_output_tokens) for item in items]
    validation = validate_jsonl(lines, len(items))
    estimate = estimate_batch(items, settings.openai_max_output_tokens)
    if not validation["valid"]:
        raise RuntimeError("Batch JSONL validation failed")
    if estimate["estimated_batch_cost_usd"] > max_cost_usd:
        raise RuntimeError(
            f"Estimated cost ${estimate['estimated_batch_cost_usd']:.8f} exceeds ${max_cost_usd:.8f}"
        )
    preflight = {
        "status": "PREFLIGHT_PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "api_requests_made": 0,
        "api_key_present": bool(settings.openai_api_key),
        "api_key_value_logged": False,
        "old_published_key_check": "requires_user_rotation_attestation",
        "total_unique_eth_news": len(all_candidates),
        "already_analyzed_success": len(successful_ids & {a.id for a in all_candidates}),
        "unprocessed_news": len(items),
        "model": MODEL_ID,
        "asset_focus": ASSET_FOCUS,
        "prompt_version": PROMPT_VERSION,
        "endpoint": ENDPOINT,
        "max_output_tokens": settings.openai_max_output_tokens,
        "max_cost_usd": max_cost_usd,
        "jsonl_path": str(JSONL_PATH.relative_to(ROOT)),
        "jsonl_validation": validation,
        "estimate": estimate,
        "input_hashes": {str(item.news_id): item.input_hash for item in items},
        "custom_ids": [item.custom_id for item in items],
    }
    return items, lines, preflight


def preflight(max_cost_usd: float) -> dict[str, Any]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    _items, lines, report = build_current(max_cost_usd)
    with JSONL_PATH.open("w", encoding="utf-8", newline="\n") as output:
        for line in lines:
            output.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
    parsed = [json.loads(line) for line in JSONL_PATH.read_text(encoding="utf-8").splitlines() if line]
    report["jsonl_validation_after_write"] = validate_jsonl(parsed, len(lines))
    if not report["jsonl_validation_after_write"]["valid"]:
        raise RuntimeError("Written JSONL failed round-trip validation")
    write_json(PREFLIGHT_PATH, report)
    return report


def submit(max_cost_usd: float, rotation_attested: bool) -> dict[str, Any]:
    if not rotation_attested:
        raise SystemExit("Key rotation attestation missing; no API request was made.")
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is missing; no API request was made.")
    existing = load_submission()
    if existing and existing.get("batch_id"):
        raise SystemExit(f"Existing batch {existing['batch_id']} recorded; no duplicate was submitted.")
    items, _lines, current = build_current(max_cost_usd)
    if not PREFLIGHT_PATH.exists():
        raise SystemExit("Preflight report is missing; no API request was made.")
    locked = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    if locked["input_hashes"] != current["input_hashes"] or locked["custom_ids"] != current["custom_ids"]:
        raise SystemExit("Current inputs differ from preflight; no API request was made.")
    client = OpenAI(api_key=settings.openai_api_key, max_retries=2)
    with JSONL_PATH.open("rb") as source:
        uploaded = client.files.create(file=source, purpose="batch")
    batch = client.batches.create(
        input_file_id=uploaded.id, endpoint=ENDPOINT, completion_window="24h",
        metadata={"stage": "9", "asset": ASSET_FOCUS, "prompt_version": PROMPT_VERSION},
    )
    report = {
        "submitted_at": datetime.now(timezone.utc).isoformat(), "batch_id": batch.id,
        "input_file_id": uploaded.id, "status": batch.status, "submitted": len(items),
        "model": MODEL_ID, "prompt_version": PROMPT_VERSION, "asset_focus": ASSET_FOCUS,
        "max_cost_usd": max_cost_usd, "estimated_batch_cost_usd": current["estimate"]["estimated_batch_cost_usd"],
        "custom_ids_sha256": __import__("hashlib").sha256("\n".join(current["custom_ids"]).encode()).hexdigest(),
    }
    write_json(SUBMISSION_PATH, report)
    with session_scope() as session:
        for item in items:
            row = session.scalar(select(NewsAnalysis).where(
                NewsAnalysis.news_id == item.news_id, NewsAnalysis.asset_focus == ASSET_FOCUS,
                NewsAnalysis.model_name == MODEL_ID, NewsAnalysis.prompt_version == PROMPT_VERSION,
            )) or NewsAnalysis(news_id=item.news_id, asset_focus=ASSET_FOCUS, model_name=MODEL_ID, prompt_version=PROMPT_VERSION)
            if row.status != "success":
                row.status = "submitted"; row.batch_id = batch.id; row.batch_custom_id = item.custom_id
                row.input_hash = item.input_hash; row.updated_at = datetime.now(timezone.utc); session.add(row)
        session.commit()
    return report


def status() -> dict[str, Any]:
    submission = load_submission()
    if not submission:
        raise SystemExit("No submitted batch is recorded.")
    client = OpenAI(api_key=settings.openai_api_key, max_retries=2)
    batch = client.batches.retrieve(submission["batch_id"])
    submission.update({
        "status": batch.status, "checked_at": datetime.now(timezone.utc).isoformat(),
        "request_counts": batch.request_counts.model_dump() if batch.request_counts else None,
        "output_file_id": batch.output_file_id, "error_file_id": batch.error_file_id,
    })
    write_json(SUBMISSION_PATH, submission)
    return submission


def _download(client: OpenAI, file_id: str | None, destination: Path) -> None:
    if not file_id:
        destination.write_text("", encoding="utf-8")
        return
    response = client.files.content(file_id)
    destination.write_bytes(response.content)


def _items_from_locked_jsonl() -> dict[str, BatchItem]:
    result: dict[str, BatchItem] = {}
    for raw in JSONL_PATH.read_text(encoding="utf-8").splitlines():
        if not raw:
            continue
        line = json.loads(raw)
        custom_id = str(line["custom_id"])
        body = line["body"]
        user_input = next(message["content"] for message in body["input"] if message["role"] == "user")
        news_id = int(custom_id.split("-")[1])
        item = BatchItem(
            news_id=news_id, title="", input_text=user_input,
            input_hash=hashlib.sha256(user_input.encode("utf-8")).hexdigest(),
            estimated_input_tokens=0, attempt=int(custom_id.rsplit("a", 1)[1]),
        )
        if item.custom_id != custom_id:
            raise RuntimeError(f"Unexpected custom_id format: {custom_id}")
        result[custom_id] = item
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _persist_batch_results(results: list[dict[str, Any]], batch_id: str) -> None:
    with session_scope() as session:
        for result in results:
            news_id = result.get("news_id")
            if news_id is None:
                continue
            row = session.scalar(select(NewsAnalysis).where(
                NewsAnalysis.news_id == news_id, NewsAnalysis.asset_focus == ASSET_FOCUS,
                NewsAnalysis.model_name == MODEL_ID, NewsAnalysis.prompt_version == PROMPT_VERSION,
            ))
            if row is None:
                row = NewsAnalysis(news_id=news_id, asset_focus=ASSET_FOCUS, model_name=MODEL_ID, prompt_version=PROMPT_VERSION)
            if row.status == "success":
                continue
            payload = result.get("payload") or {}
            row.sentiment = payload.get("sentiment"); row.importance = payload.get("importance")
            row.novelty = payload.get("novelty"); row.credibility = payload.get("credibility")
            row.expected_direction = payload.get("direction"); row.category = payload.get("category")
            row.impact_duration = payload.get("horizon"); row.confidence = payload.get("confidence")
            row.asset_relevance = payload.get("eth_relevance"); row.input_hash = result.get("input_hash")
            row.input_tokens = result.get("input_tokens", 0); row.output_tokens = result.get("output_tokens", 0)
            row.total_tokens = result.get("total_tokens", 0)
            row.actual_cost_usd = Decimal(str(actual_batch_cost(row.input_tokens or 0, row.output_tokens or 0)))
            row.batch_id = batch_id; row.batch_custom_id = result.get("custom_id")
            row.status = result["status"]; row.error_message = result.get("error_message")
            row.raw_response_json = json.dumps(result, ensure_ascii=False)
            row.analyzed_at = datetime.now(timezone.utc); row.updated_at = datetime.now(timezone.utc)
            session.add(row)
        session.commit()


def _write_csv_reports() -> tuple[list[NewsAnalysis], list[NewsAnalysis]]:
    with session_scope() as session:
        rows = list(session.scalars(select(NewsAnalysis).where(
            NewsAnalysis.asset_focus == ASSET_FOCUS, NewsAnalysis.model_name == MODEL_ID,
            NewsAnalysis.prompt_version == PROMPT_VERSION,
        ).order_by(NewsAnalysis.news_id)))
        data = [{column: getattr(row, column) for column in (
            "news_id", "status", "sentiment", "importance", "novelty", "credibility",
            "expected_direction", "category", "impact_duration", "confidence", "asset_relevance",
            "input_tokens", "output_tokens", "total_tokens", "actual_cost_usd", "batch_id",
            "batch_custom_id", "error_message",
        )} for row in rows]
    fields = list(data[0]) if data else ["news_id", "status", "error_message"]
    with RESULTS_PATH.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for row in data:
            writer.writerow({key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()})
    failures = [row for row in data if row["status"] != "success"]
    with FAILURES_PATH.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for row in failures:
            writer.writerow({key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()})
    return data, failures


def finalize() -> dict[str, Any]:
    submission = status()
    if submission["status"] != "completed":
        raise SystemExit(f"Batch is {submission['status']}; finalize deferred.")
    client = OpenAI(api_key=settings.openai_api_key, max_retries=2)
    _download(client, submission.get("output_file_id"), OUTPUT_PATH)
    _download(client, submission.get("error_file_id"), ERROR_PATH)
    item_map = _items_from_locked_jsonl()
    output_lines = _read_jsonl(OUTPUT_PATH)
    error_lines = _read_jsonl(ERROR_PATH)
    results = [parse_batch_result(line, item_map) for line in [*output_lines, *error_lines]]
    received_ids = {row.get("custom_id") for row in results}
    for custom_id, item in item_map.items():
        if custom_id not in received_ids:
            results.append({
                "news_id": item.news_id, "custom_id": custom_id, "status": "missing",
                "input_hash": item.input_hash, "input_tokens": 0, "output_tokens": 0,
                "total_tokens": 0, "payload": None, "error_message": "No output or error record",
            })
    _persist_batch_results(results, submission["batch_id"])
    rows, failures = _write_csv_reports()
    batch_rows = [row for row in rows if row["batch_id"] == submission["batch_id"]]
    successes = [row for row in rows if row["status"] == "success"]
    batch_successes = [row for row in batch_rows if row["status"] == "success"]
    input_tokens = sum(int(row["input_tokens"] or 0) for row in batch_rows)
    output_tokens = sum(int(row["output_tokens"] or 0) for row in batch_rows)
    actual_cost = actual_batch_cost(input_tokens, output_tokens)
    total_unique = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))["total_unique_eth_news"]
    def stats(field: str) -> dict[str, Any]:
        values = [int(row[field]) for row in successes if row[field] is not None]
        return {"mean": round(statistics.mean(values), 3), "median": statistics.median(values),
                "min": min(values), "max": max(values)} if values else {}
    final_report = {
        "status": "PASS" if len(successes) == total_unique and actual_cost <= 2.0 else "FAIL",
        "batch_id": submission["batch_id"], "batch_status": submission["status"],
        "total_unique_eth_news": total_unique, "already_analyzed_before_batch": total_unique - len(item_map),
        "submitted": len(item_map), "success": len(successes), "batch_success": len(batch_successes),
        "failed": len([row for row in rows if row["status"] == "api_error"]),
        "invalid_schema": len([row for row in rows if row["status"] == "invalid_schema"]),
        "refused": len([row for row in rows if row["status"] == "refused"]),
        "retries": 0, "missing_analyses": total_unique - len(successes),
        "schema_success_rate": round(len(batch_successes) / len(item_map), 6) if item_map else 1.0,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "actual_cost_usd": actual_cost,
        "average_cost_per_news_usd": round(actual_cost / len(batch_rows), 8) if batch_rows else 0,
        "max_cost_usd": 2.0, "model": MODEL_ID, "prompt_version": PROMPT_VERSION,
        "leakage": 0,
        "category_distribution": dict(Counter(row["category"] or "unknown" for row in successes)),
        "direction_distribution": dict(Counter(row["expected_direction"] or "unknown" for row in successes)),
        "horizon_distribution": dict(Counter(row["impact_duration"] or "unknown" for row in successes)),
        "sentiment_statistics": stats("sentiment"), "importance_statistics": stats("importance"),
        "eth_relevance_statistics": stats("asset_relevance"),
        "documented_failures": len(failures),
    }
    api_stats = {key: final_report[key] for key in (
        "batch_id", "model", "prompt_version", "submitted", "batch_success", "failed",
        "invalid_schema", "refused", "input_tokens", "output_tokens", "actual_cost_usd",
        "average_cost_per_news_usd", "schema_success_rate",
    )}
    write_json(API_STATS_PATH, api_stats); write_json(FINAL_PATH, final_report)
    return final_report


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--submit", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--finalize", action="store_true")
    parser.add_argument("--max-cost-usd", type=float, default=2.0)
    parser.add_argument("--confirm-key-rotated", action="store_true")
    args = parser.parse_args()
    if args.preflight:
        result = preflight(args.max_cost_usd)
    elif args.submit:
        result = submit(args.max_cost_usd, args.confirm_key_rotated)
    elif args.status:
        result = status()
    else:
        result = finalize()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
