"""add preseason_rating_sd, playoff_adjustment, ratings_through to simulation_team_result

Revision ID: 6c1e8f3a9d2b
Revises: 4b7d2e9c1a3f
Create Date: 2026-10-12 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c1e8f3a9d2b"
down_revision: Union[str, Sequence[str], None] = "4b7d2e9c1a3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("simulation_team_result", sa.Column("preseason_rating_sd", sa.Float(), nullable=True))
    op.add_column("simulation_team_result", sa.Column("playoff_adjustment", sa.Float(), nullable=True))
    op.add_column("simulation_team_result", sa.Column("ratings_through", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("simulation_team_result", "ratings_through")
    op.drop_column("simulation_team_result", "playoff_adjustment")
    op.drop_column("simulation_team_result", "preseason_rating_sd")
