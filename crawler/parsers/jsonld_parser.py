"""Defensive JSON-LD extraction helpers."""
import json
from collections.abc import Iterator
from typing import Any
from bs4 import BeautifulSoup

def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)

def extract_jsonld_objects(html: str) -> list[dict[str, Any]]:
    """Parse valid JSON-LD objects while ignoring malformed blocks."""
    objects: list[dict[str, Any]] = []
    for node in BeautifulSoup(html, "lxml").select('script[type="application/ld+json"]'):
        try:
            objects.extend(_walk(json.loads(node.string or node.get_text())))
        except (TypeError, json.JSONDecodeError):
            continue
    return objects

def find_jsonld_value(html: str, key: str) -> str | None:
    for obj in extract_jsonld_objects(html):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
