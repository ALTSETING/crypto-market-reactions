import json
from datetime import datetime,timezone
from types import SimpleNamespace

from high_impact_sources.analysis.ai_analyzer import batch_request
from high_impact_sources.schemas import SEMANTIC_V21_SCHEMA
from scripts.run_stage16_semantic_v21_batch import (
    EXPECTED_EVENTS, INPUT_PRICE, MAX_COST_USD, MAX_OUTPUT_TOKENS, OUTPUT_PRICE,
    MODEL, parse_result,
)

def sample_event():
    return SimpleNamespace(id=1,source="sec",source_type="regulator",platform="sec",author_name=None,
        published_at=datetime(2026,1,1,tzinfo=timezone.utc),title="SEC permits Ethereum ETF",
        body="Official decision concerning an Ethereum ETF.",assets=["ETH"])

def valid_v21():
    return {"event_type":"official_decision","information_status":"confirmed_action","assets":[{"asset":"ETH","relevance":100,"content_valence":"positive","content_valence_score":80,"directness":"direct"}],"source_reliability":100,"novelty":80,"importance":90,"specificity":95,"confidence":90,"surprise_level":70,"surprise_evidence":"sufficient","first_disclosure":"yes","actionability":95,"institutional_relevance":90,"retail_relevance":80,"market_scope":"single_asset","regulatory_strength":95,"economic_significance":80,"technical_significance":10,"security_significance":5,"adoption_significance":85,"execution_certainty":95,"urgency":85,"fundamental_relevance":85,"temporary_vs_structural":"structural","evidence_quality":"official_document"}


def test_batch_request_is_semantic_strict_and_reason_free():
    line=batch_request(sample_event(),MODEL,MAX_OUTPUT_TOKENS)
    serialized=json.dumps(line)
    assert line["url"]=="/v1/responses"
    assert line["body"]["store"] is False
    assert line["body"]["reasoning"]=={"effort":"minimal"}
    assert line["body"]["text"]["format"]["strict"] is True
    assert '"reason"' not in serialized


def test_output_token_cap_cannot_exceed_budget_at_preflight_input():
    input_tokens=772_647
    maximum=input_tokens/1_000_000*INPUT_PRICE+EXPECTED_EVENTS*MAX_OUTPUT_TOKENS/1_000_000*OUTPUT_PRICE
    assert maximum<=MAX_COST_USD


def test_valid_batch_result_maps_custom_id_to_event():
    line={"custom_id":"high-impact-semantic-v2-1-1","response":{"status_code":200,"body":{
        "usage":{"input_tokens":100,"output_tokens":50,"total_tokens":150},
        "output":[{"type":"message","content":[{"type":"output_text","text":json.dumps(valid_v21())}]}]}}}
    result=parse_result(line,{line["custom_id"]:1},{"1":"abc"})
    assert result["event_id"]==1 and result["status"]=="success" and result["payload"]==valid_v21()


def test_schema_identity_is_v21():assert SEMANTIC_V21_SCHEMA["name"]=="high_impact_semantic_v2_1"
