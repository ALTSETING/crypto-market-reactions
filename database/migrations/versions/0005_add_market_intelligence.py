"""add isolated stage 13.5 market intelligence tables"""
from alembic import op
import sqlalchemy as sa

revision="0005_add_market_intelligence"
down_revision="0004_add_market_context_evidence"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("news_early_reactions",
        sa.Column("id",sa.BigInteger(),primary_key=True),sa.Column("news_id",sa.BigInteger(),nullable=False),
        sa.Column("symbol",sa.String(20),nullable=False),sa.Column("baseline_time",sa.DateTime(timezone=True),nullable=False),sa.Column("latency_minutes",sa.Integer(),nullable=False),
        *[sa.Column(f"return_{h}m",sa.Numeric(16,8)) for h in (1,2,3,5,10,15)],
        *[sa.Column(f"abnormal_return_{h}m",sa.Numeric(16,8)) for h in (1,2,3,5,10,15)],
        *[sa.Column(f"pre_return_{h}m",sa.Numeric(16,8)) for h in (1,2,3,5,10,15)],
        sa.Column("max_favorable_5m",sa.Numeric(16,8)),sa.Column("max_adverse_5m",sa.Numeric(16,8)),sa.Column("max_absolute_5m",sa.Numeric(16,8)),
        sa.Column("realized_vol_5m",sa.Numeric(16,8)),sa.Column("volume_shock_5m",sa.Numeric(16,8)),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint("news_id","symbol","latency_minutes",name="uq_early_reaction_news_symbol_latency"))
    op.create_index("ix_early_reaction_baseline","news_early_reactions",["baseline_time"])
    op.create_table("primary_source_events",
        sa.Column("id",sa.BigInteger(),primary_key=True),sa.Column("source",sa.String(100),nullable=False),sa.Column("source_type",sa.String(30),nullable=False),
        sa.Column("url",sa.Text(),nullable=False),sa.Column("canonical_url",sa.Text()),sa.Column("title",sa.Text(),nullable=False),sa.Column("body",sa.Text(),nullable=False),
        sa.Column("published_at",sa.DateTime(timezone=True),nullable=False),sa.Column("modified_at",sa.DateTime(timezone=True)),sa.Column("discovered_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("time_source",sa.String(50),nullable=False),sa.Column("time_confidence",sa.Numeric(4,3),nullable=False),sa.Column("content_hash",sa.String(64),nullable=False),
        sa.Column("event_group_id",sa.String(64)),sa.Column("assets_json",sa.Text(),nullable=False,server_default='["ETH"]'),sa.Column("is_valid",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.UniqueConstraint("url",name="uq_primary_source_url"),sa.UniqueConstraint("content_hash",name="uq_primary_source_content_hash"))
    op.create_index("ix_primary_source_published","primary_source_events",["published_at"]);op.create_index("ix_primary_source_event_group","primary_source_events",["event_group_id"])
    op.create_index("uq_primary_source_canonical_not_null","primary_source_events",["canonical_url"],unique=True,postgresql_where=sa.text("canonical_url IS NOT NULL"))
    op.create_table("event_information_timeline",
        sa.Column("event_key",sa.String(100),primary_key=True),sa.Column("earliest_primary_news_id",sa.BigInteger()),sa.Column("earliest_media_news_id",sa.BigInteger(),nullable=False),
        sa.Column("earliest_information_time",sa.DateTime(timezone=True),nullable=False),sa.Column("primary_source_time",sa.DateTime(timezone=True)),sa.Column("media_source_time",sa.DateTime(timezone=True),nullable=False),
        sa.Column("delay_seconds",sa.Integer()),sa.Column("source_count",sa.Integer(),nullable=False),sa.Column("article_count",sa.Integer(),nullable=False),
        sa.Column("grouping_method",sa.String(50),nullable=False),sa.Column("grouping_confidence",sa.Numeric(5,4),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_table("futures_funding_rates",
        sa.Column("id",sa.BigInteger(),primary_key=True),sa.Column("symbol",sa.String(20),nullable=False),sa.Column("funding_time",sa.DateTime(timezone=True),nullable=False),
        sa.Column("funding_rate",sa.Numeric(20,12),nullable=False),sa.Column("mark_price",sa.Numeric(30,12)),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint("symbol","funding_time",name="uq_funding_symbol_time"))
    op.create_table("futures_open_interest",
        sa.Column("id",sa.BigInteger(),primary_key=True),sa.Column("symbol",sa.String(20),nullable=False),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),
        sa.Column("open_interest",sa.Numeric(30,12),nullable=False),sa.Column("open_interest_value",sa.Numeric(30,8)),sa.Column("period",sa.String(10),nullable=False),
        sa.UniqueConstraint("symbol","timestamp","period",name="uq_oi_symbol_time_period"))
    op.create_table("futures_long_short_ratios",
        sa.Column("id",sa.BigInteger(),primary_key=True),sa.Column("symbol",sa.String(20),nullable=False),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),
        sa.Column("ratio_type",sa.String(30),nullable=False),sa.Column("long_account",sa.Numeric(20,12)),sa.Column("short_account",sa.Numeric(20,12)),
        sa.Column("long_short_ratio",sa.Numeric(20,12),nullable=False),sa.Column("period",sa.String(10),nullable=False),
        sa.UniqueConstraint("symbol","timestamp","ratio_type","period",name="uq_ls_symbol_time_type_period"))
    op.create_table("futures_taker_volume",
        sa.Column("id",sa.BigInteger(),primary_key=True),sa.Column("symbol",sa.String(20),nullable=False),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),
        sa.Column("buy_sell_ratio",sa.Numeric(20,12),nullable=False),sa.Column("buy_volume",sa.Numeric(30,12)),sa.Column("sell_volume",sa.Numeric(30,12)),sa.Column("period",sa.String(10),nullable=False),
        sa.UniqueConstraint("symbol","timestamp","period",name="uq_taker_symbol_time_period"))
    for table,column in (("futures_funding_rates","funding_time"),("futures_open_interest","timestamp"),("futures_long_short_ratios","timestamp"),("futures_taker_volume","timestamp")):
        op.create_index(f"ix_{table}_symbol_time",table,["symbol",column])

def downgrade():
    for table in ("futures_taker_volume","futures_long_short_ratios","futures_open_interest","futures_funding_rates","event_information_timeline","primary_source_events","news_early_reactions"):
        op.drop_table(table)
