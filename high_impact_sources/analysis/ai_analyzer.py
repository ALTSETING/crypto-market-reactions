"""Leakage-safe semantic AI contracts and token/cost dry-runs; no API client exists here."""
from __future__ import annotations
import hashlib,json,re
from typing import Any
import tiktoken
from high_impact_sources.config import PROMPT_VERSION
from high_impact_sources.schemas import AI_SCHEMA,SEMANTIC_V1_SCHEMA,SEMANTIC_V2_SCHEMA

SEMANTIC_V1_PROMPT_VERSION="high_impact_semantic_v1"
SEMANTIC_V1_SYSTEM_PROMPT="""You classify the semantic properties of a high-impact public message.

Do not predict prices, market direction, volatility, numeric market outcomes, or trading outcomes.
Do not recommend long, short, buy, sell, hold, stop-loss, or take-profit.
Do not infer how the market will react.

Evaluate only:
- what kind of event this is;
- whether it is confirmed, proposed, opinion, or rumor;
- source reliability;
- novelty;
- importance;
- specificity;
- which crypto assets are mentioned or affected in the message;
- whether the content itself is positive, negative, neutral, or mixed for each asset;
- whether the relationship is direct, indirect, or market-wide.

Content valence describes the meaning of the message, not future price movement.
Return strict schema-valid JSON only."""

SEMANTIC_V2_SYSTEM_PROMPT="""You are NOT a trading model.

Never predict future price, future return, market direction, probability of growth, expected volatility, or holding period.
Never recommend buy, sell, long, short, hold, stop-loss, or take-profit.
Never infer future market movement or use market outcomes.

Your task is only to classify semantic properties of the information itself using the supplied primary message and publication metadata. Scores describe the message, its evidence, scope, significance, certainty, and likely informational attention—not a market forecast. Content valence describes meaning for an asset, never price direction. Use regulatory_strength=null for non-regulatory events. Set first_disclosure=true only when the text itself supports a first official disclosure. Each asset reason must be at most 20 words. Return strict schema-valid JSON only."""

SEMANTIC_V21_SYSTEM_PROMPT="""Classify only the message's semantic properties. Do not make market forecasts or trading recommendations. Use surprise_level=null and surprise_evidence=insufficient without direct textual evidence. Use regulatory_strength=null unless regulatory. Content valence is message meaning, not market direction. Return strict JSON."""
SYSTEM_PROMPT=SEMANTIC_V21_SYSTEM_PROMPT

LEAKAGE_FIELDS=("return_1m","return_5m","return_10m","return_20m","return_40m","return_1h","return_3h","return_5h","return_8h","return_12h","baseline_price","market_reactions","news_market_reactions","market_candles","target_","actual_reaction","future_price")
PREDICTIVE_SCHEMA_FIELDS=("expected_horizon","expected_direction","price_direction","expected_return","price_probability","future_movement","long","short","trading_action","price_target","holding_period","sentiment")
PROHIBITED_OUTPUT_PHRASES=("buy","sell","long","short","price will rise","price will fall","expected return","price target","stop-loss","take-profit")
PRICES={"gpt-5-nano":{"input":.05,"output":.40},"gpt-5-mini":{"input":.25,"output":2.00}}

def compact_input(row):
    return json.dumps({"source":row.source,"source_type":row.source_type,"platform":row.platform,"author":row.author_name,"published_at":row.published_at.isoformat(),"title":row.title,"body":row.body[:12000],"locally_detected_assets":row.assets},ensure_ascii=False,separators=(",",":"))

def compact_input_v21(row,max_body_tokens=900):
    """Compact, deterministic semantic-only input for the mass v2.1 mode."""
    encoding=tiktoken.get_encoding("o200k_base")
    body=row.body or "";body_tokens=encoding.encode(body);included=body_tokens[:max_body_tokens]
    payload={"source":row.source,"source_type":row.source_type,"platform":row.platform,
             "author":row.author_name,"published_at":row.published_at.isoformat(),
             "title":row.title,"body":encoding.decode(included),
             "locally_detected_assets":row.assets}
    return json.dumps(payload,ensure_ascii=False,separators=(",",":"))

def compact_input_v21_stats(row,max_body_tokens=900):
    encoding=tiktoken.get_encoding("o200k_base");tokens=encoding.encode(row.body or "")
    return {"original_body_tokens":len(tokens),"included_body_tokens":min(len(tokens),max_body_tokens),
            "body_truncated":len(tokens)>max_body_tokens}

def leakage_fields(value):
    try:parsed=json.loads(value)
    except (TypeError,json.JSONDecodeError):
        lower=str(value).lower();return [name for name in LEAKAGE_FIELDS if name in lower]
    keys=[]
    def collect(item):
        if isinstance(item,dict):
            for key,nested in item.items():keys.append(str(key).lower());collect(nested)
        elif isinstance(item,list):
            for nested in item:collect(nested)
    collect(parsed)
    return [name for name in LEAKAGE_FIELDS if any(key==name or (name.endswith("_") and key.startswith(name)) for key in keys)]

def schema_predictive_fields(schema=AI_SCHEMA):
    def keys(value):
        if isinstance(value,dict):
            for key,item in value.items():yield key;yield from keys(item)
        elif isinstance(value,list):
            for item in value:yield from keys(item)
    present={key.lower() for key in keys(schema)}
    return [name for name in PREDICTIVE_SCHEMA_FIELDS if name in present]

def strict_schema_issues(schema=AI_SCHEMA):
    issues=[]
    def visit(node,path):
        if not isinstance(node,dict):return
        node_type=node.get("type")
        if node_type=="object":
            if node.get("additionalProperties") is not False:issues.append(f"{path}:additionalProperties")
            properties=node.get("properties",{});required=set(node.get("required",[]))
            missing=set(properties)-required
            if missing:issues.append(f"{path}:not_required:{sorted(missing)}")
            for key,value in properties.items():visit(value,f"{path}.{key}")
        elif node_type=="array":visit(node.get("items",{}),f"{path}[]")
    visit(schema["schema"],"$");return issues

def _validate_value(spec,value,path):
    types=spec.get("type");types=types if isinstance(types,list) else [types]
    if value is None:
        if "null" not in types:raise ValueError(f"{path} is not nullable")
        return
    valid=("object" in types and isinstance(value,dict)) or ("array" in types and isinstance(value,list)) or ("string" in types and isinstance(value,str)) or ("integer" in types and isinstance(value,int) and not isinstance(value,bool)) or ("boolean" in types and isinstance(value,bool))
    if not valid:raise ValueError(f"{path} has wrong type")
    if "enum" in spec and value not in spec["enum"]:raise ValueError(f"{path} not in enum")
    if isinstance(value,int) and not isinstance(value,bool):
        if value<spec.get("minimum",value) or value>spec.get("maximum",value):raise ValueError(f"{path} outside range")
    if isinstance(value,str) and len(value)>spec.get("maxLength",len(value)):raise ValueError(f"{path} too long")
    if isinstance(value,dict):
        properties=spec["properties"]
        if set(value)!=set(spec["required"]):raise ValueError(f"{path} has wrong fields")
        for key,item in value.items():_validate_value(properties[key],item,f"{path}.{key}")
    if isinstance(value,list):
        for index,item in enumerate(value):_validate_value(spec["items"],item,f"{path}[{index}]")

def validate_semantic_output(value,schema=AI_SCHEMA):
    text=json.dumps(value,ensure_ascii=False).lower();violations=[phrase for phrase in PROHIBITED_OUTPUT_PHRASES if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])",text)]
    if violations:raise ValueError(f"predictive/trading output rejected: {violations}")
    _validate_value(schema["schema"],value,"$")
    for item in value.get("assets",[]):
        if "reason" in item and len(item["reason"].split())>20:raise ValueError("asset reason exceeds 20 words")
    if schema["name"].startswith("high_impact_semantic_v2_1"):
        evidence=value.get("surprise_evidence");surprise=value.get("surprise_level")
        if evidence=="insufficient" and surprise is not None:raise ValueError("surprise_level must be null when evidence is insufficient")
        if evidence=="sufficient" and surprise is None:raise ValueError("surprise_level must be numeric when evidence is sufficient")
    return True

def batch_request(row,model="gpt-5-mini",max_output_tokens=600,*,schema=AI_SCHEMA,system_prompt=SYSTEM_PROMPT,prompt_version=PROMPT_VERSION,input_builder=compact_input_v21):
    payload=input_builder(row)
    leaked=leakage_fields(payload)
    if leaked:raise ValueError(f"AI input leakage: {leaked}")
    slug=prompt_version.replace("high_impact_","").replace("_","-")
    return {"custom_id":f"high-impact-{slug}-{row.id}","method":"POST","url":"/v1/responses","body":{"model":model,"instructions":system_prompt,"input":payload,"reasoning":{"effort":"minimal"},"max_output_tokens":max_output_tokens,"store":False,"text":{"format":{"type":"json_schema","name":schema["name"],"strict":True,"schema":schema["schema"]}}}}

def dry_run_row(row,model="gpt-5-mini",output_tokens=600,*,schema=AI_SCHEMA,system_prompt=SYSTEM_PROMPT,prompt_version=PROMPT_VERSION,input_builder=compact_input_v21):
    payload=input_builder(row);combined=system_prompt+payload+json.dumps(schema,separators=(",",":"));leakage=leakage_fields(payload)
    if leakage:raise ValueError(f"AI input leakage: {leakage}")
    encoding=tiktoken.get_encoding("o200k_base");input_tokens=len(encoding.encode(combined));rates=PRICES[model]
    return {"event_id":row.id,"model_name":model,"prompt_version":prompt_version,"input_hash":hashlib.sha256(combined.encode()).hexdigest(),"input_tokens":input_tokens,"estimated_output_tokens":output_tokens,"estimated_cost_usd":input_tokens/1e6*rates["input"]+output_tokens/1e6*rates["output"],"status":"dry_run","leakage":0,"raw_response_json":None}

def representative_output_tokens(version,include_reason=False):
    common_asset={"asset":"ETH","relevance":90,"content_valence":"positive","content_valence_score":70,"directness":"direct"}
    if version=="v1":sample={"event_type":"official_decision","information_status":"confirmed_action","source_reliability":95,"novelty":80,"importance":85,"specificity":90,"confidence":90,"assets":[common_asset|{"asset":asset} for asset in ("BTC","ETH","SOL")]}
    elif version=="v2":sample={"event_type":"official_decision","information_status":"confirmed_action","assets":[common_asset|{"asset":asset,"reason":"Directly addressed by the official message."} for asset in ("BTC","ETH","SOL")],"source_reliability":95,"novelty":80,"importance":85,"specificity":90,"confidence":90,"surprise_level":70,"first_disclosure":True,"new_information_ratio":80,"actionability":95,"institutional_relevance":90,"retail_relevance":70,"market_scope":"single_asset","regulatory_strength":95,"economic_significance":75,"technical_significance":10,"security_significance":5,"adoption_significance":80,"ecosystem_impact":75,"execution_certainty":95,"urgency":85,"historical_uniqueness":70,"market_attention":90,"fundamental_relevance":85,"temporary_vs_structural":"structural","evidence_quality":"official_document"}
    else:
        assets=[common_asset|{"asset":asset} for asset in ("BTC","ETH","SOL")]
        if include_reason:assets=[item|{"reason":"Directly addressed by the official message."} for item in assets]
        sample={"event_type":"official_decision","information_status":"confirmed_action","assets":assets,"source_reliability":95,"novelty":80,"importance":85,"specificity":90,"confidence":90,"surprise_level":70,"surprise_evidence":"sufficient","first_disclosure":"yes","actionability":95,"institutional_relevance":90,"retail_relevance":70,"market_scope":"single_asset","regulatory_strength":95,"economic_significance":75,"technical_significance":10,"security_significance":5,"adoption_significance":80,"execution_certainty":95,"urgency":85,"fundamental_relevance":85,"temporary_vs_structural":"structural","evidence_quality":"official_document"}
    return len(tiktoken.get_encoding("o200k_base").encode(json.dumps(sample,separators=(",",":"))))
