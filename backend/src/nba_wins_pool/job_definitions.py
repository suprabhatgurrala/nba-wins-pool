"""Central registry of all scheduled background jobs."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from nba_wins_pool.db.core import engine, get_db_session
from nba_wins_pool.services.nba_simulator.nba_simulator_service import run_projections_and_simulation
from nba_wins_pool.utils.child_process import run_in_child_process

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
async def _projections_and_simulation_with_own_engine() -> None:
    async for db in get_db_session():
        await run_projections_and_simulation(db)
        break
    await engine.dispose()


def projections_and_simulation_in_child() -> None:
    """Child-process entry point: fetch projections and simulate on the child's own event loop and database pool."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_projections_and_simulation_with_own_engine())


async def fetch_nba_projections_job(db_session_factory):
    """Fetch NBA projections from FanDuel and ESPN, then simulate the season, in a child process.

    The simulation takes ~12 s of CPU and ~1.8 GB, so it runs outside the API's event loop and the memory is
    returned when the child exits. ``db_session_factory`` is unused: the child opens its own sessions.
    """
    await run_in_child_process(projections_and_simulation_in_child)


# Static job registry
SCHEDULED_JOBS: list[ScheduledJob] = [
    ScheduledJob(
        id="nba_projections_update",
        name="Update NBA Projections",
        function=fetch_nba_projections_job,
        trigger=IntervalTrigger(hours=1),
        description=(
            "Fetches NBA projections from FanDuel and ESPN, then runs a calibrated Monte Carlo "
            "simulation once the season is past the All-Star break"
        ),
    ),
]
