"""add win_threshold_probs to nba_projections

Revision ID: 4b7d2e9c1a3f
Revises: 891a6785eedb
Create Date: 2026-10-10 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b7d2e9c1a3f"
down_revision: Union[str, Sequence[str], None] = "891a6785eedb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "nba_projections",
        sa.Column("win_threshold_probs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("nba_projections", "win_threshold_probs")
