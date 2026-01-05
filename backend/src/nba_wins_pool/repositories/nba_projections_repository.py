import uuid
from datetime import date
from typing import List, Optional

from fastapi import Depends
from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.nba_projections import NBAVegasData, NBAVegasDataCreate


class NBAVegasRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_vegas_data(
        self,
        season: Optional[str] = None,
        projection_date: Optional[date] = None,
        team_id: Optional[uuid.UUID] = None,
        source: Optional[str] = None,
    ) -> List[NBAVegasData]:
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
        query = select(NBAVegasData)

        # Filter by season if provided, otherwise get the most recent season
        if season:
            query = query.where(NBAVegasData.season == season)
        elif not any([projection_date, team_id, source]):
            # Only default to latest season if no other specific filters are provided
            subq = select(func.max(NBAVegasData.season)).scalar_subquery()
            query = query.where(NBAVegasData.season == subq)

        # Filter by date if provided
        if projection_date:
            query = query.where(NBAVegasData.date == projection_date)

        # Filter by team_id if provided
        if team_id:
            query = query.where(NBAVegasData.team_id == team_id)

        # Filter by source if provided
        if source:
            query = query.where(NBAVegasData.source == source)

        # If not requesting a specific date, source, or team, get the most recent fetch for each
        if not any([projection_date, team_id, source]):
            subq = (
                select(
                    NBAVegasData.team_id, NBAVegasData.season, func.max(NBAVegasData.fetched_at).label("latest_fetch")
                )
                .group_by(NBAVegasData.team_id, NBAVegasData.season)
                .subquery()
            )

            query = query.join(
                subq,
                and_(
                    NBAVegasData.team_id == subq.c.team_id,
                    NBAVegasData.season == subq.c.season,
                    NBAVegasData.fetched_at == subq.c.latest_fetch,
                ),
            )

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def upsert(self, vegas_data: NBAVegasDataCreate, update_if_exists: bool = False) -> bool:
        """
        Create or update a Vegas data record.

        Args:
            vegas_data: The data to upsert
            update_if_exists: If True, update existing record; otherwise skip

        Returns:
            bool: True if a new record was created, False if updated or skipped
        """
        # Check if record exists for this team/season/date/source
        existing = await self.get_vegas_data(
            season=vegas_data.season,
            projection_date=vegas_data.date,
            team_id=vegas_data.team_id,
            source=vegas_data.source,
        )

        if existing and not update_if_exists:
            return False

        if existing:
            # Update existing record
            existing = existing[0]  # get_vegas_data returns a list
            for field, value in vegas_data.dict(exclude_unset=True).items():
                setattr(existing, field, value)
            self.session.add(existing)
            return False

        # Create new record
        new_data = NBAVegasData(**vegas_data.dict())
        self.session.add(new_data)
        return True


async def get_nba_vegas_repository(
    db: AsyncSession = Depends(get_db_session),
) -> NBAVegasRepository:
    return NBAVegasRepository(db)
