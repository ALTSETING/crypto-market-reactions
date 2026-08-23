import pytest

from analysis.stage11_enrichment_evidence import EvidenceEnrichmentPayload, SYSTEM_PROMPT


BASE = {
    "surprise_direction": "neutral", "surprise_magnitude": 10,
    "expected_by_market": None, "expected_by_market_evidence": "insufficient",
    "already_priced_in": None, "already_priced_in_evidence": "insufficient",
    "information_freshness": 50,
    "primary_source_probability": None, "primary_source_evidence": "insufficient",
    "actionable_novelty": 20, "event_specificity": 30, "confidence": 25,
}


def test_nullable_schema_and_evidence_are_required():
    schema = EvidenceEnrichmentPayload.model_json_schema()
    assert set(("expected_by_market", "already_priced_in", "primary_source_probability")) <= set(schema["required"])
    assert EvidenceEnrichmentPayload.model_validate(BASE).expected_by_market is None


def test_evidence_score_consistency():
    invalid = dict(BASE, expected_by_market=30)
    with pytest.raises(ValueError):
        EvidenceEnrichmentPayload.model_validate(invalid)
    valid = dict(BASE, expected_by_market=30, expected_by_market_evidence="sufficient")
    assert EvidenceEnrichmentPayload.model_validate(valid).expected_by_market == 30


def test_prompt_contains_all_non_inference_rules():
    assert "Do not infer market expectations without textual evidence" in SYSTEM_PROMPT
    assert "Do not infer priced-in status from later price movement" in SYSTEM_PROMPT
    assert "Do not assume the publisher is the primary source" in SYSTEM_PROMPT
    assert "score to null" in SYSTEM_PROMPT
