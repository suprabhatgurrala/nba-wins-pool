"""Central registry of all scheduled background jobs."""

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_espn_projections_service import NBAEspnProjectionsService
from nba_wins_pool.services.nba_vegas_projections_service import NBAVegasProjectionsService

logger = logging.getLogger(__name__)


@dataclass
class ScheduledJob:
    """Definition of a scheduled background job.

    Attributes:
        id: Unique identifier for the job
        name: Human-readable name
        function: Async function that executes the job (receives db_session_factory)
        trigger: APScheduler trigger (IntervalTrigger, CronTrigger, etc.)
        description: Description of what the job does
        enabled: Whether the job is enabled (default: True)
        max_instances: Maximum concurrent instances (default: 1)
        coalesce: Combine missed runs into one (default: True)
    """

    id: str
    name: str
    function: Callable[[Callable], Awaitable[None]]
    trigger: IntervalTrigger | CronTrigger
    description: str
    enabled: bool = True
    max_instances: int = 1
    coalesce: bool = True


# Job functions
async def fetch_nba_projections_job(db_session_factory):
    """Fetch NBA projections from FanDuel and ESPN."""
    async for db in db_session_factory():
        team_repo = TeamRepository(db)
        nba_projections_repo = NBAProjectionsRepository(db)

        # FanDuel (Vegas) service
        vegas_service = NBAVegasProjectionsService(
            db_session=db,
            team_repository=team_repo,
            nba_projections_repository=nba_projections_repo,
        )

        # ESPN service
        espn_service = NBAEspnProjectionsService(
            db_session=db,
            team_repository=team_repo,
            nba_projections_repository=nba_projections_repo,
        )

        # Fetch and write projections
        vegas_count = await vegas_service.write_projections()
        espn_count = await espn_service.write_projections()

        logger.info(f"FanDuel projections fetch completed. Successfully wrote {vegas_count} records.")
        logger.info(f"ESPN BPI projections fetch completed. Successfully wrote {espn_count} records.")

        break


async def run_simulation_job(db_session_factory):
    """Run the NBA season simulation and persist results to the database."""
    from nba_wins_pool.services.nba_simulator.nba_simulator_service import run_and_save_simulation

    async for db in db_session_factory():
        await run_and_save_simulation(db)
        break


# Static job registry
SCHEDULED_JOBS: list[ScheduledJob] = [
    ScheduledJob(
        id="nba_projections_update",
        name="Update NBA Projections",
        function=fetch_nba_projections_job,
        trigger=IntervalTrigger(hours=1),
        description="Fetches and stores NBA projections from FanDuel and ESPN every 1 hour",
    ),
    ScheduledJob(
        id="nba_simulation_run",
        name="Run NBA Season Simulation",
        function=run_simulation_job,
        trigger=IntervalTrigger(hours=3),
        description="Runs Monte Carlo simulation for the current NBA season phase and writes results to the database every 3 hours",
    ),
]
