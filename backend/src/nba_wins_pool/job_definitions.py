"""Central registry of all scheduled background jobs."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Awaitable, Callable

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from nba_wins_pool.services.auction_valuation_service import (
    get_auction_valuation_service,
)
from nba_wins_pool.services.nba_data_service import get_nba_data_service
from nba_wins_pool.utils.season import get_current_season

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

async def update_scoreboard_job(db_session_factory):
    """Update NBA scoreboard data."""
    async for db in db_session_factory():
        service = get_nba_data_service(db)
        await service.update_scoreboard()
        break


async def update_schedule_job(db_session_factory):
    """Update NBA schedule data."""
    async for db in db_session_factory():
        service = get_nba_data_service(db)
        
        # Determine current season
        now = datetime.now(UTC)
        season = get_current_season(now.date())
        
        await service.update_schedule(season=season, scoreboard_date=now.date())
        break


async def cleanup_old_data_job(db_session_factory):
    """Cleanup old NBA scoreboard data."""
    async for db in db_session_factory():
        service = get_nba_data_service(db)
        await service.cleanup_old_scoreboards(keep_days=730)
        break


async def update_fanduel_odds_job(db_session_factory):
    """Update FanDuel odds data for auction valuations."""
    async for db in db_session_factory():
        service = get_auction_valuation_service(db)
        await service.update_odds()
        break


# Static job registry
SCHEDULED_JOBS: list[ScheduledJob] = [
    ScheduledJob(
        id="nba_scoreboard_update",
        name="Update NBA Scoreboard",
        function=update_scoreboard_job,
        trigger=IntervalTrigger(minutes=1),
        description="Fetches and caches NBA scoreboard data every 1 minute",
    ),
    ScheduledJob(
        id="nba_schedule_update",
        name="Update NBA Schedule",
        function=update_schedule_job,
        trigger=CronTrigger(hour=3, minute=0),
        description="Updates NBA schedule data daily at 3 AM UTC",
    ),
    ScheduledJob(
        id="nba_cleanup_old_data",
        name="Cleanup Old NBA Data",
        function=cleanup_old_data_job,
        trigger=CronTrigger(day_of_week="sun", hour=4, minute=0),
        description="Removes old scoreboard data weekly on Sundays at 4 AM UTC",
    ),
    ScheduledJob(
        id="fanduel_odds_update",
        name="Update FanDuel Odds",
        function=update_fanduel_odds_job,
        trigger=IntervalTrigger(hours=1),
        description="Fetches and caches FanDuel odds data every 1 hour",
    ),
]
