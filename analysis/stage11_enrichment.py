"""Local-only Stage 11 surprise/priced-in enrichment dry-run helpers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from analysis.eth_ab_test import MINI_MODEL_ID
from analysis.openai_analyzer import estimate_token_count, prepare_eth_analysis_input

MODEL = MINI_MODEL_ID
PROMPT_VERSION = "eth_market_context_v1"
MAX_OUTPUT_TOKENS = 180
STANDARD_PRICES_PER_MILLION = {"input": .25, "output": 2.00}
BATCH_PRICES_PER_MILLION = {"input": .125, "output": 1.00}
SYSTEM_PROMPT = (
    "Label only the article's information about ETH at publication time; never use later events or markets. "
    "Distinguish an original concrete event from a repeated report or general commentary. Do not claim actual "
    "market expectations: expected_by_market and already_priced_in are text-supported estimates only; when the "
    "text cannot support surprise or pricing, keep confidence low. Scores are integers 0-100. Return only the "
    "strict schema, with no explanation, summary, or hidden reasoning."
)
FORBIDDEN = {
    "return_5m", "return_15m", "return_30m", "return_1h", "return_4h", "return_24h",
    "abnormal_return", "market_adjusted_return", "baseline_price", "news_market_reactions",
    "future_volume", "future_candles", "target_", "stage10",
}


def enrichment_schema() -> dict[str, Any]:
    scores = {name: {"type":"integer","minimum":0,"maximum":100} for name in [
        "surprise_magnitude", "expected_by_market", "already_priced_in", "information_freshness",
        "primary_source_probability", "actionable_novelty", "event_specificity", "confidence",
    ]}
    properties = {"surprise_direction":{"type":"string","enum":["positive","negative","neutral","mixed"]}, **scores}
    return {"type":"object","properties":properties,"required":list(properties),"additionalProperties":False}


def assert_enrichment_no_leakage(value: str) -> None:
    lowered = value.casefold(); found = sorted(field for field in FORBIDDEN if field.casefold() in lowered)
    if found:
        raise ValueError(f"Stage 11 enrichment leakage: {', '.join(found)}")


def prepare_enrichment_rows(selected: Any, max_article_tokens: int = 900) -> list[dict[str, Any]]:
    schema = enrichment_schema(); schema_tokens = estimate_token_count(json.dumps(schema,separators=(",",":"))) + 8
    rows=[]
    for row in selected.itertuples(index=False):
        compact = prepare_eth_analysis_input({"title":row.title,"body":row.body},max_tokens=max_article_tokens)
        assert_enrichment_no_leakage(SYSTEM_PROMPT + "\n" + compact)
        input_tokens = estimate_token_count(SYSTEM_PROMPT) + estimate_token_count(compact) + schema_tokens + 8
        rows.append({"event_key":row.event_key,"news_id":int(row.news_id),"source":row.source,"published_at":row.published_at.isoformat(),
                     "input":compact,"input_hash":hashlib.sha256(compact.encode()).hexdigest(),"estimated_input_tokens":input_tokens,"estimated_output_tokens":MAX_OUTPUT_TOKENS})
    return rows


def _cost(input_tokens: int, output_tokens: int, rates: dict[str, float]) -> float:
    return round((input_tokens*rates["input"]+output_tokens*rates["output"])/1_000_000,8)


def write_enrichment_dry_run(selected: Any, reports_dir: Path, max_article_tokens: int = 900) -> dict[str, Any]:
    rows=prepare_enrichment_rows(selected,max_article_tokens); total_input=sum(row["estimated_input_tokens"] for row in rows); total_output=sum(row["estimated_output_tokens"] for row in rows)
    selection={"status":"DRY_RUN_ONLY","api_requests_made":0,"event_level_news":len(rows),"model":MODEL,"prompt_version":PROMPT_VERSION,
               "news_ids":[row["news_id"] for row in rows],"by_source":dict(Counter(row["source"] for row in rows)),"input_hashes":{str(row["news_id"]):row["input_hash"] for row in rows}}
    estimate={"status":"DRY_RUN_PASS","api_requests_made":0,"model":MODEL,"prompt_version":PROMPT_VERSION,"event_count":len(rows),"estimated_input_tokens":total_input,"estimated_output_tokens_upper_bound":total_output,
              "standard_cost_usd_upper_bound":_cost(total_input,total_output,STANDARD_PRICES_PER_MILLION),"batch_cost_usd_upper_bound":_cost(total_input,total_output,BATCH_PRICES_PER_MILLION),
              "ab_test_30_standard_cost_usd_upper_bound":_cost(sum(r["estimated_input_tokens"] for r in rows[:30]),30*MAX_OUTPUT_TOKENS,STANDARD_PRICES_PER_MILLION),
              "pricing_standard_per_million":STANDARD_PRICES_PER_MILLION,"pricing_batch_per_million":BATCH_PRICES_PER_MILLION,"max_article_tokens":max_article_tokens,"max_output_tokens":MAX_OUTPUT_TOKENS,"json_schema":enrichment_schema(),"system_prompt":SYSTEM_PROMPT,"leakage_count":0}
    preview=[{key:row[key] for key in ["event_key","news_id","source","published_at","input","estimated_input_tokens","estimated_output_tokens"]} for row in rows[:5]]
    comparison={"status":"NOT_RUN_REQUIRES_SEPARATE_CONFIRMATION","api_requests_made":0,"maximum_authorized_sample":0,"planned_maximum_sample":30,"candidate_model":MODEL,"note":"No paid A/B or enrichment request was authorized in this phase."}
    (reports_dir/"stage11_eth_enrichment_selection.json").write_text(json.dumps(selection,indent=2,ensure_ascii=False),encoding="utf-8")
    (reports_dir/"stage11_eth_enrichment_cost_estimate.json").write_text(json.dumps(estimate,indent=2,ensure_ascii=False),encoding="utf-8")
    (reports_dir/"stage11_eth_enrichment_input_preview.json").write_text(json.dumps(preview,indent=2,ensure_ascii=False),encoding="utf-8")
    (reports_dir/"stage11_eth_enrichment_model_comparison.json").write_text(json.dumps(comparison,indent=2,ensure_ascii=False),encoding="utf-8")
    return estimate
