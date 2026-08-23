import pytest
from crawler.parsers.asset_detector import detect_assets

@pytest.mark.parametrize("term,asset", [("Bitcoin", "BTC"), ("BTC", "BTC"), ("Ethereum", "ETH"), ("ETH", "ETH"), ("Ether", "ETH"), ("Solana", "SOL"), ("SOL", "SOL")])
def test_detect_supported_terms(term, asset):
    assert [item["asset"] for item in detect_assets(term, "market news")] == [asset]

def test_multiple_assets():
    assert {item["asset"] for item in detect_assets("BTC and ETH", "Solana rallied")} == {"BTC", "ETH", "SOL"}

def test_no_asset_and_no_partial_sol_match():
    assert detect_assets("Macro markets", "A solution was consolidated") == []

def test_title_has_greater_confidence():
    assert detect_assets("Bitcoin rises", "")[0]["confidence"] > detect_assets("", "Bitcoin rises")[0]["confidence"]
