"""SQLAlchemy 2.x ORM models for news and market data."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    canonical_url: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    modified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at_raw: Mapped[Optional[str]] = mapped_column(Text)
    time_source: Mapped[str] = mapped_column(String(50), nullable=False)
    time_confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_group_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    assets: Mapped[list["NewsAsset"]] = relationship(
        back_populates="news", cascade="all, delete-orphan"
    )
    reactions: Mapped[list["NewsMarketReaction"]] = relationship(
        back_populates="news", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_news_articles_canonical_url", "canonical_url"),)


class NewsAsset(Base):
    __tablename__ = "news_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"))
    asset: Mapped[str] = mapped_column(String(10), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    detection_source: Mapped[str] = mapped_column(String(50), nullable=False)

    news: Mapped[NewsArticle] = relationship(back_populates="assets")
    __table_args__ = (UniqueConstraint("news_id", "symbol", name="uq_news_assets_news_symbol"),)


class MarketCandle(Base):
    __tablename__ = "market_candles"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "interval", "open_time", name="uq_candles_symbol_interval_time"),
    )


class NewsMarketReaction(Base):
    __tablename__ = "news_market_reactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    baseline_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    baseline_price: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    return_5m: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    return_15m: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    return_30m: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    return_1h: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    return_4h: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    return_24h: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    max_return_1h: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    min_return_1h: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    volume_change_1h: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))

    news: Mapped[NewsArticle] = relationship(back_populates="reactions")
    __table_args__ = (UniqueConstraint("news_id", "symbol", name="uq_reactions_news_symbol"),)


class NewsAnalysis(Base):
    __tablename__ = "news_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_focus: Mapped[str] = mapped_column(String(20), nullable=False, default="ETH")
    sentiment: Mapped[Optional[int]] = mapped_column(default=None)
    importance: Mapped[Optional[int]] = mapped_column(default=None)
    novelty: Mapped[Optional[int]] = mapped_column(default=None)
    credibility: Mapped[Optional[int]] = mapped_column(default=None)
    expected_direction: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    category: Mapped[Optional[str]] = mapped_column(String(50), default=None)
    impact_duration: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    confidence: Mapped[Optional[int]] = mapped_column(default=None)
    asset_relevance: Mapped[Optional[int]] = mapped_column(default=None)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False, default="eth_label_v1")
    input_hash: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    input_tokens: Mapped[Optional[int]] = mapped_column(default=None)
    output_tokens: Mapped[Optional[int]] = mapped_column(default=None)
    total_tokens: Mapped[Optional[int]] = mapped_column(default=None)
    estimated_cost_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), default=None)
    actual_cost_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), default=None)
    raw_response_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    batch_id: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    batch_custom_id: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("news_id", "asset_focus", "model_name", "prompt_version", name="uq_news_analysis_identity"),
        Index("ix_news_analysis_status", "status"),
        Index("ix_news_analysis_batch_id", "batch_id"),
    )


class NewsMarketContextAnalysis(Base):
    __tablename__ = "news_market_context_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_focus: Mapped[str] = mapped_column(String(20), nullable=False, default="ETH")
    surprise_direction: Mapped[Optional[str]] = mapped_column(String(20))
    surprise_magnitude: Mapped[Optional[int]] = mapped_column()
    expected_by_market: Mapped[Optional[int]] = mapped_column()
    expected_by_market_evidence: Mapped[Optional[str]] = mapped_column(String(20))
    already_priced_in: Mapped[Optional[int]] = mapped_column()
    already_priced_in_evidence: Mapped[Optional[str]] = mapped_column(String(20))
    information_freshness: Mapped[Optional[int]] = mapped_column()
    primary_source_probability: Mapped[Optional[int]] = mapped_column()
    primary_source_evidence: Mapped[Optional[str]] = mapped_column(String(20))
    actionable_novelty: Mapped[Optional[int]] = mapped_column()
    event_specificity: Mapped[Optional[int]] = mapped_column()
    confidence: Mapped[Optional[int]] = mapped_column()
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_hash: Mapped[Optional[str]] = mapped_column(String(64))
    input_tokens: Mapped[Optional[int]] = mapped_column()
    output_tokens: Mapped[Optional[int]] = mapped_column()
    total_tokens: Mapped[Optional[int]] = mapped_column()
    actual_cost_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    raw_response_json: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("news_id", "asset_focus", "model_name", "prompt_version", name="uq_market_context_analysis_identity"),
        Index("ix_market_context_analysis_status", "status"),
        CheckConstraint("surprise_direction IS NULL OR surprise_direction IN ('positive','negative','neutral','mixed')", name="ck_market_context_surprise_direction"),
        CheckConstraint("surprise_magnitude IS NULL OR surprise_magnitude BETWEEN 0 AND 100", name="ck_market_context_surprise_magnitude"),
        CheckConstraint("expected_by_market IS NULL OR expected_by_market BETWEEN 0 AND 100", name="ck_market_context_expected"),
        CheckConstraint("already_priced_in IS NULL OR already_priced_in BETWEEN 0 AND 100", name="ck_market_context_priced_in"),
        CheckConstraint("information_freshness IS NULL OR information_freshness BETWEEN 0 AND 100", name="ck_market_context_freshness"),
        CheckConstraint("primary_source_probability IS NULL OR primary_source_probability BETWEEN 0 AND 100", name="ck_market_context_primary_source"),
        CheckConstraint("actionable_novelty IS NULL OR actionable_novelty BETWEEN 0 AND 100", name="ck_market_context_actionable_novelty"),
        CheckConstraint("event_specificity IS NULL OR event_specificity BETWEEN 0 AND 100", name="ck_market_context_event_specificity"),
        CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 100", name="ck_market_context_confidence"),
        CheckConstraint("expected_by_market_evidence IS NULL OR expected_by_market_evidence IN ('sufficient','insufficient')", name="ck_market_context_expected_evidence"),
        CheckConstraint("already_priced_in_evidence IS NULL OR already_priced_in_evidence IN ('sufficient','insufficient')", name="ck_market_context_priced_in_evidence"),
        CheckConstraint("primary_source_evidence IS NULL OR primary_source_evidence IN ('sufficient','insufficient')", name="ck_market_context_primary_evidence"),
    )
