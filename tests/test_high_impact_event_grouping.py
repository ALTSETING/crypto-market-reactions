from datetime import datetime,timezone,timedelta
from high_impact_sources.pipelines.event_grouping_pipeline import grouping_signature,earliest_verified
from high_impact_sources.schemas import HighImpactEvent

def event(url,minute,auth=1):return HighImpactEvent("sec","regulator","sec",url,"Ethereum ETF decision",datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(minutes=minute),title="SEC Ethereum ETF",source_authenticity=auth,assets=["ETH"])
def test_grouping_does_not_accept_price_input():assert grouping_signature.__code__.co_argcount==1
def test_grouping_deterministic():assert grouping_signature(event("https://sec.gov/a",0))==grouping_signature(event("https://sec.gov/b",0))
def test_earliest_verified_selected():assert earliest_verified([event("https://sec.gov/a",2),event("https://sec.gov/b",1)]).url.endswith("/b")
def test_unverified_not_selected():assert earliest_verified([event("https://sec.gov/a",0,.2),event("https://sec.gov/b",1,1)]).url.endswith("/b")
