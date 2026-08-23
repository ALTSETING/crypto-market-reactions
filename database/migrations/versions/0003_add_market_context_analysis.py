"""Add Stage 11 market-context enrichment table."""
from alembic import op
import sqlalchemy as sa

revision = "0003_add_market_context_analysis"
down_revision = "0002_add_news_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_market_context_analysis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("news_id", sa.Integer(), nullable=False),
        sa.Column("asset_focus", sa.String(20), nullable=False),
        sa.Column("surprise_direction", sa.String(20)),
        sa.Column("surprise_magnitude", sa.Integer()),
        sa.Column("expected_by_market", sa.Integer()),
        sa.Column("already_priced_in", sa.Integer()),
        sa.Column("information_freshness", sa.Integer()),
        sa.Column("primary_source_probability", sa.Integer()),
        sa.Column("actionable_novelty", sa.Integer()),
        sa.Column("event_specificity", sa.Integer()),
        sa.Column("confidence", sa.Integer()),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("actual_cost_usd", sa.Numeric(12, 6)),
        sa.Column("raw_response_json", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["news_id"], ["news_articles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("news_id", "asset_focus", "model_name", "prompt_version", name="uq_market_context_analysis_identity"),
        sa.CheckConstraint("surprise_direction IS NULL OR surprise_direction IN ('positive','negative','neutral','mixed')", name="ck_market_context_surprise_direction"),
        sa.CheckConstraint("surprise_magnitude IS NULL OR surprise_magnitude BETWEEN 0 AND 100", name="ck_market_context_surprise_magnitude"),
        sa.CheckConstraint("expected_by_market IS NULL OR expected_by_market BETWEEN 0 AND 100", name="ck_market_context_expected"),
        sa.CheckConstraint("already_priced_in IS NULL OR already_priced_in BETWEEN 0 AND 100", name="ck_market_context_priced_in"),
        sa.CheckConstraint("information_freshness IS NULL OR information_freshness BETWEEN 0 AND 100", name="ck_market_context_freshness"),
        sa.CheckConstraint("primary_source_probability IS NULL OR primary_source_probability BETWEEN 0 AND 100", name="ck_market_context_primary_source"),
        sa.CheckConstraint("actionable_novelty IS NULL OR actionable_novelty BETWEEN 0 AND 100", name="ck_market_context_actionable_novelty"),
        sa.CheckConstraint("event_specificity IS NULL OR event_specificity BETWEEN 0 AND 100", name="ck_market_context_event_specificity"),
        sa.CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 100", name="ck_market_context_confidence"),
    )
    op.create_index("ix_news_market_context_analysis_news_id", "news_market_context_analysis", ["news_id"])
    op.create_index("ix_market_context_analysis_status", "news_market_context_analysis", ["status"])


def downgrade() -> None:
    op.drop_index("ix_market_context_analysis_status", table_name="news_market_context_analysis")
    op.drop_index("ix_news_market_context_analysis_news_id", table_name="news_market_context_analysis")
    op.drop_table("news_market_context_analysis")
