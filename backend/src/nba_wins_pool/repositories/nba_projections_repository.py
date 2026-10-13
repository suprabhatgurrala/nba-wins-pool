import uuid
from datetime import date, datetime
from typing import Any, List, Optional

from fastapi import Depends
from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.nba_projections import NBAProjections, NBAProjectionsCreate
from nba_wins_pool.models.team import Team


class NBAProjectionsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_projections(
        self,
        season: Optional[str] = None,
        projection_date: Optional[date] = None,
        team_id: Optional[uuid.UUID] = None,
        source: Optional[str] = None,
        as_of: Optional[datetime] = None,
    ) -> List[NBAProjections]:
        """
        Get Vegas data for teams.

        Args:
            season: Optional season to filter by (e.g., '2023-24'). If not provided, gets the most recent season.
            projection_date: Optional date to filter by.
            team_id: Optional team ID to filter by.
            source: Optional source to filter by.
            as_of: Optional cutoff; when no projection_date is given, use the latest fetch at or before this time.

        Returns:
            List of NBAVegasData records matching the criteria
        """
        # Base query
        query = select(NBAProjections)

        # Filter by season if provided, otherwise get the most recent season
        if season:
            query = query.where(NBAProjections.season == season)
        elif not any([projection_date, team_id, source]):
            # Only default to latest season if no other specific filters are provided
            subq = select(func.max(NBAProjections.season)).scalar_subquery()
            query = query.where(NBAProjections.season == subq)

        # Filter by date if provided, otherwise get the most recent fetch (up to as_of) for each (team, season, source)
        if projection_date:
            query = query.where(NBAProjections.projection_date == projection_date)
        else:
            latest_filter = NBAProjections.reg_season_wins.is_not(None)
            if as_of:
                latest_filter = and_(latest_filter, NBAProjections.fetched_at <= as_of)
            subq = (
                select(
                    NBAProjections.team_id,
                    NBAProjections.season,
                    NBAProjections.source,
                    func.max(NBAProjections.fetched_at).label("latest_fetch"),
                )
                .where(latest_filter)
                .group_by(NBAProjections.team_id, NBAProjections.season, NBAProjections.source)
                .subquery()
            )

            query = query.join(
                subq,
                and_(
                    NBAProjections.team_id == subq.c.team_id,
                    NBAProjections.season == subq.c.season,
                    NBAProjections.source == subq.c.source,
                    NBAProjections.fetched_at == subq.c.latest_fetch,
                ),
            )

        # Filter by team_id if provided
        if team_id:
            query = query.where(NBAProjections.team_id == team_id)

        # Filter by source if provided
        if source:
            query = query.where(NBAProjections.source == source)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_latest_fetched_at(self, season: str) -> Optional[datetime]:
        """
        Get the time projections were most recently fetched for a season.

        Args:
            season: The season to get the latest fetch time for.

        Returns:
            The latest fetched_at timestamp, or None if no projections found.
        """
        statement = select(func.max(NBAProjections.fetched_at)).where(NBAProjections.season == season)
        result = await self.session.execute(statement)
        return result.scalar()

    async def get_latest_playoff_bpi(self, season: str | None = None) -> dict[str, float]:
        """Get the most recent ESPN playoff BPI (PBPI) for each team.

        Args:
            season: Only rows for this season, if given.

        Returns:
            Dict mapping team abbreviation (NBA tricode) -> playoff_bpi.
            Teams with no PBPI row are omitted.
        """
        latest = (
            select(
                NBAProjections.team_id,
                func.max(NBAProjections.fetched_at).label("latest_fetch"),
            )
            .where(NBAProjections.source == "espn_bpi")
            .where(NBAProjections.playoff_bpi.is_not(None))
        )
        if season:
            latest = latest.where(NBAProjections.season == season)
        latest_subq = latest.group_by(NBAProjections.team_id).subquery()

        stmt = (
            select(Team.abbreviation, NBAProjections.playoff_bpi)
            .join(NBAProjections, Team.id == NBAProjections.team_id)
            .join(
                latest_subq,
                and_(
                    NBAProjections.team_id == latest_subq.c.team_id,
                    NBAProjections.fetched_at == latest_subq.c.latest_fetch,
                ),
            )
        )

        result = await self.session.execute(stmt)
        return {row.abbreviation: float(row.playoff_bpi) for row in result}

    async def get_latest_futures_fetched_at(self) -> datetime | None:
        """Return the most recent fetched_at for fanduel futures."""
        stmt = select(func.max(NBAProjections.fetched_at)).where(NBAProjections.source == "fanduel")
        result = await self.session.execute(stmt)
        return result.scalar()

    async def get_latest_fanduel_futures(self, season: str | None = None) -> dict[str, dict[str, Any]]:
        """Get the most recent FanDuel playoff futures probabilities for each team.

        Args:
            season: Only rows for this season (e.g. ``"2026-27"``); all seasons when None.

        Returns:
            Dict mapping team abbreviation (NBA tricode) -> dict with keys:
            make_playoffs_prob, make_playoffs_odds, miss_playoffs_odds (American, raw),
            reach_conf_semis_prob, reach_conf_finals_prob, win_conference_prob,
            win_finals_prob, fetched_at.
            Teams with no FanDuel row are omitted.
        """
        latest_subq = select(
            NBAProjections.team_id,
            func.max(NBAProjections.fetched_at).label("latest_fetch"),
        ).where(NBAProjections.source == "fanduel")
        if season:
            latest_subq = latest_subq.where(NBAProjections.season == season)
        latest_subq = latest_subq.group_by(NBAProjections.team_id).subquery()

        stmt = (
            select(
                Team.abbreviation,
                NBAProjections.make_playoffs_prob,
                NBAProjections.make_playoffs_odds,
                NBAProjections.miss_playoffs_odds,
                NBAProjections.reach_conf_semis_prob,
                NBAProjections.reach_conf_finals_prob,
                NBAProjections.win_conference_prob,
                NBAProjections.win_finals_prob,
                NBAProjections.fetched_at,
            )
            .join(NBAProjections, Team.id == NBAProjections.team_id)
            .join(
                latest_subq,
                and_(
                    NBAProjections.team_id == latest_subq.c.team_id,
                    NBAProjections.fetched_at == latest_subq.c.latest_fetch,
                ),
            )
            .where(NBAProjections.source == "fanduel")
        )
        if season:
            stmt = stmt.where(NBAProjections.season == season)

        result = await self.session.execute(stmt)
        return {
            row.abbreviation: {
                "make_playoffs_prob": row.make_playoffs_prob,
                "make_playoffs_odds": row.make_playoffs_odds,
                "miss_playoffs_odds": row.miss_playoffs_odds,
                "reach_conf_semis_prob": row.reach_conf_semis_prob,
                "reach_conf_finals_prob": row.reach_conf_finals_prob,
                "win_conference_prob": row.win_conference_prob,
                "win_finals_prob": row.win_finals_prob,
                "fetched_at": row.fetched_at,
            }
            for row in result
        }

    async def get_latest_win_totals(self, season: str, source: str) -> dict[str, dict[str, Any]]:
        """Get each team's most recent regular-season win projection from one source for a season.

        Args:
            season: Season, e.g. ``"2025-26"``.
            source: ``"fanduel"`` (win total line + over probability) or ``"espn_bpi"``
                (projected wins; no over probability).

        Returns:
            Dict mapping team abbreviation (NBA tricode) -> dict with keys ``wins``
            (FanDuel's over/under line or ESPN's projected wins), ``over_prob``
            (vig-removed, None when absent), ``fetched_at`` and ``projection_date``.
            Teams with no projection this season are omitted. Callers should check
            the dates — a pulled market keeps its last row.
        """
        latest_subq = (
            select(
                NBAProjections.team_id,
                func.max(NBAProjections.fetched_at).label("latest_fetch"),
            )
            .where(NBAProjections.source == source)
            .where(NBAProjections.season == season)
            .where(NBAProjections.reg_season_wins.is_not(None))
            .group_by(NBAProjections.team_id)
            .subquery()
        )

        stmt = (
            select(
                Team.abbreviation,
                NBAProjections.reg_season_wins,
                NBAProjections.over_wins_prob,
                NBAProjections.fetched_at,
                NBAProjections.projection_date,
            )
            .join(NBAProjections, Team.id == NBAProjections.team_id)
            .join(
                latest_subq,
                and_(
                    NBAProjections.team_id == latest_subq.c.team_id,
                    NBAProjections.fetched_at == latest_subq.c.latest_fetch,
                ),
            )
            .where(NBAProjections.source == source)
            .where(NBAProjections.season == season)
        )

        result = await self.session.execute(stmt)
        return {
            row.abbreviation: {
                "wins": float(row.reg_season_wins),
                "over_prob": float(row.over_wins_prob) if row.over_wins_prob is not None else None,
                "fetched_at": row.fetched_at,
                "projection_date": row.projection_date,
            }
            for row in result
        }

    async def get_latest_win_threshold_probs(self, season: str) -> dict[str, dict[str, Any]]:
        """Get each team's most recent FanDuel "X+ Regular Season Wins" ladder for a season.

        FanDuel only lists the ladder early in the season, so the latest one may be weeks old.

        Returns:
            Dict mapping team abbreviation (NBA tricode) -> dict with keys ``probs``
            (threshold -> raw implied ``P(wins >= threshold)``) and ``fetched_at``.
            Teams that never had a ladder this season are omitted.
        """
        latest_subq = (
            select(
                NBAProjections.team_id,
                func.max(NBAProjections.fetched_at).label("latest_fetch"),
            )
            .where(NBAProjections.source == "fanduel")
            .where(NBAProjections.season == season)
            .where(NBAProjections.win_threshold_probs.is_not(None))
            .group_by(NBAProjections.team_id)
            .subquery()
        )

        stmt = (
            select(Team.abbreviation, NBAProjections.win_threshold_probs, NBAProjections.fetched_at)
            .join(NBAProjections, Team.id == NBAProjections.team_id)
            .join(
                latest_subq,
                and_(
                    NBAProjections.team_id == latest_subq.c.team_id,
                    NBAProjections.fetched_at == latest_subq.c.latest_fetch,
                ),
            )
            .where(NBAProjections.source == "fanduel")
            .where(NBAProjections.season == season)
        )

        result = await self.session.execute(stmt)
        return {
            row.abbreviation: {
                "probs": {int(k): float(v) for k, v in row.win_threshold_probs.items()},
                "fetched_at": row.fetched_at,
            }
            for row in result
        }

    async def upsert(self, vegas_data: NBAProjectionsCreate, update_if_exists: bool = False) -> bool:
        """
        Create or update a Vegas data record.

        Args:
            vegas_data: The data to upsert
            update_if_exists: If True, update existing record; otherwise skip

        Returns:
            bool: True if a new record was created, False if updated or skipped
        """
        # Check if record exists for this team/season/date/source
        existing = await self.get_projections(
            season=vegas_data.season,
            projection_date=vegas_data.projection_date,
            team_id=vegas_data.team_id,
            source=vegas_data.source,
        )

        if existing and not update_if_exists:
            return False

        if existing:
            # Update existing record
            existing = existing[0]  # get_vegas_data returns a list
            for field, value in vegas_data.model_dump(exclude_unset=True).items():
                if value is not None:
                    setattr(existing, field, value)
            self.session.add(existing)
            return False

        # Create new record
        new_data = NBAProjections(**vegas_data.model_dump())
        self.session.add(new_data)
        return True


async def get_nba_projections_repository(
    db: AsyncSession = Depends(get_db_session),
) -> NBAProjectionsRepository:
    return NBAProjectionsRepository(db)
