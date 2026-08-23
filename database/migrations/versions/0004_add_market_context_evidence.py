"""Add explicit evidence state to Stage 11 market-context enrichment."""

from alembic import op
import sqlalchemy as sa

revision = "0004_add_market_context_evidence"
down_revision = "0003_add_market_context_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("news_market_context_analysis", sa.Column("expected_by_market_evidence", sa.String(20)))
    op.add_column("news_market_context_analysis", sa.Column("already_priced_in_evidence", sa.String(20)))
    op.add_column("news_market_context_analysis", sa.Column("primary_source_evidence", sa.String(20)))
    op.create_check_constraint(
        "ck_market_context_expected_evidence", "news_market_context_analysis",
        "expected_by_market_evidence IS NULL OR expected_by_market_evidence IN ('sufficient','insufficient')",
    )
    op.create_check_constraint(
        "ck_market_context_priced_in_evidence", "news_market_context_analysis",
        "already_priced_in_evidence IS NULL OR already_priced_in_evidence IN ('sufficient','insufficient')",
    )
    op.create_check_constraint(
        "ck_market_context_primary_evidence", "news_market_context_analysis",
        "primary_source_evidence IS NULL OR primary_source_evidence IN ('sufficient','insufficient')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_market_context_primary_evidence", "news_market_context_analysis", type_="check")
    op.drop_constraint("ck_market_context_priced_in_evidence", "news_market_context_analysis", type_="check")
    op.drop_constraint("ck_market_context_expected_evidence", "news_market_context_analysis", type_="check")
    op.drop_column("news_market_context_analysis", "primary_source_evidence")
    op.drop_column("news_market_context_analysis", "already_priced_in_evidence")
    op.drop_column("news_market_context_analysis", "expected_by_market_evidence")
