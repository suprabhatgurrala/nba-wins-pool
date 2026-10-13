"""store auction projection date as a timestamp

Revision ID: 5c1e8f2a9b47
Revises: 070a76ce05cb
Create Date: 2026-10-12 23:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c1e8f2a9b47"
down_revision: Union[str, Sequence[str], None] = "070a76ce05cb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "poolseason",
        "auction_projection_date",
        type_=sa.DateTime(),
        existing_type=sa.Date(),
        existing_nullable=True,
        postgresql_using="auction_projection_date::timestamp",
    )
    # Backfill each stored date with the latest fetch on that day, falling back to the end of the day
    op.execute(
        """
        UPDATE poolseason
        SET auction_projection_date = COALESCE(
            (
                SELECT max(np.fetched_at)
                FROM nba_projections np
                WHERE np.season = poolseason.season
                  AND np.projection_date = poolseason.auction_projection_date::date
            ),
            poolseason.auction_projection_date + interval '1 day' - interval '1 microsecond'
        )
        WHERE auction_projection_date IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "poolseason",
        "auction_projection_date",
        type_=sa.Date(),
        existing_type=sa.DateTime(),
        existing_nullable=True,
        postgresql_using="auction_projection_date::date",
    )
