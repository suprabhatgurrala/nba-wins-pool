import uuid
from datetime import datetime
from typing import List

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.simulation_results import SimulationRosterResult, SimulationRun, SimulationTeamResult


class SimulationResultsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest_team_results(self, season: str) -> List[SimulationTeamResult]:
        """Return the team rows of the season's most recent run, or [] when none is stored yet."""
        latest_run = (
            select(SimulationRun.id)
            .where(SimulationRun.season == season)
            .order_by(SimulationRun.simulated_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = select(SimulationTeamResult).where(SimulationTeamResult.run_id == latest_run)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_latest_roster_results(
        self, season: str, pool_id: uuid.UUID
    ) -> tuple[List[SimulationRosterResult], datetime | None]:
        """Return the pool's roster rows from the season's most recent run that has any, and when it ran."""
        latest_run = (
            select(SimulationRun.id)
            .join(SimulationRosterResult, SimulationRosterResult.run_id == SimulationRun.id)
            .where(SimulationRun.season == season, SimulationRosterResult.pool_id == pool_id)
            .order_by(SimulationRun.simulated_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            select(SimulationRosterResult, SimulationRun.simulated_at)
            .join(SimulationRun, SimulationRun.id == SimulationRosterResult.run_id)
            .where(SimulationRosterResult.run_id == latest_run, SimulationRosterResult.pool_id == pool_id)
        )
        rows = (await self.session.execute(stmt)).all()
        if not rows:
            return [], None
        return [result for result, _ in rows], rows[0][1]

    async def save_run(
        self,
        run: SimulationRun,
        team_results: List[SimulationTeamResult],
        roster_results: List[SimulationRosterResult],
    ) -> None:
        """Save a run and all its results in one transaction."""
        self.session.add(run)
        await self.session.flush()
        for result in [*team_results, *roster_results]:
            result.run_id = run.id
        self.session.add_all([*team_results, *roster_results])
        await self.session.commit()


def get_simulation_results_repository(
    db: AsyncSession = Depends(get_db_session),
) -> SimulationResultsRepository:
    return SimulationResultsRepository(db)
