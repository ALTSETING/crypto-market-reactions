"""Add news_analysis table for ETH AI analysis results."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_add_news_analysis"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_analysis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("news_id", sa.Integer(), nullable=False),
        sa.Column("asset_focus", sa.String(length=20), nullable=False, server_default="ETH"),
        sa.Column("sentiment", sa.Integer(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=True),
        sa.Column("novelty", sa.Integer(), nullable=True),
        sa.Column("credibility", sa.Integer(), nullable=True),
        sa.Column("expected_direction", sa.String(length=20), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("impact_duration", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("asset_relevance", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False, server_default="eth_label_v1"),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("actual_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("raw_response_json", sa.Text(), nullable=True),
        sa.Column("batch_id", sa.String(length=100), nullable=True),
        sa.Column("batch_custom_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_news_analysis_news_id"), "news_analysis", ["news_id"], unique=False)
    op.create_index("ix_news_analysis_status", "news_analysis", ["status"], unique=False)
    op.create_index("ix_news_analysis_batch_id", "news_analysis", ["batch_id"], unique=False)
    op.create_unique_constraint(
        "uq_news_analysis_identity",
        "news_analysis",
        ["news_id", "asset_focus", "model_name", "prompt_version"],
    )
    op.create_foreign_key(
        "fk_news_analysis_news_id_news_articles",
        "news_analysis",
        "news_articles",
        ["news_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_news_analysis_news_id_news_articles", "news_analysis", type_="foreignkey")
    op.drop_constraint("uq_news_analysis_identity", "news_analysis", type_="unique")
    op.drop_index("ix_news_analysis_batch_id", table_name="news_analysis")
    op.drop_index("ix_news_analysis_status", table_name="news_analysis")
    op.drop_index(op.f("ix_news_analysis_news_id"), table_name="news_analysis")
    op.drop_table("news_analysis")
