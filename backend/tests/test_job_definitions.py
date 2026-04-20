"""Tests for background job definitions and scheduler service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nba_wins_pool.job_definitions import (
    SCHEDULED_JOBS,
    fetch_nba_projections_job,
    run_simulation_job,
)
from nba_wins_pool.services.nba_simulator.nba_simulator_service import run_and_save_simulation
from nba_wins_pool.services.scheduler_service import SchedulerService


@pytest.mark.asyncio
async def test_run_simulation_job():
    """Test simulation job delegates to run_and_save_simulation."""
    mock_db = MagicMock()

    async def mock_factory():
        yield mock_db

    with patch(
        "nba_wins_pool.services.nba_simulator.nba_simulator_service.run_and_save_simulation",
        new=AsyncMock(),
    ) as mock_run:
        await run_simulation_job(mock_factory)
        mock_run.assert_awaited_once_with(mock_db)


@pytest.mark.asyncio
async def test_run_and_save_simulation():
    """Test run_and_save_simulation wires repos to simulate_nba_season and save_simulation_results."""
    mock_db = MagicMock()
    mock_phase = MagicMock()
    mock_win_stats = MagicMock()
    mock_seeding = MagicMock()
    mock_raw_sim = MagicMock()

    mock_sim_repo = MagicMock()
    mock_team_repo = MagicMock()
    mock_projections_repo = MagicMock()

    with (
        patch("nba_wins_pool.services.nba_simulator.data._make_service") as mock_make_service,
        patch(
            "nba_wins_pool.services.nba_simulator.nba_simulator_service.SimulationResultsRepository",
            return_value=mock_sim_repo,
        ),
        patch("nba_wins_pool.services.nba_simulator.nba_simulator_service.TeamRepository", return_value=mock_team_repo),
        patch(
            "nba_wins_pool.services.nba_simulator.nba_simulator_service.NBAProjectionsRepository",
            return_value=mock_projections_repo,
        ),
        patch(
            "nba_wins_pool.services.nba_simulator.nba_simulator_service.simulate_nba_season",
            new=AsyncMock(return_value=(mock_phase, mock_win_stats, mock_seeding, None, None, mock_raw_sim)),
        ) as mock_sim,
        patch(
            "nba_wins_pool.services.nba_simulator.nba_simulator_service.save_simulation_results",
            new=AsyncMock(),
        ) as mock_save,
    ):
        mock_make_service.return_value.get_current_season.return_value = "2024-25"

        await run_and_save_simulation(mock_db)

        # Repos are passed through to simulate_nba_season for warm-start calibration
        _args, kwargs = mock_sim.call_args
        assert kwargs.get("sim_repo") is mock_sim_repo
        assert kwargs.get("team_repo") is mock_team_repo
        assert kwargs.get("projections_repo") is mock_projections_repo

        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_nba_projections_job():
    """Test NBA projections fetch job calls services correctly."""
    mock_db = MagicMock()

    async def mock_factory():
        yield mock_db

    with (
        patch("nba_wins_pool.job_definitions.NBAVegasProjectionsService") as MockVegasService,
        patch("nba_wins_pool.job_definitions.NBAEspnProjectionsService") as MockEspnService,
    ):
        mock_vegas_service = MockVegasService.return_value
        mock_vegas_service.write_projections = AsyncMock(return_value=10)

        mock_espn_service = MockEspnService.return_value
        mock_espn_service.write_projections = AsyncMock(return_value=5)

        await fetch_nba_projections_job(mock_factory)

        # Verify services were instantiated
        MockVegasService.assert_called_once()
        MockEspnService.assert_called_once()

        # Verify projections were written
        mock_vegas_service.write_projections.assert_called_once()
        mock_espn_service.write_projections.assert_called_once()


def test_scheduled_jobs_registry():
    """Test that all jobs are properly registered."""
    assert len(SCHEDULED_JOBS) == 2

    job_ids = {job.id for job in SCHEDULED_JOBS}
    assert job_ids == {
        "nba_projections_update",
        "nba_simulation_run",
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
