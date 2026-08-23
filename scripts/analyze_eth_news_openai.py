"""Stage 9 ETH selection and cost dry-run.  No API requests are made here."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from analysis.openai_analyzer import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    analysis_json_schema,
    assert_no_data_leakage,
    count_request_input_tokens,
    prepare_eth_analysis_input_details,
)
from app.config import settings
from database.db import session_scope
from database.repositories.analysis_repository import AnalysisRepository

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
STANDARD_PRICES_PER_MILLION = {
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else 0


def _cost(tokens_in: int, tokens_out: int, model: str, *, batch: bool) -> float:
    rates = STANDARD_PRICES_PER_MILLION[model]
    multiplier = 0.5 if batch else 1.0
    return round(multiplier * (tokens_in * rates["input"] + tokens_out * rates["output"]) / 1_000_000, 6)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 9 ETH analysis dry-run (no API calls)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--asset", default="ETH", choices=["ETH"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=settings.openai_analysis_model)
    parser.add_argument("--max-cost-usd", type=float, default=10.0)
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--include-explanation", action="store_true")
    parser.add_argument("--prompt-version", default=PROMPT_VERSION)
    args = parser.parse_args()

    if not args.dry_run:
        parser.error("Paid/API analysis is disabled. Run with --dry-run; explicit approval is required for API use.")
    if args.include_explanation:
        parser.error("--include-explanation is debug-only and is not enabled for the full dry-run.")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with session_scope() as session:
        repository = AnalysisRepository(session)
        candidates = repository.get_eth_news_candidates(limit=args.limit)
        successful_ids = repository.get_successful_analysis_ids(args.model, args.prompt_version)

        source_counts = Counter(article.source for article in candidates)
        year_counts = Counter(str(article.published_at.year) for article in candidates)
        event_counts = Counter(article.event_group_id or "ungrouped" for article in candidates)
        multi_asset = sum(1 for article in candidates if len({asset.symbol for asset in article.assets}) > 1)
        eth_article_assets = sum(
            1 for article in candidates for asset in article.assets
            if asset.asset.upper() == "ETH" or asset.symbol.upper() == "ETHUSDT"
        )
        already_analyzed = sum(article.id in successful_ids for article in candidates)

        selection_rows: list[dict[str, Any]] = []
        for article in candidates:
            selection_rows.append({
                "news_id": article.id,
                "source": article.source,
                "published_year": article.published_at.year,
                "event_group_id": article.event_group_id or "",
                "assets": ",".join(sorted({asset.asset for asset in article.assets})),
                "symbols": ",".join(sorted({asset.symbol for asset in article.assets})),
                "already_analyzed": article.id in successful_ids,
            })

        selection = {
            "asset_focus": args.asset,
            "model": args.model,
            "prompt_version": args.prompt_version,
            "total_eth_article_assets": eth_article_assets,
            "unique_eth_news_ids": len(candidates),
            "multi_asset_news": multi_asset,
            "distinct_event_groups": len({a.event_group_id for a in candidates if a.event_group_id}),
            "articles_by_source": dict(sorted(source_counts.items())),
            "articles_by_year": dict(sorted(year_counts.items())),
            "articles_by_event_group_id": dict(sorted(event_counts.items())),
            "already_analyzed": already_analyzed,
            "unprocessed": len(candidates) - already_analyzed,
        }
        _write_json(REPORTS_DIR / "stage9_eth_selection.json", selection)
        _write_csv(
            REPORTS_DIR / "stage9_eth_selection.csv",
            selection_rows,
            ["news_id", "source", "published_year", "event_group_id", "assets", "symbols", "already_analyzed"],
        )

        token_rows: list[dict[str, Any]] = []
        prepared_records: list[dict[str, Any]] = []
        for article in candidates:
            details = prepare_eth_analysis_input_details(article, settings.openai_max_article_tokens)
            compact_input = str(details["input"])
            assert_no_data_leakage(SYSTEM_PROMPT + "\n" + compact_input)
            input_tokens = count_request_input_tokens(compact_input)
            output_tokens = settings.openai_max_output_tokens
            row = {
                "news_id": article.id,
                "source": article.source,
                "title": article.title,
                "input_tokens": input_tokens,
                "estimated_output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "truncated": bool(details["truncated"]),
                "full_article_input_tokens": int(details["full_tokens"]),
            }
            token_rows.append(row)
            prepared_records.append({**row, "input": compact_input})

        _write_csv(
            REPORTS_DIR / "stage9_eth_token_stats.csv",
            token_rows,
            ["news_id", "source", "title", "input_tokens", "estimated_output_tokens", "total_tokens", "truncated", "full_article_input_tokens"],
        )

        input_values = [int(row["input_tokens"]) for row in token_rows]
        total_input = sum(input_values)
        total_output = sum(int(row["estimated_output_tokens"]) for row in token_rows)
        longest = sorted(prepared_records, key=lambda row: row["input_tokens"], reverse=True)[:20]
        cost_report = {
            "dry_run": True,
            "api_requests_made": 0,
            "articles": len(candidates),
            "batch_requests": len(candidates),
            "input_token_stats": {
                "average": round(statistics.mean(input_values), 2) if input_values else 0,
                "median": round(statistics.median(input_values), 2) if input_values else 0,
                "p95": _percentile(input_values, 0.95),
                "max": max(input_values, default=0),
            },
            "estimated_total_input_tokens": total_input,
            "estimated_total_output_tokens": total_output,
            "estimated_total_tokens": total_input + total_output,
            "truncated_articles": sum(bool(row["truncated"]) for row in token_rows),
            "prices_usd_per_1m_standard": STANDARD_PRICES_PER_MILLION,
            "estimated_cost_usd": {
                model: {
                    "standard": _cost(total_input, total_output, model, batch=False),
                    "batch": _cost(total_input, total_output, model, batch=True),
                }
                for model in STANDARD_PRICES_PER_MILLION
            },
            "longest_20_inputs": [
                {"news_id": row["news_id"], "title": row["title"], "input_tokens": row["input_tokens"]}
                for row in longest
            ],
            "tokenizer": "tiktoken:o200k_base",
            "output_estimate_basis": f"configured maximum of {settings.openai_max_output_tokens} tokens per article",
        }
        if cost_report["estimated_cost_usd"][args.model]["batch" if args.batch else "standard"] > args.max_cost_usd:
            raise SystemExit("Estimated cost exceeds --max-cost-usd; no API request was made.")
        _write_json(REPORTS_DIR / "stage9_eth_cost_estimate.json", cost_report)

        preview = [
            {
                "custom_id": f"eth-{row['news_id']}-{args.prompt_version}",
                "news_id": row["news_id"],
                "model": args.model,
                "prompt_version": args.prompt_version,
                "system_prompt": SYSTEM_PROMPT,
                "input": row["input"],
                "json_schema": analysis_json_schema(),
                "input_tokens": row["input_tokens"],
                "estimated_output_tokens": row["estimated_output_tokens"],
            }
            for row in prepared_records[:5]
        ]
        _write_json(REPORTS_DIR / "stage9_eth_input_preview.json", preview)

    print(json.dumps({
        "status": "PASS",
        "dry_run": True,
        "api_requests_made": 0,
        "unique_eth_news_ids": selection["unique_eth_news_ids"],
        "already_analyzed": selection["already_analyzed"],
        "unprocessed": selection["unprocessed"],
        "input_token_stats": cost_report["input_token_stats"],
        "estimated_total_input_tokens": cost_report["estimated_total_input_tokens"],
        "estimated_total_output_tokens": cost_report["estimated_total_output_tokens"],
        "truncated_articles": cost_report["truncated_articles"],
        "estimated_cost_usd": cost_report["estimated_cost_usd"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
