"""Stage 9 paid A/B helpers with deterministic sampling and strict budget guards."""

from __future__ import annotations

import hashlib
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, ConfigDict, Field

from analysis.openai_analyzer import (
    CATEGORY_VALUES,
    DIRECTION_VALUES,
    HORIZON_VALUES,
    SYSTEM_PROMPT,
    assert_no_data_leakage,
    count_request_input_tokens,
    estimate_token_count,
    prepare_eth_analysis_input,
    validate_analysis_payload,
)

NANO_MODEL_ID = "gpt-5-nano-2025-08-07"
MINI_MODEL_ID = "gpt-5-mini-2025-08-07"
MODEL_IDS = (NANO_MODEL_ID, MINI_MODEL_ID)
PRICES_PER_MILLION = {
    NANO_MODEL_ID: {"input": 0.05, "output": 0.40},
    MINI_MODEL_ID: {"input": 0.25, "output": 2.00},
}


class EthAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentiment: int = Field(ge=-100, le=100)
    importance: int = Field(ge=0, le=100)
    novelty: int = Field(ge=0, le=100)
    credibility: int = Field(ge=0, le=100)
    direction: Literal[tuple(DIRECTION_VALUES)]  # type: ignore[valid-type]
    category: Literal[tuple(CATEGORY_VALUES)]  # type: ignore[valid-type]
    horizon: Literal[tuple(HORIZON_VALUES)]  # type: ignore[valid-type]
    confidence: int = Field(ge=0, le=100)
    eth_relevance: int = Field(ge=0, le=100)


@dataclass(frozen=True)
class PreparedArticle:
    news_id: int
    title: str
    input_text: str
    input_hash: str
    estimated_input_tokens: int


def deterministic_sample(articles: list[Any], sample_size: int, seed: int) -> list[Any]:
    if sample_size <= 0 or sample_size > len(articles):
        raise ValueError("sample_size must be between 1 and the candidate count")
    chosen = random.Random(seed).sample(sorted(articles, key=lambda article: article.id), sample_size)
    return sorted(chosen, key=lambda article: article.id)


def prepare_sample(articles: list[Any], max_article_tokens: int) -> list[PreparedArticle]:
    prepared: list[PreparedArticle] = []
    for article in articles:
        input_text = prepare_eth_analysis_input(article, max_tokens=max_article_tokens)
        assert_no_data_leakage(SYSTEM_PROMPT + "\n" + input_text)
        prepared.append(
            PreparedArticle(
                news_id=article.id,
                title=article.title,
                input_text=input_text,
                input_hash=hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
                estimated_input_tokens=count_request_input_tokens(input_text),
            )
        )
    return prepared


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    rates = PRICES_PER_MILLION[model_id]
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


def build_preflight(
    prepared: list[PreparedArticle],
    *,
    prompt_version: str,
    seed: int,
    max_output_tokens: int,
    max_cost_usd: float,
) -> dict[str, Any]:
    schema = EthAnalysisPayload.model_json_schema()
    schema_tokens_per_request = estimate_token_count(
        json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
    ) + 8
    total_input = sum(
        item.estimated_input_tokens + schema_tokens_per_request for item in prepared
    )
    total_output_per_model = len(prepared) * max_output_tokens
    model_estimates = {
        model_id: {
            "requests": len(prepared),
            "estimated_input_tokens": total_input,
            "estimated_output_tokens": total_output_per_model,
            "estimated_cost_usd": round(
                estimate_cost(model_id, total_input, total_output_per_model), 8
            ),
        }
        for model_id in MODEL_IDS
    }
    estimated_total = sum(value["estimated_cost_usd"] for value in model_estimates.values())
    if estimated_total > max_cost_usd:
        raise ValueError(
            f"Estimated A/B cost ${estimated_total:.8f} exceeds budget ${max_cost_usd:.8f}"
        )
    return {
        "status": "PREFLIGHT_PASS",
        "api_requests_made": 0,
        "sample_seed": seed,
        "sample_size": len(prepared),
        "news_ids": [item.news_id for item in prepared],
        "input_hashes": {str(item.news_id): item.input_hash for item in prepared},
        "prompt_version": prompt_version,
        "model_ids": list(MODEL_IDS),
        "max_article_tokens": 900,
        "max_output_tokens": max_output_tokens,
        "system_prompt": SYSTEM_PROMPT,
        "json_schema": schema,
        "estimated_schema_tokens_per_request": schema_tokens_per_request,
        "model_estimates": model_estimates,
        "estimated_total_cost_usd": round(estimated_total, 8),
        "max_cost_usd": max_cost_usd,
    }


def _is_retryable(error: Exception) -> bool:
    return isinstance(error, (RateLimitError, APIConnectionError, APITimeoutError)) or (
        isinstance(error, APIStatusError) and error.status_code >= 500
    )


def analyze_one(
    client: OpenAI,
    item: PreparedArticle,
    model_id: str,
    max_output_tokens: int,
    max_retries: int = 3,
) -> dict[str, Any]:
    retries = 0
    started = time.perf_counter()
    while True:
        try:
            response = client.responses.parse(
                model=model_id,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": item.input_text},
                ],
                text_format=EthAnalysisPayload,
                reasoning={"effort": "minimal"},
                max_output_tokens=max_output_tokens,
                store=False,
                timeout=90.0,
            )
            latency = time.perf_counter() - started
            usage = response.usage
            payload_model = response.output_parsed
            payload = payload_model.model_dump() if payload_model is not None else None
            schema_ok = payload is not None and validate_analysis_payload(payload)
            status = "success" if schema_ok else ("refused" if not response.output_text else "invalid_schema")
            input_tokens = int(usage.input_tokens if usage else 0)
            output_tokens = int(usage.output_tokens if usage else 0)
            total_tokens = int(usage.total_tokens if usage else input_tokens + output_tokens)
            return {
                "news_id": item.news_id,
                "title": item.title,
                "model_name": model_id,
                "input_hash": item.input_hash,
                "input_excerpt": item.input_text[:500],
                "status": status,
                "schema_status": "valid" if schema_ok else status,
                "structured_response": payload,
                "raw_response": response.model_dump(mode="json"),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "actual_cost_usd": round(estimate_cost(model_id, input_tokens, output_tokens), 8),
                "latency_seconds": round(latency, 4),
                "retries": retries,
                "error_message": None,
            }
        except Exception as error:
            if retries < max_retries and _is_retryable(error):
                time.sleep(2**retries)
                retries += 1
                continue
            return {
                "news_id": item.news_id,
                "title": item.title,
                "model_name": model_id,
                "input_hash": item.input_hash,
                "input_excerpt": item.input_text[:500],
                "status": "api_error",
                "schema_status": "not_received",
                "structured_response": None,
                "raw_response": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "actual_cost_usd": 0.0,
                "latency_seconds": round(time.perf_counter() - started, 4),
                "retries": retries,
                "error_message": f"{type(error).__name__}: {error}",
            }


def run_requests(
    api_key: str,
    prepared: list[PreparedArticle],
    *,
    max_output_tokens: int,
    workers: int = 4,
    existing_results: list[dict[str, Any]] | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    client = OpenAI(api_key=api_key, max_retries=0)
    results: list[dict[str, Any]] = list(existing_results or [])
    existing_keys = {(row["news_id"], row["model_name"]) for row in results}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(analyze_one, client, item, model_id, max_output_tokens): (item, model_id)
            for model_id in MODEL_IDS
            for item in prepared
            if (item.news_id, model_id) not in existing_keys
        }
        for future in as_completed(futures):
            result = future.result()
            if on_result is not None:
                on_result(result)
            results.append(result)
    return sorted(results, key=lambda row: (row["news_id"], row["model_name"]))


def result_envelope(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
