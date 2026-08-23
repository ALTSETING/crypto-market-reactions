"""Content/entity/time grouping with no access to market data."""
from hashlib import sha256
from high_impact_sources.parsers.entity_detector import detect_entities

def grouping_signature(event) -> str:
    entities="|".join(x.lower() for x in detect_entities(f"{event.title or ''} {event.body}"))
    day=event.published_at.strftime("%Y-%m-%d")
    assets="|".join(sorted(event.assets))
    tokens=sorted(set((event.title or event.body[:160]).lower().split()))[:12]
    return sha256(f"{day}|{assets}|{entities}|{' '.join(tokens)}".encode()).hexdigest()[:32]

def group_events(events):
    for event in events:event.raw_metadata_json["event_group_id"]=grouping_signature(event)
    return events

def earliest_verified(events):
    return min((e for e in events if e.source_authenticity>=.9),key=lambda e:(e.published_at,-e.time_confidence),default=None)
