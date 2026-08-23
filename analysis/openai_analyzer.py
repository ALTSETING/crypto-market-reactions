"""Local Stage 9 helpers.  This module never calls the OpenAI API."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import tiktoken
from bs4 import BeautifulSoup

from app.config import settings
from database.models import NewsArticle, NewsAnalysis

PROMPT_VERSION = "eth_label_v1"
SYSTEM_PROMPT = (
    "Label historical news for its likely effect on ETH using only article facts; never use later "
    "prices or events. Return schema-valid JSON only, without explanation or summary. Scores: "
    "sentiment -100 bearish to 100 bullish; importance impact size; novelty newness; credibility "
    "evidence reliability; confidence label certainty; eth_relevance directness (all other scores "
    "0-100). Use neutral and low confidence for weak, indirect, old, mixed, or uncertain evidence."
)

DIRECTION_VALUES = ("bearish", "neutral", "bullish", "mixed")
CATEGORY_VALUES = (
    "regulation", "etf", "staking", "protocol_upgrade", "layer2", "network_activity",
    "fees", "security", "hack", "exchange", "institutional_adoption", "partnership",
    "tokenomics", "legal", "macro", "market_commentary", "defi", "stablecoins", "nft", "other",
)
HORIZON_VALUES = ("minutes", "hours", "days", "weeks", "months", "unclear")
FORBIDDEN_FIELDS = {
    "baseline_price", "return_5m", "return_15m", "return_30m", "return_1h", "return_4h",
    "return_24h", "max_return", "min_return", "volume_change", "news_market_reactions",
}
ETH_KEYWORDS = re.compile(
    r"\b(ethereum|ether|eth|staking|validator|layer\s*2|rollup|etf|sec|upgrade|fork|"
    r"hack|exploit|fees?|gas|network|regulat(?:ion|or)|defi|stablecoin|eip-\d+)\b",
    re.IGNORECASE,
)
BOILERPLATE = re.compile(
    r"advertisement|sponsored|subscribe|newsletter|related articles?|read more|learn more|buy now|"
    r"for informational purposes|not (?:financial|investment) advice|disclaimer|all rights reserved|"
    r"cookie policy|privacy policy",
    re.IGNORECASE,
)
_TOKENIZER_CACHE = Path(__file__).resolve().parents[1] / "reports" / "tiktoken_cache"
_TOKENIZER_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(_TOKENIZER_CACHE))
_ENCODING = tiktoken.get_encoding("o200k_base")


def analysis_json_schema(include_explanation: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "sentiment": {"type": "integer", "minimum": -100, "maximum": 100},
        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
        "novelty": {"type": "integer", "minimum": 0, "maximum": 100},
        "credibility": {"type": "integer", "minimum": 0, "maximum": 100},
        "direction": {"type": "string", "enum": list(DIRECTION_VALUES)},
        "category": {"type": "string", "enum": list(CATEGORY_VALUES)},
        "horizon": {"type": "string", "enum": list(HORIZON_VALUES)},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "eth_relevance": {"type": "integer", "minimum": 0, "maximum": 100},
    }
    if include_explanation:
        properties["explanation"] = {"type": "string", "maxLength": 160}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def estimate_token_count(text: str) -> int:
    """Count tokens locally with OpenAI's o200k tokenizer."""

    return len(_ENCODING.encode(text))


def count_request_input_tokens(user_input: str, system_prompt: str = SYSTEM_PROMPT) -> int:
    """Estimate request tokens, including both messages and small framing overhead."""

    return estimate_token_count(system_prompt) + estimate_token_count(user_input) + 8


def _extract_text(body: str | None) -> str:
    if not body:
        return ""
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "button"]):
        tag.decompose()
    for tag in soup.select(
        "[class*='advert'],[class*='promo'],[class*='newsletter'],[class*='related'],"
        "[id*='advert'],[id*='newsletter'],[id*='related']"
    ):
        tag.decompose()

    lines: list[str] = []
    for raw in soup.get_text("\n", strip=True).splitlines():
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if cleaned and not BOILERPLATE.search(cleaned):
            lines.append(cleaned)
    return " ".join(lines)


def _article_value(article: dict[str, Any] | NewsArticle, field: str) -> Any:
    return article.get(field) if isinstance(article, dict) else getattr(article, field)


def prepare_eth_analysis_input_details(
    article: dict[str, Any] | NewsArticle,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Build compact extractive ETH input and report whether text was truncated."""

    title = re.sub(r"\s+", " ", str(_article_value(article, "title") or "")).strip()
    text = _extract_text(_article_value(article, "body"))
    if title and text.lower().startswith(title.lower()):
        text = text[len(title):].lstrip(" :-—|\n")
    text = re.sub(r"\s+", " ", text).strip()

    def render(value: str) -> str:
        return f"Asset focus: ETH\nTitle: {title}\nText: {value}"

    full_input = render(text)
    full_tokens = estimate_token_count(full_input)
    budget = max_tokens or settings.openai_max_article_tokens
    if full_tokens <= budget:
        return {"input": full_input, "truncated": False, "full_tokens": full_tokens}

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    lead = sentences[:6]
    relevant = [sentence for sentence in sentences[6:] if ETH_KEYWORDS.search(sentence)]
    chosen: list[str] = []
    seen: set[str] = set()
    for sentence in [*lead, *relevant]:
        key = sentence.casefold()
        if key in seen:
            continue
        candidate = " ".join([*chosen, sentence])
        if estimate_token_count(render(candidate)) <= budget:
            chosen.append(sentence)
            seen.add(key)

    compact = " ".join(chosen)
    if not compact and sentences:
        # Extremely long sentence: keep the title and omit it instead of cutting mid-sentence.
        compact = ""
    prepared = render(compact)
    if estimate_token_count(prepared) > budget:
        raise ValueError("Unable to prepare ETH input within configured token budget")
    return {"input": prepared, "truncated": True, "full_tokens": full_tokens}


def prepare_eth_analysis_input(article: dict[str, Any] | NewsArticle, max_tokens: int | None = None) -> str:
    return str(prepare_eth_analysis_input_details(article, max_tokens=max_tokens)["input"])


def assert_no_data_leakage(text: str) -> None:
    lowered = text.casefold()
    found = sorted(field for field in FORBIDDEN_FIELDS if field.casefold() in lowered)
    if found:
        raise ValueError(f"Forbidden market-reaction fields in analysis input: {', '.join(found)}")


def validate_analysis_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    schema = analysis_json_schema()
    if set(payload) != set(schema["required"]):
        return False
    integer_ranges = {
        "sentiment": (-100, 100), "importance": (0, 100), "novelty": (0, 100),
        "credibility": (0, 100), "confidence": (0, 100), "eth_relevance": (0, 100),
    }
    if any(
        isinstance(payload.get(key), bool)
        or not isinstance(payload.get(key), int)
        or not low <= payload[key] <= high
        for key, (low, high) in integer_ranges.items()
    ):
        return False
    return (
        payload["direction"] in DIRECTION_VALUES
        and payload["category"] in CATEGORY_VALUES
        and payload["horizon"] in HORIZON_VALUES
    )


def build_analysis_summary(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    if not records:
        return {"count": 0}
    return {
        "count": len(records),
        "average_sentiment": round(sum(r.get("sentiment", 0) or 0 for r in records) / len(records), 2),
        "average_importance": round(sum(r.get("importance", 0) or 0 for r in records) / len(records), 2),
        "average_relevance": round(sum(r.get("asset_relevance", 0) or 0 for r in records) / len(records), 2),
        "direction_distribution": dict(Counter(r.get("expected_direction") or "unknown" for r in records)),
        "category_distribution": dict(Counter(r.get("category") or "unknown" for r in records)),
    }


def prepare_analysis_record(
    article: NewsArticle,
    payload: dict[str, Any],
    *,
    model_name: str,
    prompt_version: str = PROMPT_VERSION,
) -> NewsAnalysis:
    input_text = prepare_eth_analysis_input(article, max_tokens=settings.openai_max_article_tokens)
    assert_no_data_leakage(input_text)
    input_tokens = count_request_input_tokens(input_text)
    return NewsAnalysis(
        news_id=article.id, asset_focus="ETH", sentiment=payload.get("sentiment"),
        importance=payload.get("importance"), novelty=payload.get("novelty"),
        credibility=payload.get("credibility"), expected_direction=payload.get("direction"),
        category=payload.get("category"), impact_duration=payload.get("horizon"),
        confidence=payload.get("confidence"), asset_relevance=payload.get("eth_relevance"),
        model_name=model_name, prompt_version=prompt_version,
        input_hash=hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
        input_tokens=input_tokens, output_tokens=0, total_tokens=input_tokens,
        estimated_cost_usd=None, actual_cost_usd=None, raw_response_json=json.dumps(payload),
        status="success", analyzed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
