"""Create initial news and market schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author", sa.String(255)),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True)),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at_raw", sa.Text()),
        sa.Column("time_source", sa.String(50), nullable=False),
        sa.Column("time_confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("event_group_id", sa.String(64)),
        sa.Column("is_valid", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"])
    op.create_index("ix_news_articles_content_hash", "news_articles", ["content_hash"])
    op.create_index("ix_news_articles_canonical_url", "news_articles", ["canonical_url"])
    op.create_index("ix_news_articles_event_group_id", "news_articles", ["event_group_id"])

    op.create_table(
        "news_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset", sa.String(10), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("detection_source", sa.String(50), nullable=False),
        sa.UniqueConstraint("news_id", "symbol", name="uq_news_assets_news_symbol"),
    )
    op.create_table(
        "market_candles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("interval", sa.String(10), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(30, 12), nullable=False),
        sa.Column("high", sa.Numeric(30, 12), nullable=False),
        sa.Column("low", sa.Numeric(30, 12), nullable=False),
        sa.Column("close", sa.Numeric(30, 12), nullable=False),
        sa.Column("volume", sa.Numeric(38, 12), nullable=False),
        sa.UniqueConstraint("symbol", "interval", "open_time", name="uq_candles_symbol_interval_time"),
    )
    op.create_index("ix_market_candles_open_time", "market_candles", ["open_time"])
    op.create_table(
        "news_market_reactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("baseline_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_price", sa.Numeric(30, 12), nullable=False),
        sa.Column("return_5m", sa.Numeric(14, 6)),
        sa.Column("return_15m", sa.Numeric(14, 6)),
        sa.Column("return_30m", sa.Numeric(14, 6)),
        sa.Column("return_1h", sa.Numeric(14, 6)),
        sa.Column("return_4h", sa.Numeric(14, 6)),
        sa.Column("return_24h", sa.Numeric(14, 6)),
        sa.Column("max_return_1h", sa.Numeric(14, 6)),
        sa.Column("min_return_1h", sa.Numeric(14, 6)),
        sa.Column("volume_change_1h", sa.Numeric(14, 6)),
        sa.UniqueConstraint("news_id", "symbol", name="uq_reactions_news_symbol"),
    )


def downgrade() -> None:
    op.drop_table("news_market_reactions")
    op.drop_index("ix_market_candles_open_time", table_name="market_candles")
    op.drop_table("market_candles")
    op.drop_table("news_assets")
    op.drop_index("ix_news_articles_event_group_id", table_name="news_articles")
    op.drop_index("ix_news_articles_canonical_url", table_name="news_articles")
    op.drop_index("ix_news_articles_content_hash", table_name="news_articles")
    op.drop_index("ix_news_articles_published_at", table_name="news_articles")
    op.drop_table("news_articles")
