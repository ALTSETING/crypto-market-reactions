from datetime import datetime, timezone

import pandas as pd

from market_intelligence.primary_sources.base_source import BasePrimarySource, PrimarySourceEvent
from market_intelligence.timing.first_information_detector import match_primary_to_media


def test_primary_event_hash_is_stable():
    event = PrimarySourceEvent("ethereum_foundation", "project_blog", "https://example.test/a", "Title", "Body", datetime.now(timezone.utc))
    assert event.content_hash == event.content_hash and len(event.content_hash) == 64


def test_robots_failure_is_fail_closed(monkeypatch):
    source = BasePrimarySource(timeout=1)
    monkeypatch.setattr(source.session, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert source.robots_allowed("https://example.test/a") is False


def test_primary_matching_uses_text_and_time_only():
    primary = pd.DataFrame({"id": [7], "title": ["Ethereum protocol upgrade announced"], "published_at": [pd.Timestamp("2024-01-01", tz="UTC")]})
    media = pd.DataFrame({"event_key": ["e1"], "title": ["Ethereum protocol upgrade announced today"], "published_at": [pd.Timestamp("2024-01-02", tz="UTC")]})
    result = match_primary_to_media(primary, media, threshold=.1)
    assert result.iloc[0].primary_id == 7 and "return" not in " ".join(result.columns)
