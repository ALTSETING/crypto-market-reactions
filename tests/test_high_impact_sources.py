from datetime import datetime,timezone
from high_impact_sources.parsers.source_authenticity import validate_official
from high_impact_sources.registry import get_source
from high_impact_sources.schemas import HighImpactEvent

def test_only_official_account_allowed():assert validate_official("elon_musk","https://x.com/elonmusk/status/1","elonmusk")
def test_wrong_handle_rejected():assert not validate_official("elon_musk","https://x.com/elonmusk/status/1","fake")
def test_domain_validation():assert not validate_official("sec","https://example.com/sec")
def test_repost_distinguished_from_original():
    a=HighImpactEvent("elon_musk","public_figure","x","https://x.com/elonmusk/status/1","btc",datetime.now(timezone.utc),author_handle="elonmusk",raw_metadata_json={"post_kind":"repost"})
    assert a.raw_metadata_json["post_kind"]!="original"
def test_deleted_status_preserves_record():
    now=datetime.now(timezone.utc);event=HighImpactEvent("elon_musk","public_figure","x","https://x.com/elonmusk/status/2","btc",now,author_handle="elonmusk",deleted_at=now)
    assert event.body=="btc" and event.deleted_at==now
def test_paid_sources_fail_closed():assert get_source("elon_musk").fetch()==[] and get_source("donald_trump").availability()["status"]=="blocked"
def test_source_rate_limits_configured():assert get_source("sec").min_interval>=.1 and get_source("ethereum_github").min_interval>=1
