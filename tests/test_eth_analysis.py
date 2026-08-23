from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from analysis.openai_analyzer import (
    FORBIDDEN_FIELDS,
    SYSTEM_PROMPT,
    analysis_json_schema,
    assert_no_data_leakage,
    estimate_token_count,
    prepare_eth_analysis_input,
    validate_analysis_payload,
)
from database.models import Base, NewsArticle, NewsAsset, NewsAnalysis
from database.repositories.analysis_repository import AnalysisRepository
from analysis.eth_ab_test import PreparedArticle, build_preflight, deterministic_sample


def _make_article(title: str, body: str, *, news_id: int = 1) -> NewsArticle:
    return NewsArticle(
        id=news_id,
        source="test",
        url=f"https://example.com/{news_id}",
        title=title,
        body=body,
        author="tester",
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        discovered_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        crawled_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        published_at_raw="2024-01-01T00:00:00Z",
        time_source="parser",
        time_confidence=0.99,
        content_hash=f"hash-{news_id}",
        is_valid=True,
    )


def test_prepare_eth_analysis_input_strips_html_and_disclaimer():
    article = {
        "title": "ETH staking upgrade arrives",
        "body": "<html><body><div class='ad'>Buy now</div><p>ETH staking upgrade arrives with major validator changes.</p><p>Disclaimer: This article is for informational purposes only.</p><p>SEC approved another ETF.</p></body></html>",
    }

    prompt = prepare_eth_analysis_input(article)

    assert "Asset focus: ETH" in prompt
    assert "Title: ETH staking upgrade arrives" in prompt
    assert "Buy now" not in prompt
    assert "Disclaimer" not in prompt
    assert "<html" not in prompt
    assert "SEC approved" in prompt


def test_prepare_eth_analysis_input_stays_within_budget():
    article = {
        "title": "ETH network update",
        "body": " ".join(["This paragraph explains Ethereum network activity. " for _ in range(1000)]),
    }

    prompt = prepare_eth_analysis_input(article, max_tokens=900)
    assert estimate_token_count(prompt) <= 900


def test_eth_selection_returns_unique_eth_news_only():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        article_eth = _make_article("ETH ETF", "Ethereum ETF news", news_id=1)
        article_eth.assets = [NewsAsset(news=article_eth, asset="ETH", symbol="ETHUSDT", confidence=0.99, detection_source="test")]
        article_btc = _make_article("BTC rally", "Bitcoin-only story", news_id=2)
        article_btc.assets = [NewsAsset(news=article_btc, asset="BTC", symbol="BTCUSDT", confidence=0.99, detection_source="test")]
        article_multi = _make_article("ETH and BTC", "Mixed asset story", news_id=3)
        article_multi.assets = [
            NewsAsset(news=article_multi, asset="ETH", symbol="ETHUSDT", confidence=0.99, detection_source="test"),
            NewsAsset(news=article_multi, asset="BTC", symbol="BTCUSDT", confidence=0.88, detection_source="test"),
        ]
        article_sol = _make_article("SOL upgrade", "Solana-only story", news_id=4)
        article_sol.assets = [NewsAsset(news=article_sol, asset="SOL", symbol="SOLUSDT", confidence=0.99, detection_source="test")]
        session.add_all([article_eth, article_btc, article_multi, article_sol])
        session.commit()

        selected = AnalysisRepository(session).get_eth_news_candidates(limit=10)

    assert [article.id for article in selected] == [1, 3]


def test_validate_analysis_payload_rejects_invalid_values():
    invalid_payload = {
        "sentiment": 101,
        "importance": 50,
        "novelty": 10,
        "credibility": 20,
        "direction": "bearish",
        "category": "regulation",
        "horizon": "days",
        "confidence": 80,
        "eth_relevance": 90,
    }

    assert validate_analysis_payload(invalid_payload) is False


def test_prompt_has_strict_schema_and_no_market_reaction_fields():
    schema = analysis_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "explanation" not in schema["properties"]
    assert "summary" not in schema["properties"]
    assert_no_data_leakage(SYSTEM_PROMPT)
    assert all(field not in SYSTEM_PROMPT for field in FORBIDDEN_FIELDS)


def test_compact_input_ignores_market_reaction_attributes():
    article = {
        "title": "Ethereum validator update",
        "body": "Ethereum validators approved a network update.",
        "baseline_price": 1234,
        "return_5m": 9.9,
        "news_market_reactions": [{"return_1h": 5}],
    }

    prompt = prepare_eth_analysis_input(article)

    assert "1234" not in prompt
    assert "9.9" not in prompt
    assert_no_data_leakage(prompt)


def test_payload_rejects_extra_fields_and_boolean_scores():
    payload = {
        "sentiment": 0,
        "importance": 50,
        "novelty": 50,
        "credibility": 50,
        "direction": "neutral",
        "category": "other",
        "horizon": "unclear",
        "confidence": 50,
        "eth_relevance": 50,
        "summary": "not allowed",
    }
    assert validate_analysis_payload(payload) is False
    payload.pop("summary")
    payload["importance"] = True
    assert validate_analysis_payload(payload) is False


def test_ab_sample_is_reproducible_and_preflight_enforces_budget():
    articles = [type("Article", (), {"id": news_id})() for news_id in range(1, 101)]
    first = deterministic_sample(articles, 50, 20260718)
    second = deterministic_sample(list(reversed(articles)), 50, 20260718)
    assert [article.id for article in first] == [article.id for article in second]

    prepared = [
        PreparedArticle(
            news_id=article.id,
            title=str(article.id),
            input_text="Asset focus: ETH\nTitle: test\nText: Ethereum update.",
            input_hash=str(article.id),
            estimated_input_tokens=100,
        )
        for article in first
    ]
    preflight = build_preflight(
        prepared,
        prompt_version="eth_label_v1",
        seed=20260718,
        max_output_tokens=140,
        max_cost_usd=0.10,
    )
    assert preflight["sample_size"] == 50
    assert preflight["estimated_total_cost_usd"] < 0.10
