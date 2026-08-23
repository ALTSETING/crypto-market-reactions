"""Controlled, resumable 30-event Stage 11 enrichment A/B evaluation."""

from __future__ import annotations

import hashlib
import json
import random
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Literal

import numpy as np
import pandas as pd
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, ConfigDict, Field

from analysis.openai_analyzer import estimate_token_count, prepare_eth_analysis_input
from analysis.stage11_enrichment import FORBIDDEN, SYSTEM_PROMPT, assert_enrichment_no_leakage

MINI_MODEL_ID = "gpt-5-mini-2025-08-07"
NANO_MODEL_ID = "gpt-5-nano-2025-08-07"
MODEL_IDS = (MINI_MODEL_ID, NANO_MODEL_ID)
PROMPT_VERSION = "eth_market_context_v1"
SAMPLE_SIZE = 30
SAMPLE_SEED = 20260718
MAX_OUTPUT_TOKENS = 180
PRICES_PER_MILLION = {
    MINI_MODEL_ID: {"input": 0.25, "output": 2.00},
    NANO_MODEL_ID: {"input": 0.05, "output": 0.40},
}
NUMERIC_FIELDS = (
    "surprise_magnitude", "expected_by_market", "already_priced_in",
    "information_freshness", "primary_source_probability", "actionable_novelty",
    "event_specificity", "confidence",
)


class EnrichmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surprise_direction: Literal["positive", "negative", "neutral", "mixed"]
    surprise_magnitude: int = Field(ge=0, le=100)
    expected_by_market: int = Field(ge=0, le=100)
    already_priced_in: int = Field(ge=0, le=100)
    information_freshness: int = Field(ge=0, le=100)
    primary_source_probability: int = Field(ge=0, le=100)
    actionable_novelty: int = Field(ge=0, le=100)
    event_specificity: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)


@dataclass(frozen=True)
class PreparedEvent:
    event_key: str
    news_id: int
    title: str
    input_text: str
    input_hash: str
    estimated_input_tokens: int


def _one_hot_value(row: pd.Series, prefix: str, fallback: str = "unknown") -> str:
    matches = [column[len(prefix):] for column in row.index if column.startswith(prefix) and row[column] == 1]
    return matches[0] if matches else fallback


def build_sample_frame(raw_events: pd.DataFrame, dataset: pd.DataFrame, *, seed: int = SAMPLE_SEED,
                       sample_size: int = SAMPLE_SIZE) -> pd.DataFrame:
    """Greedy inverse-frequency coverage sample; future returns remain selection metadata only."""
    target_columns = [column for column in dataset if column.startswith("target_abs_abnormal_return_")]
    base = dataset[["metadata_news_id", "metadata_event_key", *target_columns]].copy()
    base["reaction_magnitude"] = base[target_columns].max(axis=1)
    direction_columns = [column for column in dataset if column.startswith("ai9_direction_")]
    category_columns = [column for column in dataset if column.startswith("ai9_category_")]
    decoded = pd.DataFrame({
        "stage9_direction": dataset[direction_columns].idxmax(axis=1).str.removeprefix("ai9_direction_"),
        "stage9_category": dataset[category_columns].idxmax(axis=1).str.removeprefix("ai9_category_"),
        "stage9_importance": dataset["ai9_importance"].astype(float),
    })
    base = pd.concat([base.reset_index(drop=True), decoded.reset_index(drop=True)], axis=1)
    source = raw_events[["news_id", "source", "published_at"]].drop_duplicates("news_id")
    candidates = base.merge(source, left_on="metadata_news_id", right_on="news_id", how="inner")
    candidates["year"] = pd.to_datetime(candidates["published_at"], utc=True).dt.year
    candidates["importance_band"] = pd.cut(
        candidates["stage9_importance"], [-1, 20, 40, 60, 80, 100],
        labels=["00-20", "21-40", "41-60", "61-80", "81-100"],
    ).astype(str)
    candidates["reaction_band"] = pd.qcut(
        candidates["reaction_magnitude"].rank(method="first"), 5,
        labels=["q1", "q2", "q3", "q4", "q5"],
    ).astype(str)
    strata = ["year", "source", "stage9_direction", "importance_band", "stage9_category", "reaction_band"]
    frequencies = {column: candidates[column].value_counts().to_dict() for column in strata}
    rng = random.Random(seed)
    jitter = {int(news_id): rng.random() for news_id in candidates.metadata_news_id}
    covered = {column: Counter() for column in strata}
    chosen: list[int] = []
    remaining = set(candidates.index.tolist())
    while len(chosen) < sample_size:
        def score(index: int) -> tuple[float, float, int]:
            row = candidates.loc[index]
            coverage = sum(
                (4.0 if covered[column][row[column]] == 0 else 1.0 / (covered[column][row[column]] + 1))
                / np.sqrt(frequencies[column][row[column]])
                for column in strata
            )
            return coverage, jitter[int(row.metadata_news_id)], -int(row.metadata_news_id)
        winner = max(remaining, key=score)
        chosen.append(winner)
        remaining.remove(winner)
        for column in strata:
            covered[column][candidates.at[winner, column]] += 1
    result = candidates.loc[chosen].copy().drop(columns=["news_id"])
    result = result.rename(columns={"metadata_event_key": "event_key", "metadata_news_id": "news_id"})
    columns = ["event_key", "news_id", "published_at", "year", "source", "stage9_direction",
               "stage9_importance", "importance_band", "stage9_category", "reaction_magnitude", "reaction_band"]
    return result[columns].sort_values(["year", "source", "news_id"], kind="mergesort").reset_index(drop=True)


def prepare_events(sample: pd.DataFrame, raw_events: pd.DataFrame, max_article_tokens: int = 900) -> list[PreparedEvent]:
    lookup = raw_events.drop_duplicates("news_id").set_index("news_id")
    schema_tokens = estimate_token_count(json.dumps(EnrichmentPayload.model_json_schema(), separators=(",", ":"))) + 8
    prepared: list[PreparedEvent] = []
    for sample_row in sample.itertuples(index=False):
        article = lookup.loc[int(sample_row.news_id)]
        input_text = prepare_eth_analysis_input(
            {"title": article.title, "body": article.body}, max_tokens=max_article_tokens,
        )
        assert_enrichment_no_leakage(SYSTEM_PROMPT + "\n" + input_text)
        prepared.append(PreparedEvent(
            event_key=str(sample_row.event_key), news_id=int(sample_row.news_id), title=str(article.title),
            input_text=input_text,
            input_hash=hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
            estimated_input_tokens=estimate_token_count(SYSTEM_PROMPT) + estimate_token_count(input_text) + schema_tokens + 8,
        ))
    return prepared


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    rates = PRICES_PER_MILLION[model_id]
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


def build_preflight(prepared: list[PreparedEvent], *, seed: int, max_cost_usd: float) -> dict[str, Any]:
    identities = [f"{item.news_id}:{model}:{PROMPT_VERSION}" for model in MODEL_IDS for item in prepared]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate API request identity detected")
    leakage_hits = [field for field in FORBIDDEN if any(field.casefold() in item.input_text.casefold() for item in prepared)]
    estimates = {}
    for model in MODEL_IDS:
        input_tokens = sum(item.estimated_input_tokens for item in prepared)
        output_tokens = len(prepared) * MAX_OUTPUT_TOKENS
        estimates[model] = {
            "requests": len(prepared), "estimated_input_tokens": input_tokens,
            "estimated_output_tokens_upper_bound": output_tokens,
            "estimated_cost_usd_upper_bound": round(estimate_cost(model, input_tokens, output_tokens), 8),
        }
    total = sum(row["estimated_cost_usd_upper_bound"] for row in estimates.values())
    if total > max_cost_usd:
        raise ValueError(f"Estimated cost ${total:.8f} exceeds budget ${max_cost_usd:.8f}")
    return {
        "status": "PREFLIGHT_PASS", "api_requests_made": 0, "sample_seed": seed,
        "sample_size": len(prepared), "news_ids": [item.news_id for item in prepared],
        "event_keys": [item.event_key for item in prepared],
        "input_hashes": {str(item.news_id): item.input_hash for item in prepared},
        "models": list(MODEL_IDS), "prompt_version": PROMPT_VERSION,
        "system_prompt": SYSTEM_PROMPT, "json_schema": EnrichmentPayload.model_json_schema(),
        "max_output_tokens": MAX_OUTPUT_TOKENS, "model_estimates": estimates,
        "estimated_total_cost_usd_upper_bound": round(total, 8), "max_cost_usd": max_cost_usd,
        "leakage_count": len(leakage_hits), "leakage_fields": sorted(leakage_hits),
        "request_identity_count": len(identities), "unique_request_identity_count": len(set(identities)),
        "reaction_fields_in_api_input": 0,
    }


def _retryable(error: Exception) -> bool:
    return isinstance(error, (RateLimitError, APIConnectionError, APITimeoutError)) or (
        isinstance(error, APIStatusError) and error.status_code >= 500
    )


def analyze_one(client: OpenAI, item: PreparedEvent, model_id: str, max_retries: int = 3) -> dict[str, Any]:
    retries, started = 0, time.perf_counter()
    while True:
        try:
            response = client.responses.parse(
                model=model_id,
                input=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": item.input_text}],
                text_format=EnrichmentPayload, reasoning={"effort": "minimal"},
                max_output_tokens=MAX_OUTPUT_TOKENS, store=False, timeout=90.0,
            )
            payload_model = response.output_parsed
            payload = payload_model.model_dump() if payload_model is not None else None
            status = "success" if payload is not None else ("refused" if not response.output_text else "invalid_schema")
            usage = response.usage
            input_tokens = int(usage.input_tokens if usage else 0)
            output_tokens = int(usage.output_tokens if usage else 0)
            return {
                "event_key": item.event_key, "news_id": item.news_id, "title": item.title,
                "model_name": model_id, "prompt_version": PROMPT_VERSION, "input_hash": item.input_hash,
                "status": status, "schema_status": "valid" if status == "success" else status,
                "structured_response": payload,
                "raw_response": response.model_dump(mode="json", warnings=False),
                "input_tokens": input_tokens, "output_tokens": output_tokens,
                "total_tokens": int(usage.total_tokens if usage else input_tokens + output_tokens),
                "actual_cost_usd": round(estimate_cost(model_id, input_tokens, output_tokens), 8),
                "latency_seconds": round(time.perf_counter() - started, 4), "retries": retries,
                "error_message": None,
            }
        except Exception as error:
            if retries < max_retries and _retryable(error):
                time.sleep(2 ** retries); retries += 1; continue
            return {
                "event_key": item.event_key, "news_id": item.news_id, "title": item.title,
                "model_name": model_id, "prompt_version": PROMPT_VERSION, "input_hash": item.input_hash,
                "status": "api_error", "schema_status": "not_received", "structured_response": None,
                "raw_response": None, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "actual_cost_usd": 0.0, "latency_seconds": round(time.perf_counter() - started, 4),
                "retries": retries, "error_message": f"{type(error).__name__}: {error}",
            }


def run_requests(api_key: str, prepared: list[PreparedEvent], *, existing_results: list[dict[str, Any]],
                 on_result: Callable[[dict[str, Any]], None], workers: int = 4) -> tuple[list[dict[str, Any]], int]:
    client = OpenAI(api_key=api_key, max_retries=0)
    valid_news = {item.news_id: item for item in prepared}
    results = [row for row in existing_results if row["news_id"] in valid_news and
               row.get("event_key") == valid_news[row["news_id"]].event_key and
               row.get("input_hash") == valid_news[row["news_id"]].input_hash]
    existing = {(row["news_id"], row["model_name"], row["prompt_version"]) for row in results if row["status"] == "success"}
    jobs = [(item, model) for model in MODEL_IDS for item in prepared
            if (item.news_id, model, PROMPT_VERSION) not in existing]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(analyze_one, client, item, model) for item, model in jobs]
        for future in as_completed(futures):
            row = future.result(); on_result(row); results.append(row)
    latest = {(row["news_id"], row["model_name"], row["prompt_version"]): row for row in results}
    return sorted(latest.values(), key=lambda row: (row["news_id"], row["model_name"])), len(jobs)


def compare_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for model in MODEL_IDS:
        rows = [row for row in results if row["model_name"] == model]
        good = [row for row in rows if row["status"] == "success"]
        payloads = [row["structured_response"] for row in good]
        scores = {}
        for field in NUMERIC_FIELDS:
            values = [payload[field] for payload in payloads]
            scores[field] = {
                "count": len(values), "mean": round(statistics.mean(values), 3) if values else None,
                "median": round(statistics.median(values), 3) if values else None,
                "std": round(statistics.pstdev(values), 3) if len(values) > 1 else 0,
                "min": min(values) if values else None, "max": max(values) if values else None,
                "unique_values": len(set(values)), "distribution": dict(sorted(Counter(values).items())),
            }
        correlation = pd.DataFrame(payloads)[list(NUMERIC_FIELDS)].corr().round(4).to_dict() if payloads else {}
        contradictions = {
            "high_priced_in_and_high_freshness": sum(p["already_priced_in"] >= 75 and p["information_freshness"] >= 75 for p in payloads),
            "low_confidence_but_extreme_surprise": sum(p["confidence"] <= 30 and p["surprise_magnitude"] >= 80 for p in payloads),
            "generic_but_highly_actionable": sum(p["event_specificity"] <= 25 and p["actionable_novelty"] >= 75 for p in payloads),
        }
        summaries[model] = {
            "success": len(good), "failed": len(rows) - len(good),
            "schema_success_rate": round(len(good) / len(rows), 4) if rows else 0,
            "actual_cost_usd": round(sum(row["actual_cost_usd"] for row in rows), 8),
            "input_tokens": sum(row["input_tokens"] for row in rows),
            "output_tokens": sum(row["output_tokens"] for row in rows),
            "retries": sum(row["retries"] for row in rows),
            "direction_distribution": dict(Counter(p["surprise_direction"] for p in payloads)),
            "score_statistics": scores, "pairwise_correlations": correlation,
            "contradictions": contradictions,
        }
    indexed = {(row["news_id"], row["model_name"]): row for row in results if row["status"] == "success"}
    differences = {field: [] for field in NUMERIC_FIELDS}; significant = []
    paired = 0
    for news_id in sorted({row["news_id"] for row in results}):
        mini, nano = indexed.get((news_id, MINI_MODEL_ID)), indexed.get((news_id, NANO_MODEL_ID))
        if not mini or not nano: continue
        paired += 1; a, b = mini["structured_response"], nano["structured_response"]
        for field in NUMERIC_FIELDS: differences[field].append(abs(a[field] - b[field]))
        if a["surprise_direction"] != b["surprise_direction"] or any(abs(a[f] - b[f]) >= 25 for f in NUMERIC_FIELDS):
            significant.append(news_id)
    mean_differences = {field: round(statistics.mean(values), 3) if values else None for field, values in differences.items()}
    # Technical winner only; human semantic review is an explicit unresolved gate.
    rank = lambda model: (summaries[model]["schema_success_rate"],
                          -sum(summaries[model]["contradictions"].values()),
                          statistics.mean(summaries[model]["score_statistics"][f]["std"] for f in NUMERIC_FIELDS))
    winner = max(MODEL_IDS, key=rank)
    systematic_errors = []
    for model in MODEL_IDS:
        neutral = summaries[model]["direction_distribution"].get("neutral", 0)
        if neutral / max(1, summaries[model]["success"]) >= 0.8:
            systematic_errors.append({
                "model": model, "issue": "strong_neutral_default_bias",
                "neutral_count": neutral, "sample_size": summaries[model]["success"],
            })
    if len(significant) / max(1, paired) >= 0.5:
        systematic_errors.append({
            "models": list(MODEL_IDS), "issue": "low_cross_model_stability",
            "significant_divergences": len(significant), "paired": paired,
        })
    return {
        "status": "A_B_COMPLETE", "models": summaries, "paired_successes": paired,
        "mean_absolute_score_differences": mean_differences,
        "significant_divergence_definition": "direction mismatch or any numeric score difference >=25",
        "significant_divergences": len(significant), "significant_divergence_news_ids": significant,
        "systematic_errors": systematic_errors, "technical_winner": winner,
        "actual_total_cost_usd": round(sum(row["actual_cost_usd"] for row in results), 8),
        "decision_gate": "NO-GO_PENDING_COMPLETED_HUMAN_REVIEW",
        "predictive_claim": "NOT_EVALUATED_ON_N30",
    }
