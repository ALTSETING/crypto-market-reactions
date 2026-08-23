from high_impact_sources.config import OFFICIAL_HANDLES, RELEVANCE_THRESHOLD
from high_impact_sources.parsers.source_authenticity import validate_official

def validate_event(event) -> tuple[bool,str|None]:
    if not validate_official(event.source,event.url,event.author_handle):return False,"unofficial_source_or_handle"
    if not event.body.strip():return False,"empty_body"
    if event.published_at.utcoffset().total_seconds()!=0:return False,"timestamp_not_utc"
    if not (0<=event.time_confidence<=1 and 0<=event.source_authenticity<=1):return False,"invalid_confidence"
    if event.crypto_relevance<RELEVANCE_THRESHOLD:return False,"below_crypto_relevance_threshold"
    if event.source in OFFICIAL_HANDLES and event.author_handle and event.author_handle.lstrip('@').lower()!=OFFICIAL_HANDLES[event.source].lower():return False,"wrong_author_handle"
    return True,None
