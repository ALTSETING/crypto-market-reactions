import pytest

from high_impact_sources.parsers.crypto_relevance_detector import detect_crypto_relevance


def detected_assets(text: str) -> list[str]:
    assets, _score, _hits = detect_crypto_relevance(text)
    return assets


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Coinbase Global 8-K filing 0001679788-26-000075", []),
        ("cryptocurrency exchange and digital assets", []),
        ("Bitcoin adoption increased", ["BTC"]),
        ("Ethereum network upgrade", ["ETH"]),
        ("Solana validator update", ["SOL"]),
        ("Bitcoin and Ethereum market update", ["BTC", "ETH"]),
        ("Solana and Ethereum protocol update", ["ETH", "SOL"]),
        ("General SEC filing by Coinbase Global", []),
        ("Coinbase filing discusses support for Solana", ["SOL"]),
        ("Generic crypto filing; SOL relevance score: 0.02", []),
        ("Company metadata: issuer is a Solana ecosystem company", []),
        ("Courtyard Marriott Solana Beach mortgage loan", []),
        ("Courtyard Marriott Solana 2 Beach mortgage loan", []),
    ],
)
def test_assets_require_concrete_content_evidence(text: str, expected: list[str]) -> None:
    assert detected_assets(text) == expected


def test_reclassification_is_deterministic() -> None:
    text = "Bitcoin, Ethereum and Solana market infrastructure update"
    first = detect_crypto_relevance(text)
    assert detect_crypto_relevance(text) == first
    assert detect_crypto_relevance(text) == first
