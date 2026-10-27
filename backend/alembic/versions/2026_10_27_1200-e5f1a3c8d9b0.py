"""store every projection fetch as quotes per team and market, replacing nba_projections

Revision ID: e5f1a3c8d9b0
Revises: d4b8e2f6a1c7
Create Date: 2026-10-27 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f1a3c8d9b0"
down_revision: Union[str, Sequence[str], None] = "d4b8e2f6a1c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (market, line, prob, odds, opp_odds, condition) for each nba_projections column group
QUOTE_COLUMNS = [
    (
        "win_total",
        "np.reg_season_wins",
        "np.over_wins_prob",
        "np.over_wins_odds",
        "np.under_wins_odds",
        "np.reg_season_wins IS NOT NULL AND f.source <> 'espn_bpi'",
    ),
    (
        "espn_wins",
        "np.reg_season_wins",
        "NULL",
        "NULL",
        "NULL",
        "np.reg_season_wins IS NOT NULL AND f.source = 'espn_bpi'",
    ),
    ("espn_bpi", "np.bpi", "NULL", "NULL", "NULL", "np.bpi IS NOT NULL"),
    ("espn_playoff_bpi", "np.playoff_bpi", "NULL", "NULL", "NULL", "np.playoff_bpi IS NOT NULL"),
    (
        "make_playoffs",
        "NULL",
        "np.make_playoffs_prob",
        "np.make_playoffs_odds",
        "np.miss_playoffs_odds",
        "np.make_playoffs_prob IS NOT NULL OR np.make_playoffs_odds IS NOT NULL",
    ),
    (
        "reach_semis",
        "NULL",
        "np.reach_conf_semis_prob",
        "np.reach_conf_semis_odds",
        "NULL",
        "np.reach_conf_semis_prob IS NOT NULL",
    ),
    (
        "reach_conf_finals",
        "NULL",
        "np.reach_conf_finals_prob",
        "np.reach_conf_finals_odds",
        "NULL",
        "np.reach_conf_finals_prob IS NOT NULL",
    ),
    (
        "win_conf",
        "NULL",
        "np.win_conference_prob",
        "np.win_conference_odds",
        "NULL",
        "np.win_conference_prob IS NOT NULL",
    ),
    ("win_title", "NULL", "np.win_finals_prob", "np.win_finals_odds", "NULL", "np.win_finals_prob IS NOT NULL"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "projection_fetch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column("season", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("quote_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_projection_fetch_source_season_fetched_at", "projection_fetch", ["source", "season", "fetched_at"]
    )
    op.create_table(
        "market_quote",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fetch_id", sa.Uuid(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column("season", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("market", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("prob", sa.Float(), nullable=True),
        sa.Column("odds", sa.Integer(), nullable=True),
        sa.Column("opp_odds", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["fetch_id"], ["projection_fetch.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_market_quote_latest", "market_quote", ["source", "season", "team_id", "market", "fetched_at"])
    op.create_index("ix_market_quote_fetch_id", "market_quote", ["fetch_id"])

    op.execute(
        """
        INSERT INTO projection_fetch (id, source, season, fetched_at, quote_count)
        SELECT gen_random_uuid(), COALESCE(source, 'unknown'), season, fetched_at, 0
        FROM nba_projections
        GROUP BY COALESCE(source, 'unknown'), season, fetched_at
        """
    )
    from_fetch = """
        FROM nba_projections np
        JOIN projection_fetch f
          ON f.source = COALESCE(np.source, 'unknown') AND f.season = np.season AND f.fetched_at = np.fetched_at
    """
    for market, line, prob, odds, opp_odds, condition in QUOTE_COLUMNS:
        op.execute(
            f"""
            INSERT INTO market_quote (id, fetch_id, source, season, fetched_at, team_id, market, line, prob, odds, opp_odds)
            SELECT gen_random_uuid(), f.id, f.source, f.season, f.fetched_at, np.team_id, '{market}',
                   {line}, {prob}, {odds}, {opp_odds}
            {from_fetch}
            WHERE {condition}
            """
        )
    op.execute(
        f"""
        INSERT INTO market_quote (id, fetch_id, source, season, fetched_at, team_id, market, line, prob)
        SELECT gen_random_uuid(), f.id, f.source, f.season, f.fetched_at, np.team_id, 'wins_ladder',
               ladder.key::float, ladder.value::float
        {from_fetch}
        CROSS JOIN LATERAL jsonb_each_text(np.win_threshold_probs) ladder
        WHERE np.win_threshold_probs IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE projection_fetch f SET quote_count = counts.n
        FROM (SELECT fetch_id, count(*) AS n FROM market_quote GROUP BY fetch_id) counts
        WHERE counts.fetch_id = f.id
        """
    )
    op.execute("DELETE FROM projection_fetch WHERE quote_count = 0")

    op.drop_table("nba_projections")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "nba_projections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("season", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("projection_date", sa.Date(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("team_name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("reg_season_wins", sa.Float(), nullable=True),
        sa.Column("over_wins_prob", sa.Float(), nullable=True),
        sa.Column("make_playoffs_prob", sa.Float(), nullable=True),
        sa.Column("win_conference_prob", sa.Float(), nullable=True),
        sa.Column("win_finals_prob", sa.Float(), nullable=True),
        sa.Column("over_wins_odds", sa.Integer(), nullable=True),
        sa.Column("under_wins_odds", sa.Integer(), nullable=True),
        sa.Column("make_playoffs_odds", sa.Integer(), nullable=True),
        sa.Column("miss_playoffs_odds", sa.Integer(), nullable=True),
        sa.Column("win_conference_odds", sa.Integer(), nullable=True),
        sa.Column("win_finals_odds", sa.Integer(), nullable=True),
        sa.Column("bpi", sa.Float(), nullable=True),
        sa.Column("playoff_bpi", sa.Float(), nullable=True),
        sa.Column("reach_conf_semis_prob", sa.Float(), nullable=True),
        sa.Column("reach_conf_finals_prob", sa.Float(), nullable=True),
        sa.Column("reach_conf_semis_odds", sa.Integer(), nullable=True),
        sa.Column("reach_conf_finals_odds", sa.Integer(), nullable=True),
        sa.Column("win_threshold_probs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_nba_projections_fetched_at"), "nba_projections", ["fetched_at"])
    op.create_index(op.f("ix_nba_projections_projection_date"), "nba_projections", ["projection_date"])
    op.create_index(op.f("ix_nba_projections_season"), "nba_projections", ["season"])
    op.create_index(op.f("ix_nba_projections_source"), "nba_projections", ["source"])
    op.create_index(op.f("ix_nba_projections_team_id"), "nba_projections", ["team_id"])
    op.create_index(
        "ix_nba_projections_season_source_team_id_fetched_at",
        "nba_projections",
        ["season", "source", "team_id", "fetched_at"],
    )

    def pick(market: str, column: str) -> str:
        return f"max(q.{column}) FILTER (WHERE q.market = '{market}')"

    op.execute(
        f"""
        INSERT INTO nba_projections (
            id, season, projection_date, fetched_at, source, team_id, team_name,
            reg_season_wins, over_wins_prob, over_wins_odds, under_wins_odds, bpi, playoff_bpi,
            make_playoffs_prob, make_playoffs_odds, miss_playoffs_odds,
            reach_conf_semis_prob, reach_conf_semis_odds, reach_conf_finals_prob, reach_conf_finals_odds,
            win_conference_prob, win_conference_odds, win_finals_prob, win_finals_odds, win_threshold_probs
        )
        SELECT gen_random_uuid(), q.season, q.fetched_at::date, q.fetched_at, q.source, q.team_id, max(t.name),
               COALESCE({pick("win_total", "line")}, {pick("espn_wins", "line")}),
               {pick("win_total", "prob")}, {pick("win_total", "odds")}, {pick("win_total", "opp_odds")},
               {pick("espn_bpi", "line")}, {pick("espn_playoff_bpi", "line")},
               {pick("make_playoffs", "prob")}, {pick("make_playoffs", "odds")}, {pick("make_playoffs", "opp_odds")},
               {pick("reach_semis", "prob")}, {pick("reach_semis", "odds")},
               {pick("reach_conf_finals", "prob")}, {pick("reach_conf_finals", "odds")},
               {pick("win_conf", "prob")}, {pick("win_conf", "odds")},
               {pick("win_title", "prob")}, {pick("win_title", "odds")},
               jsonb_object_agg(q.line::int::text, q.prob) FILTER (WHERE q.market = 'wins_ladder')
        FROM market_quote q
        JOIN team t ON t.id = q.team_id
        GROUP BY q.fetch_id, q.season, q.fetched_at, q.source, q.team_id
        """
    )

    op.drop_index("ix_market_quote_fetch_id", table_name="market_quote")
    op.drop_index("ix_market_quote_latest", table_name="market_quote")
    op.drop_table("market_quote")
    op.drop_index("ix_projection_fetch_source_season_fetched_at", table_name="projection_fetch")
    op.drop_table("projection_fetch")
