"""Queries and persistence for news market reactions."""
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from database.models import MarketCandle, NewsArticle, NewsAsset, NewsMarketReaction
from market.reaction_calculator import baseline_time, calculate_reaction

class ReactionRepository:
    def __init__(self, session: Session): self.session = session
    def pending(self, limit: int = 100, start=None, end=None, source: str | None = None, symbols: list[str] | None = None):
        exists = select(NewsMarketReaction.id).where(NewsMarketReaction.news_id == NewsArticle.id, NewsMarketReaction.symbol == NewsAsset.symbol).exists()
        statement = select(NewsArticle, NewsAsset.symbol).join(NewsAsset).where(~exists, NewsArticle.is_valid.is_(True))
        if start is not None: statement = statement.where(NewsArticle.published_at >= start)
        if end is not None: statement = statement.where(NewsArticle.published_at < end)
        if source: statement = statement.where(NewsArticle.source == source)
        if symbols: statement = statement.where(NewsAsset.symbol.in_(symbols))
        return self.session.execute(statement.order_by(NewsArticle.published_at).limit(limit)).all()

    def calculate_and_add(self, news: NewsArticle, symbol: str) -> NewsMarketReaction | None:
        start = baseline_time(news.published_at)
        candles = list(self.session.scalars(select(MarketCandle).where(MarketCandle.symbol == symbol, MarketCandle.interval == "1m", MarketCandle.open_time >= start, MarketCandle.open_time <= start + timedelta(hours=24)).order_by(MarketCandle.open_time)))
        values = calculate_reaction(news.published_at, candles)
        if values is None: return None
        reaction = NewsMarketReaction(news_id=news.id, symbol=symbol, **values)
        self.session.add(reaction); return reaction
