"""index foreign keys and common filters

Revision ID: b7d2e4a1c9f3
Revises: 5c1e8f2a9b47
Create Date: 2026-10-21 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2e4a1c9f3"
down_revision: Union[str, Sequence[str], None] = "5c1e8f2a9b47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ("ix_rosterslot_team_id", "rosterslot", ["team_id"]),
    ("ix_rosterslot_auction_lot_id", "rosterslot", ["auction_lot_id"]),
    ("ix_roster_pool_id_season", "roster", ["pool_id", "season"]),
    ("ix_auctionlot_team_id", "auctionlot", ["team_id"]),
    ("ix_auctionlot_winning_bid_id", "auctionlot", ["winning_bid_id"]),
    ("ix_auction_current_lot_id", "auction", ["current_lot_id"]),
    ("ix_auctioneventlog_auction_id_created_at", "auctioneventlog", ["auction_id", "created_at"]),
]


def upgrade() -> None:
    """Upgrade schema."""
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
