"""drop simulation_team_result.ratings_through

Revision ID: d4b8e2f6a1c7
Revises: c3a9f1d7e5b2
Create Date: 2026-10-22 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4b8e2f6a1c7"
down_revision: Union[str, Sequence[str], None] = "c3a9f1d7e5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("simulation_team_result", "ratings_through")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("simulation_team_result", sa.Column("ratings_through", sa.DateTime(), nullable=True))
