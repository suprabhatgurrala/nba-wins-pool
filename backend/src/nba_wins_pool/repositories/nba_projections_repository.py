import uuid
from datetime import date
from typing import List, Optional

from fastapi import Depends
from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.nba_projections import NBAProjections, NBAProjectionsCreate


class NBAProjectionsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_projections(
        self,
        season: Optional[str] = None,
        projection_date: Optional[date] = None,
        team_id: Optional[uuid.UUID] = None,
        source: Optional[str] = None,
    ) -> List[NBAProjections]:
        """
        Get Vegas data for teams.

        Args:
            season: Optional season to filter by (e.g., '2023-24'). If not provided, gets the most recent season.
            projection_date: Optional date to filter by.
            team_id: Optional team ID to filter by.
            source: Optional source to filter by.

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

        # Filter by date if provided, otherwise get the most recent fetch for each (team, season, source)
        if projection_date:
            query = query.where(NBAProjections.projection_date == projection_date)
        else:
            subq = (
                select(
                    NBAProjections.team_id,
                    NBAProjections.season,
                    NBAProjections.source,
                    func.max(NBAProjections.fetched_at).label("latest_fetch"),
                )
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

    async def get_latest_projection_date(self, season: str) -> Optional[date]:
        """
        Get the latest projection date for a season.

        Args:
            season: The season to get the latest projection date for.

        Returns:
            The latest projection date, or None if no projections found.
        """
        statement = select(func.max(NBAProjections.projection_date)).where(NBAProjections.season == season)
        result = await self.session.execute(statement)
        return result.scalar()

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
            for field, value in vegas_data.dict(exclude_unset=True).items():
                if value is not None:
                    setattr(existing, field, value)
            self.session.add(existing)
            return False

        # Create new record
        new_data = NBAProjections(**vegas_data.dict())
        self.session.add(new_data)
        return True


async def get_nba_projections_repository(
    db: AsyncSession = Depends(get_db_session),
) -> NBAProjectionsRepository:
    return NBAProjectionsRepository(db)
