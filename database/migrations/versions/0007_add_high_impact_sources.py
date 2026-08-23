"""add isolated Stage 16 high-impact source tables

Revision ID: 0007_add_high_impact_sources
Revises: 0006_complete_stage135_metrics
"""
from alembic import op
import high_impact_sources.models as m

revision="0007_add_high_impact_sources"
down_revision="0006_complete_stage135_metrics"
branch_labels=None
depends_on=None

def upgrade():
    for table in (m.high_impact_events,m.high_impact_event_assets,m.high_impact_event_analysis,m.high_impact_market_reactions):
        table.create(op.get_bind(),checkfirst=True)

def downgrade():
    for name in ("high_impact_market_reactions","high_impact_event_analysis","high_impact_event_assets","high_impact_events"):
        op.drop_table(name)
