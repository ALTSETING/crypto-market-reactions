"""complete isolated Stage 13.5 early-reaction metrics"""
from alembic import op
import sqlalchemy as sa

revision = "0006_complete_stage135_metrics"
down_revision = "0005_add_market_intelligence"
branch_labels = None
depends_on = None

HORIZONS = (1, 2, 3, 5, 10, 15)
EXCURSIONS = (1, 3, 5, 10, 15)


def upgrade():
    for horizon in HORIZONS:
        op.add_column("news_early_reactions", sa.Column(f"btc_return_{horizon}m", sa.Numeric(16, 8)))
        op.add_column("news_early_reactions", sa.Column(f"eth_minus_btc_{horizon}m", sa.Numeric(16, 8)))
    for horizon in EXCURSIONS:
        if horizon != 5:
            op.add_column("news_early_reactions", sa.Column(f"max_favorable_{horizon}m", sa.Numeric(16, 8)))
            op.add_column("news_early_reactions", sa.Column(f"max_adverse_{horizon}m", sa.Numeric(16, 8)))
            op.add_column("news_early_reactions", sa.Column(f"max_absolute_{horizon}m", sa.Numeric(16, 8)))
            op.add_column("news_early_reactions", sa.Column(f"realized_vol_{horizon}m", sa.Numeric(16, 8)))
            op.add_column("news_early_reactions", sa.Column(f"volume_shock_{horizon}m", sa.Numeric(16, 8)))
        op.add_column("news_early_reactions", sa.Column(f"high_low_range_{horizon}m", sa.Numeric(16, 8)))
        op.add_column("news_early_reactions", sa.Column(f"time_to_max_move_{horizon}m", sa.Integer()))


def downgrade():
    for horizon in reversed(EXCURSIONS):
        op.drop_column("news_early_reactions", f"time_to_max_move_{horizon}m")
        op.drop_column("news_early_reactions", f"high_low_range_{horizon}m")
        if horizon != 5:
            for prefix in ("volume_shock", "realized_vol", "max_absolute", "max_adverse", "max_favorable"):
                op.drop_column("news_early_reactions", f"{prefix}_{horizon}m")
    for horizon in reversed(HORIZONS):
        op.drop_column("news_early_reactions", f"eth_minus_btc_{horizon}m")
        op.drop_column("news_early_reactions", f"btc_return_{horizon}m")
