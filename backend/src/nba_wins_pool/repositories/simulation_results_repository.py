import uuid
from typing import List

from fastapi import Depends
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.simulation_results import SimulationRosterResult, SimulationTeamResult


class SimulationResultsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest_team_results(self, season: str) -> List[SimulationTeamResult]:
        """Return the most recent batch of SimulationTeamResult rows for a season.

        Finds the latest simulated_at timestamp for the given season, then
        returns all team rows from that batch. Returns an empty list when no
        simulation has been stored for the season yet.
        """
        max_ts_stmt = select(func.max(SimulationTeamResult.simulated_at)).where(SimulationTeamResult.season == season)
        max_ts = (await self.session.execute(max_ts_stmt)).scalar()
        if max_ts is None:
            return []
        stmt = select(SimulationTeamResult).where(
            SimulationTeamResult.season == season,
            SimulationTeamResult.simulated_at == max_ts,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def save_all_team_results(self, records: List[SimulationTeamResult]) -> None:
        """Bulk-insert a batch of SimulationTeamResult rows."""
        if not records:
            return
        self.session.add_all(records)
        await self.session.commit()

    async def get_latest_roster_results(self, season: str, pool_id: uuid.UUID) -> List[SimulationRosterResult]:
        """Return the most recent batch of SimulationRosterResult rows for a season and pool."""
        max_ts_stmt = (
            select(func.max(SimulationRosterResult.simulated_at))
            .where(SimulationRosterResult.season == season)
            .where(SimulationRosterResult.pool_id == pool_id)
        )
        max_ts = (await self.session.execute(max_ts_stmt)).scalar()
        if max_ts is None:
            return []
        stmt = select(SimulationRosterResult).where(
            SimulationRosterResult.season == season,
            SimulationRosterResult.pool_id == pool_id,
            SimulationRosterResult.simulated_at == max_ts,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def save_all_roster_results(self, records: List[SimulationRosterResult]) -> None:
        """Bulk-insert a batch of SimulationRosterResult rows."""
        if not records:
            return
        self.session.add_all(records)
        await self.session.commit()


def get_simulation_results_repository(
    db: AsyncSession = Depends(get_db_session),
) -> SimulationResultsRepository:
    return SimulationResultsRepository(db)
