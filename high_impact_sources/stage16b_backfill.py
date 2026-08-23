"""Offline helpers for the isolated Stage 16B historical source archive."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit


ASSETS = ("BTC", "ETH", "SOL")
ASSET_TERMS = {
    "BTC": ("bitcoin", " btc ", "spot bitcoin", "bitcoin etf", "bitcoin trust"),
    "ETH": ("ethereum", "ether", " eth ", "staking", "beacon chain", "eth2"),
    "SOL": ("solana", " sol ", "$sol"),
}
GENERAL_TERMS = (
    "cryptocurrency", "crypto asset", "digital asset", "blockchain", "virtual currency",
    "decentralized finance", "defi", "token", "exchange-traded fund",
)
ACTION_TERMS = (
    "approved", "approval", "denied", "order", "charges", "complaint", "settlement",
    "launch", "mainnet", "hard fork", "upgrade", "release", "security fix", "vulnerability",
    "exploit", "emergency patch", "consensus", "deprecation", "finalized", "listing",
    "registration statement", "proposed rule", "acquisition", "custody", "injunction",
)
EDUCATIONAL_TERMS = (
    "explainer", "beginner", "tutorial", "community roundup", "weekly update", "quick update",
    "conference", "devcon", "grant", "fellowship", "workshop", "videos and pictures",
)
MILESTONES = (
    "frontier", "homestead", "dao", "byzantium", "constantinople", "petersburg", "istanbul",
    "muir glacier", "beacon", "merge", "serenity", "altair", "bellatrix", "shapella",
    "dencun", "mainnet", "hard fork", "security alert",
)


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = re.sub(r"/+", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def normalize_title(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", (title or "").lower())
    return " ".join(value.split())


def clean_text(value: str) -> str:
    return " ".join((value or "").replace("\x00", " ").split())


def content_hash(title: str, body: str) -> str:
    return hashlib.sha256(f"{normalize_title(title)}\n{clean_text(body)}".encode("utf-8")).hexdigest()


def detect_assets(text: str, default_asset: str | None = None) -> tuple[list[str], list[str]]:
    padded = f" {clean_text(text).lower()} "
    assets = [asset for asset, terms in ASSET_TERMS.items() if any(term in padded for term in terms)]
    matched = [term.strip() for terms in ASSET_TERMS.values() for term in terms if term in padded]
    matched.extend(term for term in GENERAL_TERMS if term in padded)
    if not assets and default_asset:
        assets = [default_asset]
    return assets, sorted(set(matched))


def local_relevance(
    title: str,
    body: str,
    *,
    default_asset: str | None = None,
    channel: str = "",
    form_type: str | None = None,
) -> dict[str, Any]:
    text = clean_text(f"{title}\n{body}").lower()
    assets, matched = detect_assets(text, default_asset)
    direct_hits = sum(any(term in f" {text} " for term in terms) for terms in ASSET_TERMS.values())
    general_hits = sum(term in text for term in GENERAL_TERMS)
    action_hits = sum(term in text for term in ACTION_TERMS)
    educational = any(term in text[:1200] for term in EDUCATIONAL_TERMS)
    score = min(100, direct_hits * 35 + min(general_hits, 2) * 12 + min(action_hits, 3) * 12)
    if channel.startswith("github") and default_asset:
        score = min(100, score + 15)
    if channel == "ethereum_foundation" and default_asset == "ETH":
        score = min(100, score + 15)
    if form_type and form_type.upper().startswith(("S-1", "8-K", "N-1A", "485", "424B")):
        score = min(100, score + 8)
    if educational and action_hits == 0:
        score = max(0, score - 40)
    crypto_relevant = bool(assets) and score >= 60
    relevance_class = "direct" if direct_hits else "indirect" if general_hits else "none"
    if not assets:
        reason = "no_supported_asset"
    elif action_hits == 0:
        reason = "no_concrete_high_impact_event"
    elif score < 60:
        reason = "below_conservative_relevance_threshold"
    elif educational and action_hits < 2:
        reason = "educational_or_routine_content"
        crypto_relevant = False
    else:
        reason = "accepted"
    return {
        "crypto_relevant": crypto_relevant,
        "assets": assets,
        "relevance_score": score,
        "relevance_class": relevance_class,
        "rejection_reason": None if crypto_relevant else reason,
        "matched_keywords": matched,
        "matched_entities": assets,
        "matched_protocol": default_asset,
    }


def infer_event_type(title: str, body: str) -> str:
    text = clean_text(f"{title} {body}").lower()
    if any(term in text for term in ("vulnerability", "exploit", "security alert", "security fix", "emergency patch")):
        return "security_event"
    if any(term in text for term in ("charges", "complaint", "injunction", "settlement", "legal action")):
        return "legal_action"
    if any(term in text for term in ("approved", "approval", "denied", "commission order")):
        return "official_decision"
    if any(term in text for term in ("hard fork", "upgrade", "consensus", "mainnet", "protocol")):
        return "protocol_update"
    if any(term in text for term in ("release", "launch", "listing")):
        return "product_launch"
    if any(term in text for term in ("etf", "fund", "institutional", "trust")):
        return "institutional"
    return "other"


def target_window(asset: str, timestamp: datetime, current_earliest: dict[str, datetime]) -> bool:
    value = timestamp.astimezone(timezone.utc)
    if asset in ("BTC", "ETH"):
        return value >= datetime(2017, 1, 1, tzinfo=timezone.utc) and value < current_earliest[asset]
    # SOL source records may exist earlier, but observations are admitted only when candles do.
    return value >= datetime(2020, 3, 16, tzinfo=timezone.utc) and value < current_earliest[asset]


def group_signature(asset: str, title: str, timestamp: datetime) -> str:
    normalized = normalize_title(title)
    milestone = next((name for name in MILESTONES if name in normalized), None)
    basis = f"{asset}|{milestone or normalized[:100]}|{timestamp:%Y-%m}"
    return "stage16b-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def near_duplicate_title(left: str, right: str) -> bool:
    a, b = set(normalize_title(left).split()), set(normalize_title(right).split())
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.85
