from __future__ import annotations

import pandas as pd
import pytest

from scripts.quality.build_reactions_v2 import first_full_minute_after, reaction_return
from scripts.quality.full_dataset_audit import asset_evidence, normalize_title, record_type


def test_reaction_v2_reference_is_first_full_minute_strictly_after_publication():
    assert first_full_minute_after(pd.Timestamp("2025-01-01T14:30:27Z")) == pd.Timestamp("2025-01-01T14:31:00Z")
    assert first_full_minute_after(pd.Timestamp("2025-01-01T14:30:00Z")) == pd.Timestamp("2025-01-01T14:31:00Z")


def test_reaction_v2_rejects_timezone_naive_publication():
    with pytest.raises(ValueError, match="timezone-aware"):
        first_full_minute_after(pd.Timestamp("2025-01-01 14:30:27"))


def test_reaction_formula_and_missing_candle_rule():
    assert reaction_return(100.0, 101.5) == pytest.approx(1.5)
    assert reaction_return(100.0, None) is None
    assert reaction_return(None, 101.5) is None
    assert reaction_return(0.0, 101.5) is None


@pytest.mark.parametrize(
    ("source", "url", "title", "expected"),
    [
        ("sec", "https://www.sec.gov/Archives/example", "Document", "regulatory_filing"),
        ("eth_github", "https://github.com/ethereum/go-ethereum/commit/a", "core: fix", "github_commit"),
        ("btc_github", "https://github.com/bitcoin/bitcoin/releases/tag/v1", "Release v1", "protocol_release"),
        ("coindesk", "https://www.coindesk.com/example", "Bitcoin rises", "news_article"),
    ],
)
def test_record_type_rules(source, url, title, expected):
    assert record_type(source, url, title) == expected


def test_solana_beach_is_not_sol_evidence_without_crypto_context():
    assert not asset_evidence("City council meeting in Solana Beach", "SOL")
    assert asset_evidence("Solana network validators approve upgrade", "SOL")


def test_generic_coinbase_does_not_imply_btc_or_eth():
    title = "Coinbase publishes quarterly results"
    assert not asset_evidence(title, "BTC")
    assert not asset_evidence(title, "ETH")


def test_normalized_title_supports_deterministic_story_grouping():
    assert normalize_title("Bitcoin ETF — Approved!") == normalize_title("Bitcoin ETF approved")
