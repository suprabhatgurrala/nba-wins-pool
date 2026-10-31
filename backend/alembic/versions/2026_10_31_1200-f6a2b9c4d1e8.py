"""add discordguilddefault table

Revision ID: f6a2b9c4d1e8
Revises: e5f1a3c8d9b0
Create Date: 2026-10-31 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a2b9c4d1e8"
down_revision: Union[str, Sequence[str], None] = "e5f1a3c8d9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "discordguilddefault",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("pool_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pool_id"], ["pool.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_discordguilddefault_guild_id"), "discordguilddefault", ["guild_id"], unique=False)
    op.create_index(op.f("ix_discordguilddefault_pool_id"), "discordguilddefault", ["pool_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_discordguilddefault_pool_id"), table_name="discordguilddefault")
    op.drop_index(op.f("ix_discordguilddefault_guild_id"), table_name="discordguilddefault")
    op.drop_table("discordguilddefault")
