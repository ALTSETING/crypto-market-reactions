import pandas as pd
import pytest

from analysis.stage11_enrichment_ab import EnrichmentPayload, build_preflight, PreparedEvent
from analysis.stage11_enrichment import SYSTEM_PROMPT, assert_enrichment_no_leakage


def test_enrichment_payload_is_strict_and_bounded():
    schema = EnrichmentPayload.model_json_schema()
    assert schema["additionalProperties"] is False
    with pytest.raises(Exception):
        EnrichmentPayload.model_validate({"surprise_direction": "positive", "surprise_magnitude": 101})


def test_prompt_explicitly_limits_uncertain_market_expectation():
    assert "text-supported estimates only" in SYSTEM_PROMPT
    assert "confidence low" in SYSTEM_PROMPT
    assert_enrichment_no_leakage(SYSTEM_PROMPT + "\nTitle: Ethereum upgrade")


def test_preflight_guards_budget_and_duplicate_identity():
    item = PreparedEvent("event-1", 1, "title", "Title: ETH", "a" * 64, 100)
    report = build_preflight([item], seed=1, max_cost_usd=0.03)
    assert report["leakage_count"] == 0
    assert report["unique_request_identity_count"] == 2
    with pytest.raises(ValueError):
        build_preflight([item, item], seed=1, max_cost_usd=0.03)


def test_reaction_leakage_is_rejected():
    with pytest.raises(ValueError):
        assert_enrichment_no_leakage("target_abnormal_return_24h=2")
