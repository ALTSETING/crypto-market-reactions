"""Evidence-aware Stage 11 enrichment schema and paid mini-only retest helpers."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from analysis.openai_analyzer import estimate_token_count, prepare_eth_analysis_input
from analysis.stage11_enrichment import assert_enrichment_no_leakage
from analysis.stage11_enrichment_ab import MINI_MODEL_ID, NUMERIC_FIELDS, PreparedEvent, estimate_cost

MODEL_ID = MINI_MODEL_ID
PROMPT_VERSION = "eth_market_context_v2"
MAX_OUTPUT_TOKENS = 180
EVIDENCE_FIELDS = (
    "expected_by_market_evidence", "already_priced_in_evidence", "primary_source_evidence",
)
NULLABLE_SCORE_FIELDS = (
    "expected_by_market", "already_priced_in", "primary_source_probability",
)
SYSTEM_PROMPT = (
    "Label only article evidence about ETH at publication time; never use later events or market data. "
    "Distinguish a concrete original event from repetition or commentary. Do not infer market expectations "
    "without textual evidence. Do not infer priced-in status from later price movement. Do not assume the "
    "publisher is the primary source. For expected_by_market, already_priced_in, and primary_source_probability, "
    "set evidence to sufficient only when the article directly supports the score; otherwise set evidence to "
    "insufficient and the score to null. Use integer scores 0-100 elsewhere. Return only strict JSON; no explanation."
)


class EvidenceEnrichmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surprise_direction: Literal["positive", "negative", "neutral", "mixed"]
    surprise_magnitude: int = Field(ge=0, le=100)
    expected_by_market: int | None = Field(ge=0, le=100)
    expected_by_market_evidence: Literal["sufficient", "insufficient"]
    already_priced_in: int | None = Field(ge=0, le=100)
    already_priced_in_evidence: Literal["sufficient", "insufficient"]
    information_freshness: int = Field(ge=0, le=100)
    primary_source_probability: int | None = Field(ge=0, le=100)
    primary_source_evidence: Literal["sufficient", "insufficient"]
    actionable_novelty: int = Field(ge=0, le=100)
    event_specificity: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def evidence_matches_nullable_scores(self) -> "EvidenceEnrichmentPayload":
        pairs = (
            (self.expected_by_market, self.expected_by_market_evidence),
            (self.already_priced_in, self.already_priced_in_evidence),
            (self.primary_source_probability, self.primary_source_evidence),
        )
        for score, evidence in pairs:
            if (evidence == "insufficient") != (score is None):
                raise ValueError("insufficient evidence requires null; sufficient evidence requires an integer")
        return self


def prepare_events_v2(sample: Any, raw_events: Any, max_article_tokens: int = 900) -> list[PreparedEvent]:
    lookup = raw_events.drop_duplicates("news_id").set_index("news_id")
    schema_tokens = estimate_token_count(json.dumps(EvidenceEnrichmentPayload.model_json_schema(), separators=(",", ":"))) + 8
    prepared = []
    for row in sample.itertuples(index=False):
        article = lookup.loc[int(row.news_id)]
        text = prepare_eth_analysis_input({"title": article.title, "body": article.body}, max_tokens=max_article_tokens)
        assert_enrichment_no_leakage(SYSTEM_PROMPT + "\n" + text)
        prepared.append(PreparedEvent(
            event_key=str(row.event_key), news_id=int(row.news_id), title=str(article.title),
            input_text=text, input_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            estimated_input_tokens=estimate_token_count(SYSTEM_PROMPT) + estimate_token_count(text) + schema_tokens + 8,
        ))
    return prepared


def build_preflight_v2(prepared: list[PreparedEvent], max_cost_usd: float) -> dict[str, Any]:
    identities = [f"{x.news_id}:{MODEL_ID}:{PROMPT_VERSION}" for x in prepared]
    total_input = sum(x.estimated_input_tokens for x in prepared)
    total_output = len(prepared) * MAX_OUTPUT_TOKENS
    cost = estimate_cost(MODEL_ID, total_input, total_output)
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate request identity")
    if cost > max_cost_usd:
        raise ValueError(f"Estimated cost ${cost:.8f} exceeds budget ${max_cost_usd:.8f}")
    schema = EvidenceEnrichmentPayload.model_json_schema()
    return {
        "status": "PREFLIGHT_PASS", "api_requests_made": 0, "sample_size": len(prepared),
        "news_ids": [x.news_id for x in prepared], "event_keys": [x.event_key for x in prepared],
        "input_hashes": {str(x.news_id): x.input_hash for x in prepared}, "model": MODEL_ID,
        "prompt_version": PROMPT_VERSION, "system_prompt": SYSTEM_PROMPT, "json_schema": schema,
        "estimated_input_tokens": total_input, "estimated_output_tokens_upper_bound": total_output,
        "estimated_cost_usd_upper_bound": round(cost, 8), "max_cost_usd": max_cost_usd,
        "leakage_count": 0, "unique_request_identity_count": len(set(identities)),
        "nullable_score_fields": list(NULLABLE_SCORE_FIELDS), "evidence_fields": list(EVIDENCE_FIELDS),
    }


def _retryable(error: Exception) -> bool:
    return isinstance(error, (RateLimitError, APIConnectionError, APITimeoutError)) or (
        isinstance(error, APIStatusError) and error.status_code >= 500
    )


def analyze_one_v2(client: OpenAI, item: PreparedEvent, max_retries: int = 3) -> dict[str, Any]:
    retries, started = 0, time.perf_counter()
    while True:
        try:
            response = client.responses.create(
                model=MODEL_ID,
                input=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": item.input_text}],
                text={"format": {"type": "json_schema", "name": "stage11_eth_evidence",
                                  "schema": EvidenceEnrichmentPayload.model_json_schema(), "strict": True}},
                reasoning={"effort": "minimal"},
                max_output_tokens=MAX_OUTPUT_TOKENS, store=False, timeout=90.0,
            )
            validation_error = None
            try:
                payload = EvidenceEnrichmentPayload.model_validate_json(response.output_text).model_dump()
                status = "success"
            except Exception as error:
                payload = json.loads(response.output_text) if response.output_text else None
                status = "invalid_evidence" if payload is not None else "refused"
                validation_error = f"{type(error).__name__}: {error}"
            usage = response.usage
            inp = int(usage.input_tokens if usage else 0); out = int(usage.output_tokens if usage else 0)
            return {
                "event_key": item.event_key, "news_id": item.news_id, "title": item.title,
                "model_name": MODEL_ID, "prompt_version": PROMPT_VERSION, "input_hash": item.input_hash,
                "status": status, "schema_status": "valid" if status == "success" else status,
                "structured_response": payload, "raw_response": response.model_dump(mode="json", warnings=False),
                "input_tokens": inp, "output_tokens": out,
                "total_tokens": int(usage.total_tokens if usage else inp + out),
                "actual_cost_usd": round(estimate_cost(MODEL_ID, inp, out), 8),
                "latency_seconds": round(time.perf_counter() - started, 4), "retries": retries,
                "error_message": validation_error,
            }
        except Exception as error:
            if retries < max_retries and _retryable(error):
                time.sleep(2 ** retries); retries += 1; continue
            return {
                "event_key": item.event_key, "news_id": item.news_id, "title": item.title,
                "model_name": MODEL_ID, "prompt_version": PROMPT_VERSION, "input_hash": item.input_hash,
                "status": "api_error", "schema_status": "not_received", "structured_response": None,
                "raw_response": None, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "actual_cost_usd": 0.0, "latency_seconds": round(time.perf_counter() - started, 4),
                "retries": retries, "error_message": f"{type(error).__name__}: {error}",
            }


def run_v2(api_key: str, prepared: list[PreparedEvent], existing: list[dict[str, Any]],
           on_result: Callable[[dict[str, Any]], None], workers: int = 4) -> tuple[list[dict[str, Any]], int]:
    valid = {x.news_id: x for x in prepared}
    results = [x for x in existing if x["news_id"] in valid and x.get("input_hash") == valid[x["news_id"]].input_hash]
    done = {x["news_id"] for x in results if x["status"] == "success"}
    jobs = [x for x in prepared if x.news_id not in done]
    client = OpenAI(api_key=api_key, max_retries=0)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(analyze_one_v2, client, item) for item in jobs]
        for future in as_completed(futures):
            row = future.result(); on_result(row); results.append(row)
    latest = {x["news_id"]: x for x in results}
    return [latest[x.news_id] for x in prepared if x.news_id in latest], len(jobs)


def compare_v1_v2(v1: list[dict[str, Any]], v2: list[dict[str, Any]]) -> dict[str, Any]:
    v1i = {x["news_id"]: x for x in v1 if x["model_name"] == MODEL_ID and x["status"] == "success"}
    v2i = {x["news_id"]: x for x in v2 if x["status"] == "success"}
    paired = sorted(set(v1i) & set(v2i))
    null_rates = {field: round(sum(v2i[n]["structured_response"][field] is None for n in paired) / len(paired), 4) for field in NULLABLE_SCORE_FIELDS} if paired else {}
    stability = {}
    for field in NUMERIC_FIELDS:
        pairs = [(v1i[n]["structured_response"][field], v2i[n]["structured_response"][field]) for n in paired
                 if v2i[n]["structured_response"].get(field) is not None]
        stability[field] = {
            "comparable_pairs": len(pairs),
            "mean_absolute_difference": round(statistics.mean(abs(a-b) for a,b in pairs), 3) if pairs else None,
        }
    contradictions = {
        "insufficient_with_numeric_score": 0,
        "sufficient_with_null_score": 0,
        "high_priced_in_and_high_freshness": 0,
        "generic_but_highly_actionable": 0,
    }
    for n in paired:
        p = v2i[n]["structured_response"]
        for score, evidence in zip(NULLABLE_SCORE_FIELDS, EVIDENCE_FIELDS):
            contradictions["insufficient_with_numeric_score"] += int(p[evidence] == "insufficient" and p[score] is not None)
            contradictions["sufficient_with_null_score"] += int(p[evidence] == "sufficient" and p[score] is None)
        contradictions["high_priced_in_and_high_freshness"] += int((p["already_priced_in"] or 0) >= 75 and p["information_freshness"] >= 75)
        contradictions["generic_but_highly_actionable"] += int(p["event_specificity"] <= 25 and p["actionable_novelty"] >= 75)
    evidence_distribution = {field: dict(__import__("collections").Counter(v2i[n]["structured_response"][field] for n in paired)) for field in EVIDENCE_FIELDS}
    return {
        "status": "V1_V2_COMPARISON_COMPLETE", "model": MODEL_ID,
        "baseline_prompt_version": "eth_market_context_v1", "candidate_prompt_version": PROMPT_VERSION,
        "paired_successes": len(paired), "null_rates": null_rates,
        "evidence_distribution": evidence_distribution, "score_stability": stability,
        "contradictions": contradictions,
        "human_review_readiness": "READY_FOR_REVIEW_NOT_YET_REVIEWED" if len(paired) == 30 and not sum(contradictions.values()) else "NOT_READY",
        "full_batch_gate": "NO-GO_PENDING_HUMAN_REVIEW_AND_NEW_CONFIRMATION",
    }
