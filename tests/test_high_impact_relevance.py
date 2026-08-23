from high_impact_sources.parsers.crypto_relevance_detector import detect_crypto_relevance

def test_btc_detection():assert detect_crypto_relevance("Bitcoin BTC reserve")[0]==["BTC"]
def test_eth_detection():assert "ETH" in detect_crypto_relevance("Ethereum staking protocol")[0]
def test_sol_detection():assert detect_crypto_relevance("Solana SOL token")[0]==["SOL"]
def test_short_ticker_false_positive():assert "SOL" not in detect_crypto_relevance("we solve problems")[0]
def test_general_crypto_is_relevant_without_inventing_assets():
    assets, relevance, _hits = detect_crypto_relevance("cryptocurrency stablecoin policy")
    assert assets == []
    assert relevance >= 0.35
