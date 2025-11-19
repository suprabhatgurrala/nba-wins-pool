"""Tests for background job definitions and scheduler service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nba_wins_pool.job_definitions import (
    SCHEDULED_JOBS,
    update_fanduel_odds_job,
)
from nba_wins_pool.services.scheduler_service import SchedulerService


@pytest.mark.asyncio
async def test_update_fanduel_odds_job():
    """Test FanDuel odds update job calls service correctly."""
    mock_db = MagicMock()

    async def mock_factory():
        yield mock_db

    with patch("nba_wins_pool.job_definitions.get_auction_valuation_service") as mock_get_service:
        mock_service = MagicMock()
        mock_service.update_odds = AsyncMock()
        mock_get_service.return_value = mock_service

        await update_fanduel_odds_job(mock_factory)

        mock_get_service.assert_called_once_with(mock_db)
        mock_service.update_odds.assert_called_once()


def test_scheduled_jobs_registry():
    """Test that all jobs are properly registered."""
    assert len(SCHEDULED_JOBS) == 1

    job_ids = {job.id for job in SCHEDULED_JOBS}
    assert job_ids == {
        "fanduel_odds_update",
    }

    # All jobs should be enabled by default
    for job in SCHEDULED_JOBS:
        assert job.enabled is True
        assert job.max_instances == 1
        assert job.coalesce is True
        assert callable(job.function)


@pytest.mark.asyncio
async def test_scheduler_service_start():
    """Test that scheduler service registers all enabled jobs."""
    scheduler = SchedulerService()

    try:
        await scheduler.start()

        # Check that scheduler is running
        assert scheduler._is_running is True
        assert scheduler.scheduler.running is True

        # Check that all enabled jobs are registered
        jobs = scheduler.scheduler.get_jobs()
        enabled_jobs = [j for j in SCHEDULED_JOBS if j.enabled]
        assert len(jobs) == len(enabled_jobs)

        # Verify job IDs match
        job_ids = {job.id for job in jobs}
        expected_ids = {job.id for job in enabled_jobs}
        assert job_ids == expected_ids

    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_scheduler_service_shutdown():
    """Test that scheduler service shuts down gracefully."""
    scheduler = SchedulerService()

    await scheduler.start()
    assert scheduler._is_running is True

    await scheduler.shutdown()
    assert scheduler._is_running is False
    # Note: scheduler.running state may not update synchronously


@pytest.mark.asyncio
async def test_scheduler_service_double_start():
    """Test that starting scheduler twice doesn't cause issues."""
    scheduler = SchedulerService()

    try:
        await scheduler.start()
        await scheduler.start()  # Should log warning but not error

        assert scheduler._is_running is True

    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_scheduler_service_disabled_jobs():
    """Test that disabled jobs are not registered."""
    # Create a copy of the job and disable it
    from copy import deepcopy

    original_job = SCHEDULED_JOBS[0]
    disabled_job = deepcopy(original_job)
    disabled_job.enabled = False

    with patch("nba_wins_pool.services.scheduler_service.SCHEDULED_JOBS") as mock_jobs:
        mock_jobs.__iter__.return_value = [disabled_job]

        scheduler = SchedulerService()

        try:
            await scheduler.start()

            jobs = scheduler.scheduler.get_jobs()
            # No jobs should be registered since the only one is disabled
            assert len(jobs) == 0

        finally:
            await scheduler.shutdown()
