"""Detect supported crypto assets in article text."""
import re
from typing import TypedDict
from app.config import SUPPORTED_ASSETS

class DetectedAsset(TypedDict):
    asset: str
    symbol: str
    confidence: float
    detection_source: str

def _contains(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword.lower())
    pattern = rf"(?<!\w){escaped}(?!\w)" if keyword.startswith("$") else rf"(?<![\w$]){escaped}(?!\w)"
    return re.search(pattern, text.lower(), flags=re.IGNORECASE) is not None

def detect_assets(title: str, body: str) -> list[DetectedAsset]:
    """Return every supported asset mentioned in title or body once."""
    results: list[DetectedAsset] = []
    for asset, config in SUPPORTED_ASSETS.items():
        in_title = any(_contains(title, name) for name in config["names"])
        in_body = any(_contains(body, name) for name in config["names"])
        if in_title or in_body:
            results.append({"asset": asset, "symbol": config["symbol"], "confidence": 0.95 if in_title else 0.75, "detection_source": "title_keywords" if in_title else "body_keywords"})
    return results
