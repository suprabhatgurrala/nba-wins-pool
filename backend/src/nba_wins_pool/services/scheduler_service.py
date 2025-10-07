"""Background job scheduler service.

This service manages the APScheduler lifecycle and registers jobs
from the central job registry. All job business logic lives in
their respective domain services.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.job_definitions import SCHEDULED_JOBS

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for managing background jobs.
    
    Reads job definitions from SCHEDULED_JOBS registry and manages their execution.
    All job business logic lives in domain services (e.g., NbaDataService).
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self._is_running = False

    async def start(self):
        """Start the scheduler and register all jobs from the registry."""
        if self._is_running:
            logger.warning("Scheduler is already running")
            return

        logger.info("Starting scheduler service")

        # Register all jobs from the static registry
        for job_def in SCHEDULED_JOBS:
            if not job_def.enabled:
                logger.info(f"Skipping disabled job: {job_def.name}")
                continue
            
            # Wrap the job function to inject db_session_factory
            async def job_wrapper(func=job_def.function):
                await func(get_db_session)
            
            self.scheduler.add_job(
                job_wrapper,
                job_def.trigger,
                id=job_def.id,
                name=job_def.name,
                max_instances=job_def.max_instances,
                coalesce=job_def.coalesce,
                replace_existing=True,
            )
            
            logger.info(
                f"Registered job: {job_def.name} (ID: {job_def.id}) - {job_def.description}"
            )

        # Start the scheduler
        self.scheduler.start()
        self._is_running = True

        logger.info(f"Scheduler started with {len([j for j in SCHEDULED_JOBS if j.enabled])} jobs")

    async def shutdown(self):
        """Gracefully shutdown the scheduler."""
        if not self._is_running:
            return

        logger.info("Shutting down scheduler service")
        self.scheduler.shutdown(wait=True)
        self._is_running = False
        logger.info("Scheduler service stopped")


# Global scheduler instance
_scheduler_instance: SchedulerService | None = None


def get_scheduler() -> SchedulerService:
    """Get the global scheduler instance.
    
    Returns:
        SchedulerService instance
    """
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = SchedulerService()
    return _scheduler_instance
