from datetime import datetime,timedelta,timezone
from high_impact_sources.parsers.timestamp_parser import parse_timestamp,next_full_minute

def test_published_time_utc():assert parse_timestamp("2026-01-01T02:00:00+02:00")==datetime(2026,1,1,tzinfo=timezone.utc)
def test_naive_time_becomes_utc():assert parse_timestamp(datetime(2026,1,1)).tzinfo==timezone.utc
def test_baseline_next_full_minute():assert next_full_minute(datetime(2026,1,1,14,35,12,tzinfo=timezone.utc)).minute==36
def test_partial_candle_not_used():assert next_full_minute(datetime(2026,1,1,14,35,59,tzinfo=timezone.utc))==datetime(2026,1,1,14,36,tzinfo=timezone.utc)
