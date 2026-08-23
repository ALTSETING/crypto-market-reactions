"""Conservative local relevance and explicit asset-evidence detector."""

from __future__ import annotations

import re
import unicodedata


ASSET_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "BTC": (
        re.compile(r"(?<![\w$])bitcoin(?!\w)", re.IGNORECASE),
        re.compile(r"(?<![\w$])btc(?!\w)", re.IGNORECASE),
        re.compile(r"\$btc\b", re.IGNORECASE),
    ),
    "ETH": (
        re.compile(r"(?<![\w$])ethereum(?!\w)", re.IGNORECASE),
        re.compile(r"(?<![\w$])ether(?!\w)", re.IGNORECASE),
        re.compile(r"(?<![\w$])eth(?!\w)", re.IGNORECASE),
        re.compile(r"\$eth\b", re.IGNORECASE),
    ),
    "SOL": (
        re.compile(
            r"(?<![\w$])solana(?!\w)(?!\s+(?:(?:\d+\s+)?beach|california|ca\b))",
            re.IGNORECASE,
        ),
        re.compile(r"\$sol\b", re.IGNORECASE),
        re.compile(r"(?<![\w$])SOL(?!\w)"),
        re.compile(
            r"(?<![\w$])sol\s+(?:token|price|etf|network|protocol|blockchain|market|news)(?!\w)",
            re.IGNORECASE,
        ),
    ),
}

GENERAL_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?<!\w)cryptocurrenc(?:y|ies)(?!\w)",
        r"(?<!\w)crypto(?!\w)",
        r"(?<!\w)digital assets?(?!\w)",
        r"(?<!\w)blockchain(?!\w)",
        r"(?<!\w)stablecoins?(?!\w)",
        r"(?<!\w)tokens?(?!\w)",
        r"(?<!\w)tokenization(?!\w)",
        r"(?<!\w)mining(?!\w)",
        r"(?<!\w)crypto exchange(?!\w)",
        r"(?<!\w)crypto etf(?!\w)",
    )
)

# These labelled fragments describe the source/company or a previous model's
# output. They are not evidence contained in the event material itself.
METADATA_FRAGMENT = re.compile(
    r"(?:^|[.;\n])\s*(?:company|issuer|source)\s+(?:metadata|relevance)\s*:[^;\n]*"
    r"|(?:^|[.;\n])\s*(?:btc|eth|sol)\s+relevance(?:\s+score)?\s*:[^;\n]*",
    re.IGNORECASE,
)


def normalize_evidence_text(text: str) -> str:
    """Normalize material and remove labelled non-content metadata fragments."""

    normalized = unicodedata.normalize("NFKC", text or "")
    without_metadata = METADATA_FRAGMENT.sub(" ", normalized)
    return re.sub(r"\s+", " ", without_metadata).strip()


def detect_crypto_relevance(text: str) -> tuple[list[str], float, dict[str, int]]:
    """Return explicitly evidenced assets and an independent crypto relevance score.

    General crypto vocabulary contributes to relevance but never creates an
    asset assignment. Asset order is stable, making repeat classification
    deterministic.
    """

    evidence = normalize_evidence_text(text)
    hits = {
        asset: sum(bool(pattern.search(evidence)) for pattern in patterns)
        for asset, patterns in ASSET_PATTERNS.items()
    }
    general = sum(bool(pattern.search(evidence)) for pattern in GENERAL_PATTERNS)
    assets = [asset for asset in ("BTC", "ETH", "SOL") if hits[asset]]
    score = min(1.0, 0.30 * general + 0.45 * sum(hits.values()))
    return assets, score, {**hits, "general": general}
