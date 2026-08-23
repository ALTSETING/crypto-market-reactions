import pandas as pd

from scripts.processing.build_website_dataset import _classified_assets


def group_with_scores(**scores: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"asset": list(scores), "sem_asset_relevance": list(scores.values())}
    )


def test_generic_filing_does_not_inherit_low_score_assets() -> None:
    group = group_with_scores(BTC=0.03, ETH=0.03, SOL=0.02)
    assert _classified_assets(
        group,
        "Coinbase Global 8-K filing 0001679788-26-000075",
        "Issuer relevance: cryptocurrency exchange and digital assets.",
    ) == []


def test_title_evidence_is_sufficient_even_without_an_existing_asset_row() -> None:
    assert _classified_assets(
        group_with_scores(ETH=0.60),
        "Coinbase filing discusses Solana support",
        "Official filing metadata.",
    ) == ["SOL"]


def test_body_evidence_requires_semantic_corroboration() -> None:
    title = "Protocol market update"
    body = "The substantive report discusses Ethereum and Solana validators."
    assert _classified_assets(
        group_with_scores(ETH=0.70, SOL=0.02), title, body
    ) == ["ETH"]
    assert _classified_assets(
        group_with_scores(ETH=0.70, SOL=0.80), title, body
    ) == ["ETH", "SOL"]


def test_website_reclassification_is_deterministic() -> None:
    group = group_with_scores(BTC=0.8, ETH=0.7, SOL=0.6)
    expected = _classified_assets(group, "Bitcoin and Solana", "Ethereum protocol")
    assert expected == ["BTC", "ETH", "SOL"]
    assert _classified_assets(group, "Bitcoin and Solana", "Ethereum protocol") == expected
