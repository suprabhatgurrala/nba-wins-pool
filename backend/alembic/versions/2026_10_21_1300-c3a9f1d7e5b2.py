"""move simulation run details into simulation_run and index projections lookups

Revision ID: c3a9f1d7e5b2
Revises: b7d2e4a1c9f3
Create Date: 2026-10-21 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a9f1d7e5b2"
down_revision: Union[str, Sequence[str], None] = "b7d2e4a1c9f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESULT_TABLES = ["simulation_team_result", "simulation_roster_result"]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "simulation_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("season", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("phase", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("n_sims", sa.Integer(), nullable=False),
        sa.Column("simulated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_simulation_run_season_simulated_at", "simulation_run", ["season", "simulated_at"], unique=False)

    op.execute(
        """
        INSERT INTO simulation_run (id, season, phase, n_sims, simulated_at)
        SELECT gen_random_uuid(), season, max(phase), max(n_sims), simulated_at
        FROM (
            SELECT season, phase, n_sims, simulated_at FROM simulation_team_result
            UNION ALL
            SELECT season, phase, n_sims, simulated_at FROM simulation_roster_result
        ) runs
        GROUP BY season, simulated_at
        """
    )

    for table in RESULT_TABLES:
        op.add_column(table, sa.Column("run_id", sa.Uuid(), nullable=True))
        op.execute(
            f"""
            UPDATE {table} r SET run_id = run.id
            FROM simulation_run run
            WHERE run.season = r.season AND run.simulated_at = r.simulated_at
            """
        )
        op.alter_column(table, "run_id", nullable=False)
        op.create_foreign_key(f"{table}_run_id_fkey", table, "simulation_run", ["run_id"], ["id"], ondelete="CASCADE")
        op.create_index(f"ix_{table}_run_id", table, ["run_id"], unique=False)
        op.drop_index(f"ix_{table}_season", table_name=table)
        op.drop_index(f"ix_{table}_simulated_at", table_name=table)
        for column in ["season", "phase", "n_sims", "simulated_at"]:
            op.drop_column(table, column)

    op.create_index(
        "ix_nba_projections_season_source_team_id_fetched_at",
        "nba_projections",
        ["season", "source", "team_id", "fetched_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_nba_projections_season_source_team_id_fetched_at", table_name="nba_projections")

    for table in RESULT_TABLES:
        op.add_column(table, sa.Column("season", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        op.add_column(table, sa.Column("phase", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True))
        op.add_column(table, sa.Column("n_sims", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("simulated_at", sa.DateTime(), nullable=True))
        op.execute(
            f"""
            UPDATE {table} r SET season = run.season, phase = run.phase, n_sims = run.n_sims,
                simulated_at = run.simulated_at
            FROM simulation_run run
            WHERE run.id = r.run_id
            """
        )
        for column in ["season", "phase", "n_sims", "simulated_at"]:
            op.alter_column(table, column, nullable=False)
        op.create_index(f"ix_{table}_season", table, ["season"], unique=False)
        op.create_index(f"ix_{table}_simulated_at", table, ["simulated_at"], unique=False)
        op.drop_index(f"ix_{table}_run_id", table_name=table)
        op.drop_constraint(f"{table}_run_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "run_id")

    op.drop_index("ix_simulation_run_season_simulated_at", table_name="simulation_run")
    op.drop_table("simulation_run")
