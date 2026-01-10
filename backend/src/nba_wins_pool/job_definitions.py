"""Central registry of all scheduled background jobs."""

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from nba_wins_pool.services.nba_espn_projections_service import (
    get_nba_espn_projections_service,
)
from nba_wins_pool.services.nba_vegas_projections_service import (
    get_nba_vegas_projections_service,
)

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
        service = get_nba_vegas_projections_service(db)
        await service.write_projections()
        service = get_nba_espn_projections_service(db)
        await service.write_projections()
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
