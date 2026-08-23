import pytest
from analysis.stage11_enrichment import SYSTEM_PROMPT, assert_enrichment_no_leakage, enrichment_schema


def test_enrichment_schema_is_strict_and_has_no_explanation():
    schema=enrichment_schema()
    assert schema["additionalProperties"] is False
    assert "explanation" not in schema["properties"]
    assert set(schema["required"]) == set(schema["properties"])


def test_enrichment_system_prompt_has_no_market_leakage():
    assert_enrichment_no_leakage(SYSTEM_PROMPT)


def test_enrichment_leakage_guard_rejects_targets():
    with pytest.raises(ValueError):
        assert_enrichment_no_leakage("target_abnormal_return_1h")
