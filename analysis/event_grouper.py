"""Basic grouping of similar headlines into events."""
import re
from difflib import SequenceMatcher
from uuid import uuid4

def normalize_title(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))

def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()

def new_event_group_id() -> str:
    return uuid4().hex
