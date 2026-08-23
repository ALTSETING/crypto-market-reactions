from datetime import datetime, timezone

from high_impact_sources.stage16b_backfill import (
    group_signature,
    local_relevance,
    near_duplicate_title,
    normalize_url,
    target_window,
)


def test_local_relevance_requires_concrete_event():
    routine = local_relevance("Ethereum beginner guide", "A tutorial about Ethereum", default_asset="ETH")
    concrete = local_relevance("Ethereum hard fork", "The mainnet upgrade was finalized", default_asset="ETH")
    assert not routine["crypto_relevant"]
    assert concrete["crypto_relevant"]


def test_sec_asset_detection_is_not_keyword_only():
    result = local_relevance("Annual report", "Bitcoin may be discussed as a general market risk.", form_type="10-K")
    assert not result["crypto_relevant"]


def test_target_windows_stop_before_existing_event():
    earliest = {
        "BTC": datetime(2021, 5, 13, tzinfo=timezone.utc),
        "ETH": datetime(2020, 1, 11, tzinfo=timezone.utc),
        "SOL": datetime(2022, 2, 3, tzinfo=timezone.utc),
    }
    assert target_window("BTC", datetime(2021, 5, 12, tzinfo=timezone.utc), earliest)
    assert not target_window("BTC", earliest["BTC"], earliest)


def test_canonical_url_drops_tracking_and_trailing_slash():
    assert normalize_url("HTTPS://Example.com/a/?utm_source=x") == "https://example.com/a"


def test_group_signature_groups_named_milestone_within_month():
    first = group_signature("ETH", "Ethereum Istanbul Upgrade Announcement", datetime(2019, 11, 1, tzinfo=timezone.utc))
    second = group_signature("ETH", "Geth release for Istanbul hard fork", datetime(2019, 11, 30, tzinfo=timezone.utc))
    assert first == second


def test_near_duplicate_title():
    assert near_duplicate_title("Ethereum Mainnet Upgrade Announcement", "Ethereum mainnet upgrade announcement!")
