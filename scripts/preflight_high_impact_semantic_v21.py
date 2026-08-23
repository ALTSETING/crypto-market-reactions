"""Stage 16 semantic v2.1 offline preflight. Never creates/uploads JSONL or calls an API."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from database.db import session_scope
from high_impact_sources.analysis.ai_analyzer import (
    PRICES,
    SEMANTIC_V2_SYSTEM_PROMPT,
    SEMANTIC_V21_SYSTEM_PROMPT,
    compact_input,
    compact_input_v21,
    compact_input_v21_stats,
    dry_run_row,
    leakage_fields,
    representative_output_tokens,
    schema_predictive_fields,
    strict_schema_issues,
)
from high_impact_sources.config import PROMPT_VERSION, REPORTS
from high_impact_sources.schemas import SEMANTIC_V2_SCHEMA, build_semantic_v21_schema

V2_PROMPT_VERSION = "high_impact_semantic_v2"
EXPECTED_EVENTS = 714


def token_stats(frame: pd.DataFrame) -> dict:
    return {
        "total": int(frame.input_tokens.sum()),
        "average": float(frame.input_tokens.mean()),
        "median": float(frame.input_tokens.median()),
        "p95": float(frame.input_tokens.quantile(0.95)),
        "max": int(frame.input_tokens.max()),
    }


def costs(input_tokens: int, output_tokens: int) -> dict:
    return {
        model: input_tokens / 1_000_000 * rates["input"]
        + output_tokens / 1_000_000 * rates["output"]
        for model, rates in PRICES.items()
    }


def schema_fields(schema: dict) -> dict:
    top = set(schema["schema"]["properties"])
    asset = set(schema["schema"]["properties"]["assets"]["items"]["properties"])
    return {"top_level": len(top), "asset_block": len(asset), "total": len(top) + len(asset)}


def file_hashes(paths: list[Path]) -> dict:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
        if path.exists()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--model", default="gpt-5-mini", choices=tuple(PRICES))
    parser.add_argument("--max-body-tokens", type=int, default=900)
    parser.add_argument("--include-reason", action="store_true", default=False)
    args = parser.parse_args()

    if PROMPT_VERSION != "high_impact_semantic_v2_1":
        raise RuntimeError(f"Unexpected prompt version: {PROMPT_VERSION}")

    with session_scope() as session:
        rows = session.execute(text(
            "SELECT id,source,source_type,platform,author_name,published_at,title,body "
            "FROM high_impact_events WHERE status='accepted' ORDER BY id"
        )).mappings().all()

    class Obj:
        def __init__(self, data):
            self.__dict__.update(data)
            self.assets = []

    objects = [Obj(dict(row)) for row in rows]
    schema_v21 = build_semantic_v21_schema(args.include_reason)
    output_v2 = representative_output_tokens("v2")
    output_v21 = representative_output_tokens("v21", args.include_reason)
    v21_builder = lambda row: compact_input_v21(row, args.max_body_tokens)

    v2 = pd.DataFrame([
        dry_run_row(row, args.model, output_v2, schema=SEMANTIC_V2_SCHEMA,
                    system_prompt=SEMANTIC_V2_SYSTEM_PROMPT,
                    prompt_version=V2_PROMPT_VERSION, input_builder=compact_input)
        for row in objects
    ])
    v21 = pd.DataFrame([
        dry_run_row(row, args.model, output_v21, schema=schema_v21,
                    system_prompt=SEMANTIC_V21_SYSTEM_PROMPT,
                    prompt_version=PROMPT_VERSION, input_builder=v21_builder)
        for row in objects
    ])
    resumed = pd.DataFrame([
        dry_run_row(row, args.model, output_v21, schema=schema_v21,
                    system_prompt=SEMANTIC_V21_SYSTEM_PROMPT,
                    prompt_version=PROMPT_VERSION, input_builder=v21_builder)
        for row in objects
    ])

    v2_stats = token_stats(v2)
    v21_stats = token_stats(v21)
    v2_output_total = len(v2) * output_v2
    v21_output_total = len(v21) * output_v21
    v2_costs = costs(v2_stats["total"], v2_output_total)
    v21_costs = costs(v21_stats["total"], v21_output_total)
    v2_top = set(SEMANTIC_V2_SCHEMA["schema"]["properties"])
    v21_top = set(schema_v21["schema"]["properties"])
    v2_asset = set(SEMANTIC_V2_SCHEMA["schema"]["properties"]["assets"]["items"]["properties"])
    v21_asset = set(schema_v21["schema"]["properties"]["assets"]["items"]["properties"])
    resume_ok = v21.input_hash.tolist() == resumed.input_hash.tolist()
    body_stats = [compact_input_v21_stats(row, args.max_body_tokens) for row in objects]
    truncated_count = sum(item["body_truncated"] for item in body_stats)

    decisions = {
        "new_information_ratio": {
            "decision": "removed",
            "reason": "Strong semantic overlap with novelty; a reliable ratio needs a comparison corpus, not one isolated message.",
            "evidence_type": "schema_identifiability_review",
        },
        "ecosystem_impact": {
            "decision": "removed",
            "reason": "Overlaps importance plus economic, technical, adoption, and fundamental significance scores.",
            "evidence_type": "schema_identifiability_review",
        },
        "empirical_correlation_available": False,
        "note": "Stage 16 v2 has offline dry-run metadata only; no model outputs exist, so empirical score correlations were not fabricated.",
    }
    comparison = {
        "status": "PASS" if not strict_schema_issues(schema_v21) else "FAIL",
        "mode": "offline_dry_run_comparison",
        "events": len(v21),
        "api_requests": 0,
        "jsonl_created": False,
        "jsonl_uploaded": False,
        "batch_submitted": False,
        "include_reason": args.include_reason,
        "max_body_tokens": args.max_body_tokens,
        "v2": {
            "prompt_version": V2_PROMPT_VERSION,
            "input_tokens": v2_stats,
            "estimated_output_tokens_per_event": output_v2,
            "estimated_output_tokens_total": v2_output_total,
            "estimated_batch_cost_usd": v2_costs,
            "schema_valid": not strict_schema_issues(SEMANTIC_V2_SCHEMA),
            "field_counts": schema_fields(SEMANTIC_V2_SCHEMA),
        },
        "v2_1": {
            "prompt_version": PROMPT_VERSION,
            "input_tokens": v21_stats,
            "estimated_output_tokens_per_event": output_v21,
            "estimated_output_tokens_total": v21_output_total,
            "estimated_batch_cost_usd": v21_costs,
            "schema_valid": not strict_schema_issues(schema_v21),
            "field_counts": schema_fields(schema_v21),
        },
        "delta_v2_1_minus_v2": {
            "input_tokens_total": v21_stats["total"] - v2_stats["total"],
            "average_input_tokens": v21_stats["average"] - v2_stats["average"],
            "median_input_tokens": v21_stats["median"] - v2_stats["median"],
            "p95_input_tokens": v21_stats["p95"] - v2_stats["p95"],
            "max_input_tokens": v21_stats["max"] - v2_stats["max"],
            "estimated_output_tokens_total": v21_output_total - v2_output_total,
            "estimated_batch_cost_usd": {model: v21_costs[model] - v2_costs[model] for model in PRICES},
        },
        "removed_top_level_fields": sorted(v2_top - v21_top),
        "removed_asset_fields": sorted(v2_asset - v21_asset),
        "added_fields": sorted(v21_top - v2_top),
        "changed_fields": {
            "first_disclosure": {"from": "boolean", "to": "yes|no|unclear"},
            "surprise_level": {"from": "integer", "to": "integer|null"},
            "surprise_evidence": {"from": "absent", "to": "sufficient|insufficient"},
        },
        "redundancy_decisions": decisions,
    }

    preserved = [REPORTS / name for name in (
        "stage16_semantic_v1_vs_v2.json",
        "stage16_semantic_v2_preflight.json",
        "stage16_ai_semantic_v2_results.csv",
        "stage16_ai_semantic_v1_dryrun_comparator.csv",
        "stage16_high_impact_semantic_v2_preflight.jsonl",
    )]
    leakage_count = int(v21.leakage.sum()) if len(v21) else 0
    predictive = schema_predictive_fields(schema_v21)
    issues = strict_schema_issues(schema_v21)
    targets = {
        "average_input_tokens_lte_1200": v21_stats["average"] <= 1200,
        "p95_input_tokens_lte_2000": v21_stats["p95"] <= 2000,
        "strict_schema_issues_zero": len(issues) == 0,
        "predictive_fields_zero": len(predictive) == 0,
        "leakage_zero": leakage_count == 0,
    }
    hard_pass = (
        len(v21) == EXPECTED_EVENTS and all(targets.values()) and resume_ok
        and not args.include_reason
    )
    preflight = {
        "status": "PASS" if hard_pass else "FAIL",
        "prompt_version": PROMPT_VERSION,
        "mode": "offline_dry_run",
        "events_expected": EXPECTED_EVENTS,
        "events_processed": len(v21),
        "model_for_estimate": args.model,
        "api_requests": 0,
        "jsonl_created": False,
        "jsonl_uploaded": False,
        "batch_submitted": False,
        "include_reason": args.include_reason,
        "system_prompt": SEMANTIC_V21_SYSTEM_PROMPT,
        "system_prompt_tokens": len(__import__("tiktoken").get_encoding("o200k_base").encode(SEMANTIC_V21_SYSTEM_PROMPT)),
        "input_tokens": v21_stats,
        "body_truncation": {"max_body_tokens": args.max_body_tokens,
                            "events_truncated": truncated_count,
                            "fraction": truncated_count / len(objects) if objects else 0},
        "estimated_output_tokens_per_event": output_v21,
        "estimated_output_tokens_total": v21_output_total,
        "estimated_batch_cost_usd": v21_costs,
        "schema_name": schema_v21["name"],
        "schema_valid": len(issues) == 0,
        "strict_schema_issues": issues,
        "predictive_fields": predictive,
        "leakage_violations": leakage_count,
        "resume_deterministic": resume_ok,
        "duplicate_dry_run_requests": 0,
        "targets": targets,
        "nullable_evidence_aware": {
            "surprise_level": ["integer", "null"],
            "surprise_evidence": ["sufficient", "insufficient"],
            "consistency_validation": True,
        },
        "reason_mode": "CLI --include-reason only; disabled for this mass-mode preflight",
        "preserved_v1_v2_artifact_hashes": file_hashes(preserved),
        "redundancy_decisions": decisions,
        "comparison_report": "stage16_semantic_v21_comparison.json",
    }

    previews = []
    for row in objects[:5]:
        payload = compact_input_v21(row, args.max_body_tokens)
        previews.append({
            "event_id": row.id,
            "source": row.source,
            "title": row.title,
            **compact_input_v21_stats(row, args.max_body_tokens),
            "input_hash": hashlib.sha256((SEMANTIC_V21_SYSTEM_PROMPT + payload + json.dumps(schema_v21, separators=(",", ":"))).encode()).hexdigest(),
            "compact_input": json.loads(payload),
            "leakage_fields": leakage_fields(payload),
        })
    preview_report = {
        "prompt_version": PROMPT_VERSION,
        "mode": "offline_preview",
        "api_requests": 0,
        "include_reason": args.include_reason,
        "sample_size": len(previews),
        "samples": previews,
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "stage16_semantic_v21_comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "stage16_semantic_v21_preflight.json").write_text(json.dumps(preflight, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "stage16_semantic_v21_input_preview.json").write_text(json.dumps(preview_report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"preflight": preflight, "comparison": comparison}, ensure_ascii=False))


if __name__ == "__main__":
    main()
