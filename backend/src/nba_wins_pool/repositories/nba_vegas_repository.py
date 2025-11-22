from datetime import datetime
from typing import List, Optional

from fastapi import Depends
from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.nba_vegas_data import NBAVegasData, NBAVegasDataCreate


class NBAVegasRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_vegas_data(
        self, season: Optional[str] = None, fetched_at: Optional[datetime] = None
    ) -> List[NBAVegasData]:
        """
        Get Vegas data for all teams.

        Args:
            season: Optional season to filter by (e.g., '2023-24'). If not provided, gets the most recent season.
            fetched_at: Optional timestamp to get data as of a specific time. If not provided, gets the latest data.

        Returns:
            List of NBAVegasData records matching the criteria
        """
        # Base query for all teams
        query = select(NBAVegasData)

        # Filter by season if provided, otherwise get the most recent season
        if season:
            query = query.where(NBAVegasData.season == season)
        else:
            # Subquery to get the most recent season
            subq = select(func.max(NBAVegasData.season)).scalar_subquery()
            query = query.where(NBAVegasData.season == subq)

        # Filter by specific timestamp if provided, otherwise get the latest data
        if fetched_at:
            query = query.where(func.date_trunc("second", NBAVegasData.fetched_at) == fetched_at)
        else:
            # For each team/season, get the most recent record
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
        # Check if record exists for this team/season
        existing = [
            record
            for record in await self.get_vegas_data(season=vegas_data.season, fetched_at=vegas_data.fetched_at)
            if record.team_id == vegas_data.team_id
            and record.season == vegas_data.season
            and record.fetched_at == vegas_data.fetched_at
        ]

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
