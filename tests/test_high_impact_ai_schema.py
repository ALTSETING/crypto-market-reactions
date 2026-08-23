import json
from datetime import datetime,timezone
from types import SimpleNamespace

import pytest

from high_impact_sources.analysis.ai_analyzer import (
    AI_SCHEMA,LEAKAGE_FIELDS,SEMANTIC_V1_SCHEMA,SEMANTIC_V2_SCHEMA,SYSTEM_PROMPT,
    batch_request,compact_input_v21,leakage_fields,schema_predictive_fields,
    strict_schema_issues,validate_semantic_output,
)
from high_impact_sources.config import PROMPT_VERSION
from high_impact_sources.schemas import build_semantic_v21_schema


def sample_event():
    return SimpleNamespace(id=1,source="sec",source_type="regulator",platform="sec",
        author_name=None,published_at=datetime(2026,1,1,tzinfo=timezone.utc),
        title="SEC permits Ethereum ETF",body="Official decision concerning an Ethereum ETF.",assets=["ETH"])


def valid_v21():
    return {"event_type":"official_decision","information_status":"confirmed_action",
        "assets":[{"asset":"ETH","relevance":100,"content_valence":"positive","content_valence_score":80,"directness":"direct"}],
        "source_reliability":100,"novelty":80,"importance":90,"specificity":95,"confidence":90,
        "surprise_level":70,"surprise_evidence":"sufficient","first_disclosure":"yes",
        "actionability":95,"institutional_relevance":90,"retail_relevance":80,
        "market_scope":"single_asset","regulatory_strength":95,"economic_significance":80,
        "technical_significance":10,"security_significance":5,"adoption_significance":85,
        "execution_certainty":95,"urgency":85,"fundamental_relevance":85,
        "temporary_vs_structural":"structural","evidence_quality":"official_document"}


def valid_v2():
    value=valid_v21();value.pop("surprise_evidence")
    value.update({"first_disclosure":True,"new_information_ratio":80,"ecosystem_impact":80,
        "historical_uniqueness":70,"market_attention":90})
    value["assets"][0]["reason"]="Official approval directly concerns Ethereum."
    return value


def test_ai_prompt_has_no_reaction_data():assert leakage_fields(SYSTEM_PROMPT)==[]
def test_system_prompt_omits_market_payload_fields():assert not any(term in SYSTEM_PROMPT.lower() for term in LEAKAGE_FIELDS)
def test_system_prompt_omits_market_data_nouns():assert not {"returns","reactions","candles"}&set(SYSTEM_PROMPT.lower().split())
def test_strict_schema():assert AI_SCHEMA["strict"] and AI_SCHEMA["schema"]["additionalProperties"] is False
def test_schema_assets_enum():assert AI_SCHEMA["schema"]["properties"]["assets"]["items"]["properties"]["asset"]["enum"]==["BTC","ETH","SOL"]
def test_no_long_short_output():assert "long" not in json.dumps(AI_SCHEMA).lower() and "short" not in json.dumps(AI_SCHEMA).lower()
def test_forbidden_leakage_detected():assert leakage_fields("baseline_price and return_5m")==["return_5m","baseline_price"]
def test_prompt_input_has_no_market_payload():
    value=compact_input_v21(sample_event()).lower();assert not any(field in value for field in LEAKAGE_FIELDS)
def test_schema_has_no_predictive_fields():assert schema_predictive_fields()==[]
def test_expected_horizon_removed_completely():assert "expected_horizon" not in json.dumps(AI_SCHEMA)
def test_semantic_schema_uses_content_valence():
    properties=AI_SCHEMA["schema"]["properties"]["assets"]["items"]["properties"]
    assert "content_valence" in properties and "content_valence_score" in properties and "sentiment" not in properties
def test_content_valence_is_not_price_direction():assert "Content valence is message meaning, not market direction" in SYSTEM_PROMPT


@pytest.mark.parametrize("phrase",["buy","sell","long","short","price will rise","price will fall","expected return"])
def test_predictive_or_trading_response_rejected(phrase):
    with pytest.raises(ValueError):validate_semantic_output({"extra":phrase})


def test_valid_semantic_response_accepted():assert validate_semantic_output(valid_v21())
def test_market_reactions_added_only_after_ai():
    request=batch_request(sample_event());serialized=json.dumps(request)
    assert request["url"]=="/v1/responses" and not leakage_fields(request["body"]["input"]) and "market_reactions" not in serialized
def test_semantic_prompt_version():assert PROMPT_VERSION=="high_impact_semantic_v2_1"
def test_jsonl_request_has_strict_schema():
    request=batch_request(sample_event());fmt=request["body"]["text"]["format"]
    assert fmt["type"]=="json_schema" and fmt["strict"] is True
def test_v21_all_fields_required_for_strict_schema():assert strict_schema_issues()==[]
def test_v21_reason_schema_is_also_strict():assert strict_schema_issues(build_semantic_v21_schema(True))==[]
def test_regulatory_strength_nullable_and_required():
    root=AI_SCHEMA["schema"];assert root["properties"]["regulatory_strength"]["type"]==["integer","null"] and "regulatory_strength" in root["required"]
def test_nullable_regulatory_strength_validates():
    value=valid_v21();value["regulatory_strength"]=None;assert validate_semantic_output(value)
def test_surprise_nullable_when_evidence_insufficient():
    value=valid_v21();value["surprise_level"]=None;value["surprise_evidence"]="insufficient"
    assert validate_semantic_output(value)
def test_surprise_numeric_rejected_when_evidence_insufficient():
    value=valid_v21();value["surprise_evidence"]="insufficient"
    with pytest.raises(ValueError):validate_semantic_output(value)
def test_surprise_null_rejected_when_evidence_sufficient():
    value=valid_v21();value["surprise_level"]=None
    with pytest.raises(ValueError):validate_semantic_output(value)
def test_first_disclosure_is_three_state_enum():
    spec=AI_SCHEMA["schema"]["properties"]["first_disclosure"]
    assert spec["enum"]==["yes","no","unclear"]
def test_removed_unreliable_or_redundant_fields():
    root=AI_SCHEMA["schema"]["properties"]
    assert not {"historical_uniqueness","market_attention","new_information_ratio","ecosystem_impact"}&set(root)
def test_reason_absent_by_default_and_cli_enabled():
    default=AI_SCHEMA["schema"]["properties"]["assets"]["items"]["properties"]
    with_reason=build_semantic_v21_schema(True)["schema"]["properties"]["assets"]["items"]
    assert "reason" not in default and "reason" in with_reason["properties"] and "reason" in with_reason["required"]
def test_asset_reason_over_twenty_words_rejected_in_reason_mode():
    value=valid_v21();value["assets"][0]["reason"]=" ".join(["word"]*21)
    with pytest.raises(ValueError):validate_semantic_output(value,build_semantic_v21_schema(True))
def test_v21_request_resume_is_deterministic():assert batch_request(sample_event())==batch_request(sample_event())
def test_compact_input_body_cap():
    event=sample_event();event.body="token "*2000
    import tiktoken
    body=json.loads(compact_input_v21(event,100))["body"]
    assert len(tiktoken.get_encoding("o200k_base").encode(body))<=100
def test_v1_schema_preserved_for_ab_comparison():assert "surprise_level" not in SEMANTIC_V1_SCHEMA["schema"]["properties"] and "content_valence" in SEMANTIC_V1_SCHEMA["schema"]["properties"]["assets"]["items"]["properties"]
def test_v2_schema_preserved_for_comparison():assert validate_semantic_output(valid_v2(),SEMANTIC_V2_SCHEMA)
