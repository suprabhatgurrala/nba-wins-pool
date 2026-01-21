"""Central registry of all scheduled background jobs."""

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_data_service import NbaDataService
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
        # Initialize repositories and services
        team_repo = TeamRepository(db)
        external_repo = ExternalDataRepository(db)
        nba_projections_repo = NBAProjectionsRepository(db)
        nba_data_service = NbaDataService(db, external_repo)

        # FanDuel (Vegas) service
        vegas_service = NBAVegasProjectionsService(
            db_session=db,
            nba_data_service=nba_data_service,
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


# Static job registry
SCHEDULED_JOBS: list[ScheduledJob] = [
    ScheduledJob(
        id="nba_projections_update",
        name="Update NBA Projections",
        function=fetch_nba_projections_job,
        trigger=IntervalTrigger(hours=1),
        description="Fetches and stores NBA projections from FanDuel and ESPN every 1 hour",
    ),
]
