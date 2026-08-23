import json
from types import SimpleNamespace

import pytest

from analysis.eth_batch import (
    MODEL_ID, BatchItem, estimate_batch, parse_batch_result, request_line, validate_jsonl,
)


def item(news_id=1):
    return BatchItem(news_id, "ETH title", "Asset focus: ETH\nTitle: ETH title\nText: facts", "a" * 64, 30)


def test_batch_line_is_strict_and_has_no_leakage():
    line = request_line(item(), 140)
    assert line["body"]["model"] == MODEL_ID
    assert line["body"]["text"]["format"]["strict"] is True
    assert line["body"]["store"] is False
    assert validate_jsonl([line], 1)["valid"] is True


def test_duplicate_custom_id_fails_validation():
    line = request_line(item(), 140)
    report = validate_jsonl([line, line], 2)
    assert report["valid"] is False
    assert report["duplicate_custom_ids"] == 1


def test_batch_estimate_uses_discounted_rates():
    estimate = estimate_batch([item()], 140)
    assert estimate["estimated_batch_cost_usd"] > 0
    assert estimate["pricing_usd_per_million"] == {"input": 0.125, "output": 1.0}


def test_parse_successful_responses_output():
    payload = {"sentiment": 10, "importance": 20, "novelty": 30, "credibility": 40,
               "direction": "bullish", "category": "staking", "horizon": "days",
               "confidence": 50, "eth_relevance": 90}
    batch_item = item()
    line = {"custom_id": batch_item.custom_id, "response": {"status_code": 200, "body": {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(payload)}]}],
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    }}, "error": None}
    parsed = parse_batch_result(line, {batch_item.custom_id: batch_item})
    assert parsed["status"] == "success"
    assert parsed["payload"] == payload


def test_leakage_is_rejected_before_jsonl_creation():
    leaked = item()
    object.__setattr__(leaked, "input_text", "return_5m: 1.0")
    with pytest.raises(ValueError):
        request_line(leaked, 140)
