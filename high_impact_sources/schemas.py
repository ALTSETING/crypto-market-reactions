"""Shared event and strict AI schemas."""

from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

@dataclass
class HighImpactEvent:
    source: str
    source_type: str
    platform: str
    url: str
    body: str
    published_at: datetime
    author_name: str | None = None
    author_handle: str | None = None
    external_id: str | None = None
    canonical_url: str | None = None
    title: str | None = None
    modified_at: datetime | None = None
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None
    time_source: str = "official_metadata"
    time_confidence: float = 1.0
    source_authenticity: float = 1.0
    content_hash: str = ""
    raw_metadata_json: dict[str, Any] = field(default_factory=dict)
    assets: list[str] = field(default_factory=list)
    crypto_relevance: float = 0.0

    def __post_init__(self) -> None:
        self.published_at = utc(self.published_at)
        self.discovered_at = utc(self.discovered_at)
        if self.modified_at: self.modified_at = utc(self.modified_at)
        if self.deleted_at: self.deleted_at = utc(self.deleted_at)
        self.canonical_url = self.canonical_url or self.url
        if not self.content_hash:
            normalized = f"{(self.title or '').strip()}\n{self.body.strip()}"
            self.content_hash = sha256(normalized.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

SEMANTIC_V1_SCHEMA: dict[str, Any] = {
    "name": "high_impact_event_analysis",
    "strict": True,
    "schema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "event_type": {"type": "string", "enum": ["official_decision","policy_statement","legal_action","product_announcement","protocol_update","security_event","market_comment","personal_opinion","endorsement","threat","rumor","other"]},
            "information_status": {"type": "string", "enum": ["confirmed_action","official_plan","proposal","prediction","opinion","rumor","unclear"]},
            **{name: {"type": "integer", "minimum": 0, "maximum": 100} for name in ("source_reliability","novelty","importance","specificity","confidence")},
            "assets": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "properties": {
                    "asset": {"type": "string", "enum": ["BTC","ETH","SOL"]},
                    "relevance": {"type": "integer", "minimum": 0, "maximum": 100},
                    "content_valence": {"type": "string", "enum": ["negative","neutral","positive","mixed"], "description": "Meaning of the message for the asset, not a price-direction prediction."},
                    "content_valence_score": {"type": "integer", "minimum": -100, "maximum": 100, "description": "Strength and sign of semantic content valence, not expected market movement."},
                    "directness": {"type": "string", "enum": ["direct","indirect","market_wide"]},
                }, "required": ["asset","relevance","content_valence","content_valence_score","directness"]}},
        },
        "required": ["event_type","information_status","source_reliability","novelty","importance","specificity","confidence","assets"],
    },
}

_SCORE = {"type": "integer", "minimum": 0, "maximum": 100}
SEMANTIC_V2_SCHEMA: dict[str, Any] = {
    "name": "high_impact_semantic_v2",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "event_type": {"type": "string", "enum": ["official_decision","policy_statement","legal_action","protocol_update","security_event","product_launch","partnership","exchange_listing","exchange_delisting","macro","institutional","government","personal_opinion","rumor","other"]},
            "information_status": {"type": "string", "enum": ["confirmed_action","official_plan","proposal","prediction","opinion","rumor","unclear"]},
            "assets": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "properties": {
                    "asset": {"type": "string", "enum": ["BTC","ETH","SOL"]},
                    "relevance": dict(_SCORE),
                    "content_valence": {"type": "string", "enum": ["negative","neutral","positive","mixed"], "description": "Meaning of the message for the asset, not a price-direction prediction."},
                    "content_valence_score": {"type": "integer", "minimum": -100, "maximum": 100, "description": "Semantic valence strength, not expected market movement."},
                    "directness": {"type": "string", "enum": ["direct","indirect","market_wide"]},
                    "reason": {"type": "string", "maxLength": 160, "description": "Semantic rationale using at most 20 words and only message evidence."},
                }, "required": ["asset","relevance","content_valence","content_valence_score","directness","reason"]}},
            "source_reliability": dict(_SCORE), "novelty": dict(_SCORE), "importance": dict(_SCORE),
            "specificity": dict(_SCORE), "confidence": dict(_SCORE),
            "surprise_level": {**_SCORE, "description": "How unexpected the information appears from the message context alone; never use market behavior."},
            "first_disclosure": {"type": "boolean", "description": "True only when the message itself supports that this is the first official disclosure; otherwise false."},
            "new_information_ratio": {**_SCORE, "description": "Share of the message that conveys substantively new information."},
            "actionability": {**_SCORE, "description": "Presence of concrete actions or decisions, not trading actionability."},
            "institutional_relevance": dict(_SCORE), "retail_relevance": dict(_SCORE),
            "market_scope": {"type": "string", "enum": ["single_asset","sector","whole_crypto","macro"]},
            "regulatory_strength": {"type": ["integer","null"], "minimum": 0, "maximum": 100, "description": "Regulatory force when the source/event is regulatory; null otherwise."},
            "economic_significance": {**_SCORE, "description": "Potential change to project or ecosystem economics, never price."},
            "technical_significance": dict(_SCORE), "security_significance": dict(_SCORE),
            "adoption_significance": dict(_SCORE), "ecosystem_impact": dict(_SCORE),
            "execution_certainty": {**_SCORE, "description": "Certainty that the stated plan or action will be executed, not certainty of market outcome."},
            "urgency": {**_SCORE, "description": "Operational or informational urgency, not urgency to trade."},
            "historical_uniqueness": {**_SCORE, "description": "Rarity indicated by the information itself; lower confidence when evidence is limited."},
            "market_attention": {**_SCORE, "description": "Likely public attention due to message salience, never expected market movement."},
            "fundamental_relevance": dict(_SCORE),
            "temporary_vs_structural": {"type": "string", "enum": ["temporary","mixed","structural"]},
            "evidence_quality": {"type": "string", "enum": ["official_document","official_statement","primary_source","secondary_source","unknown"]},
        },
        "required": ["event_type","information_status","assets","source_reliability","novelty","importance","specificity","confidence","surprise_level","first_disclosure","new_information_ratio","actionability","institutional_relevance","retail_relevance","market_scope","regulatory_strength","economic_significance","technical_significance","security_significance","adoption_significance","ecosystem_impact","execution_certainty","urgency","historical_uniqueness","market_attention","fundamental_relevance","temporary_vs_structural","evidence_quality"],
    },
}

def build_semantic_v21_schema(include_reason: bool = False) -> dict[str, Any]:
    """Build the compact mass schema; optional reasons are a separate CLI mode."""
    asset_properties = {
        "asset": {"type": "string", "enum": ["BTC","ETH","SOL"]},
        "relevance": dict(_SCORE),
        "content_valence": {"type": "string", "enum": ["negative","neutral","positive","mixed"]},
        "content_valence_score": {"type": "integer", "minimum": -100, "maximum": 100},
        "directness": {"type": "string", "enum": ["direct","indirect","market_wide"]},
    }
    if include_reason:
        asset_properties["reason"] = {"type": "string", "maxLength": 160}
    properties = {
        "event_type": {"type": "string", "enum": ["official_decision","policy_statement","legal_action","protocol_update","security_event","product_launch","partnership","exchange_listing","exchange_delisting","macro","institutional","government","personal_opinion","rumor","other"]},
        "information_status": {"type": "string", "enum": ["confirmed_action","official_plan","proposal","prediction","opinion","rumor","unclear"]},
        "assets": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": asset_properties, "required": list(asset_properties)}},
        "source_reliability": dict(_SCORE), "novelty": dict(_SCORE), "importance": dict(_SCORE),
        "specificity": dict(_SCORE), "confidence": dict(_SCORE),
        "surprise_level": {"type": ["integer","null"], "minimum": 0, "maximum": 100},
        "surprise_evidence": {"type": "string", "enum": ["sufficient","insufficient"]},
        "first_disclosure": {"type": "string", "enum": ["yes","no","unclear"]},
        "actionability": dict(_SCORE), "institutional_relevance": dict(_SCORE), "retail_relevance": dict(_SCORE),
        "market_scope": {"type": "string", "enum": ["single_asset","sector","whole_crypto","macro"]},
        "regulatory_strength": {"type": ["integer","null"], "minimum": 0, "maximum": 100},
        "economic_significance": dict(_SCORE), "technical_significance": dict(_SCORE),
        "security_significance": dict(_SCORE), "adoption_significance": dict(_SCORE),
        "execution_certainty": dict(_SCORE), "urgency": dict(_SCORE), "fundamental_relevance": dict(_SCORE),
        "temporary_vs_structural": {"type": "string", "enum": ["temporary","mixed","structural"]},
        "evidence_quality": {"type": "string", "enum": ["official_document","official_statement","primary_source","secondary_source","unknown"]},
    }
    return {"name": "high_impact_semantic_v2_1_reason" if include_reason else "high_impact_semantic_v2_1", "strict": True, "schema": {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}}

SEMANTIC_V21_SCHEMA = build_semantic_v21_schema(False)
AI_SCHEMA = SEMANTIC_V21_SCHEMA
