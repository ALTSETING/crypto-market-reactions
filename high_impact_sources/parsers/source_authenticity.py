from urllib.parse import urlparse
from high_impact_sources.config import ALLOWED_DOMAINS, OFFICIAL_HANDLES

def validate_official(source: str, url: str, handle: str | None = None) -> bool:
    host=urlparse(url).hostname or ""
    if host.lower() not in ALLOWED_DOMAINS.get(source, ()): return False
    expected=OFFICIAL_HANDLES.get(source)
    return not expected or (handle or "").lstrip("@").lower()==expected.lower()
