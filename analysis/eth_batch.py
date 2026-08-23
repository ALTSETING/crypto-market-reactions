"""Stage 9 ETH Batch API preparation, validation, and result parsing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from analysis.eth_ab_test import MINI_MODEL_ID, PreparedArticle
from analysis.openai_analyzer import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    analysis_json_schema,
    assert_no_data_leakage,
    count_request_input_tokens,
    estimate_token_count,
    prepare_eth_analysis_input,
    validate_analysis_payload,
)

MODEL_ID = MINI_MODEL_ID
ASSET_FOCUS = "ETH"
ENDPOINT = "/v1/responses"
BATCH_INPUT_PRICE_PER_MILLION = 0.125
BATCH_OUTPUT_PRICE_PER_MILLION = 1.0


@dataclass(frozen=True)
class BatchItem:
    news_id: int
    title: str
    input_text: str
    input_hash: str
    estimated_input_tokens: int
    attempt: int = 1

    @property
    def custom_id(self) -> str:
        return f"eth-{self.news_id}-v1-mini-20250807-a{self.attempt}"


def prepare_batch_items(articles: Iterable[Any], max_article_tokens: int) -> list[BatchItem]:
    result: list[BatchItem] = []
    for article in articles:
        input_text = prepare_eth_analysis_input(article, max_tokens=max_article_tokens)
        assert_no_data_leakage(SYSTEM_PROMPT + "\n" + input_text)
        result.append(BatchItem(
            news_id=article.id,
            title=article.title,
            input_text=input_text,
            input_hash=hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
            estimated_input_tokens=count_request_input_tokens(input_text),
        ))
    return result


def request_body(item: BatchItem, max_output_tokens: int) -> dict[str, Any]:
    body = {
        "model": MODEL_ID,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": item.input_text},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "eth_analysis",
                "strict": True,
                "schema": analysis_json_schema(include_explanation=False),
            }
        },
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": max_output_tokens,
        "store": False,
    }
    assert_no_data_leakage(json.dumps(body, ensure_ascii=False))
    return body


def request_line(item: BatchItem, max_output_tokens: int) -> dict[str, Any]:
    return {
        "custom_id": item.custom_id,
        "method": "POST",
        "url": ENDPOINT,
        "body": request_body(item, max_output_tokens),
    }


def validate_jsonl(lines: list[dict[str, Any]], expected_count: int) -> dict[str, Any]:
    custom_ids = [line.get("custom_id") for line in lines]
    leakage_failures: list[str] = []
    structural_failures: list[str] = []
    for line in lines:
        custom_id = str(line.get("custom_id"))
        try:
            assert_no_data_leakage(json.dumps(line, ensure_ascii=False))
        except ValueError:
            leakage_failures.append(custom_id)
        if (
            line.get("method") != "POST"
            or line.get("url") != ENDPOINT
            or line.get("body", {}).get("model") != MODEL_ID
            or line.get("body", {}).get("store") is not False
            or line.get("body", {}).get("text", {}).get("format", {}).get("strict") is not True
        ):
            structural_failures.append(custom_id)
    result = {
        "line_count": len(lines),
        "expected_count": expected_count,
        "unique_custom_ids": len(set(custom_ids)),
        "duplicate_custom_ids": len(custom_ids) - len(set(custom_ids)),
        "leakage_count": len(leakage_failures),
        "leakage_custom_ids": leakage_failures,
        "structural_failures": structural_failures,
        "valid": (
            len(lines) == expected_count
            and len(set(custom_ids)) == len(lines)
            and not leakage_failures
            and not structural_failures
        ),
    }
    return result


def estimate_batch(items: list[BatchItem], max_output_tokens: int) -> dict[str, Any]:
    schema_tokens = estimate_token_count(json.dumps(
        analysis_json_schema(False), separators=(",", ":"), ensure_ascii=False
    )) + 8
    input_tokens = sum(item.estimated_input_tokens + schema_tokens for item in items)
    output_tokens = len(items) * max_output_tokens
    cost = (
        input_tokens * BATCH_INPUT_PRICE_PER_MILLION
        + output_tokens * BATCH_OUTPUT_PRICE_PER_MILLION
    ) / 1_000_000
    return {
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_schema_tokens_per_request": schema_tokens,
        "estimated_batch_cost_usd": round(cost, 8),
        "pricing_usd_per_million": {
            "input": BATCH_INPUT_PRICE_PER_MILLION,
            "output": BATCH_OUTPUT_PRICE_PER_MILLION,
        },
    }


def extract_output_text(response_body: dict[str, Any]) -> str | None:
    for output in response_body.get("output", []):
        if output.get("type") != "message":
            continue
        for content in output.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text")
    return None


def extract_refusal(response_body: dict[str, Any]) -> str | None:
    for output in response_body.get("output", []):
        if output.get("type") != "message":
            continue
        for content in output.get("content", []):
            if content.get("type") == "refusal":
                return str(content.get("refusal") or "Model refusal")
    return None


def parse_batch_result(line: dict[str, Any], item_by_custom_id: dict[str, BatchItem]) -> dict[str, Any]:
    custom_id = str(line.get("custom_id", ""))
    item = item_by_custom_id.get(custom_id)
    if item is None:
        return {"custom_id": custom_id, "status": "unmatched", "error_message": "Unknown custom_id"}
    response = line.get("response") or {}
    body = response.get("body") or {}
    error = line.get("error") or body.get("error")
    usage = body.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    if error or response.get("status_code") != 200:
        return {
            "news_id": item.news_id, "custom_id": custom_id, "status": "api_error",
            "input_hash": item.input_hash, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
            "payload": None, "error_message": json.dumps(error or body, ensure_ascii=False),
        }
    refusal = extract_refusal(body)
    if refusal:
        return {
            "news_id": item.news_id, "custom_id": custom_id, "status": "refused",
            "input_hash": item.input_hash, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
            "payload": None, "error_message": refusal,
        }
    text = extract_output_text(body)
    try:
        payload = json.loads(text or "")
    except json.JSONDecodeError as error_decode:
        return {
            "news_id": item.news_id, "custom_id": custom_id, "status": "invalid_schema",
            "input_hash": item.input_hash, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
            "payload": None, "error_message": str(error_decode),
        }
    status = "success" if validate_analysis_payload(payload) else "invalid_schema"
    return {
        "news_id": item.news_id, "custom_id": custom_id, "status": status,
        "input_hash": item.input_hash, "input_tokens": input_tokens,
        "output_tokens": output_tokens, "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
        "payload": payload if status == "success" else None,
        "error_message": None if status == "success" else "Payload failed local schema validation",
    }


def actual_batch_cost(input_tokens: int, output_tokens: int) -> float:
    return round((
        input_tokens * BATCH_INPUT_PRICE_PER_MILLION
        + output_tokens * BATCH_OUTPUT_PRICE_PER_MILLION
    ) / 1_000_000, 8)
