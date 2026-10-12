"""add fanduel_snapshot table for raw FanDuel futures responses

Revision ID: 9e4a7c2b5f1d
Revises: 6c1e8f3a9d2b
Create Date: 2026-10-12 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e4a7c2b5f1d"
down_revision: Union[str, Sequence[str], None] = "6c1e8f3a9d2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "fanduel_snapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("season", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("projection_date", sa.Date(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("populated_markets", sa.Integer(), nullable=False),
        sa.Column("futures_response", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fanduel_snapshot_season"), "fanduel_snapshot", ["season"], unique=False)
    op.create_index(op.f("ix_fanduel_snapshot_projection_date"), "fanduel_snapshot", ["projection_date"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_fanduel_snapshot_projection_date"), table_name="fanduel_snapshot")
    op.drop_index(op.f("ix_fanduel_snapshot_season"), table_name="fanduel_snapshot")
    op.drop_table("fanduel_snapshot")
