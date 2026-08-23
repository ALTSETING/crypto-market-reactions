"""add Stage 16 semantic v2.1 analysis fields

Revision ID: 0008_high_impact_semantic_v21
Revises: 0007_add_high_impact_sources
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_high_impact_semantic_v21"
down_revision = "0007_add_high_impact_sources"
branch_labels = None
depends_on = None

SCORES = (
    "surprise_level", "actionability", "institutional_relevance", "retail_relevance",
    "regulatory_strength", "economic_significance", "technical_significance",
    "security_significance", "adoption_significance", "execution_certainty", "urgency",
    "fundamental_relevance",
)


def upgrade():
    for name in SCORES:
        op.add_column("high_impact_event_analysis", sa.Column(name, sa.Integer(), nullable=True))
    for name in ("surprise_evidence", "first_disclosure", "market_scope",
                 "temporary_vs_structural", "evidence_quality"):
        op.add_column("high_impact_event_analysis", sa.Column(name, sa.String(50), nullable=True))
    op.add_column("high_impact_event_analysis", sa.Column("batch_id", sa.String(100), nullable=True))
    op.add_column("high_impact_event_analysis", sa.Column("batch_custom_id", sa.String(150), nullable=True))
    op.create_index("ix_high_impact_analysis_batch_id", "high_impact_event_analysis", ["batch_id"])
    op.create_index("uq_high_impact_analysis_batch_custom_id", "high_impact_event_analysis",
                    ["batch_custom_id"], unique=True, postgresql_where=sa.text("batch_custom_id IS NOT NULL"))


def downgrade():
    op.drop_index("uq_high_impact_analysis_batch_custom_id", table_name="high_impact_event_analysis")
    op.drop_index("ix_high_impact_analysis_batch_id", table_name="high_impact_event_analysis")
    for name in ("batch_custom_id", "batch_id", "evidence_quality", "temporary_vs_structural",
                 "market_scope", "first_disclosure", "surprise_evidence"):
        op.drop_column("high_impact_event_analysis", name)
    for name in reversed(SCORES):
        op.drop_column("high_impact_event_analysis", name)
