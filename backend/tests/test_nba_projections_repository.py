import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.nba_projections import NBAProjections, NBAProjectionsCreate
from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repository(mock_session):
    return NBAProjectionsRepository(mock_session)


@pytest.mark.asyncio
async def test_upsert_partial_update_skips_none(repository, mock_session):
    # Arrange
    team_id = uuid.uuid4()
    season = "2024-25"
    projection_date = date(2024, 1, 1)
    source = "test_source"

    # Existing record in database
    existing_record = NBAProjections(
        id=uuid.uuid4(),
        season=season,
        projection_date=projection_date,
        team_id=team_id,
        team_name="Test Team",
        source=source,
        reg_season_wins=45.5,
        make_playoffs_prob=0.8,
        fetched_at=datetime.now(),
    )

    # Mock get_projections to return the existing record
    repository.get_projections = AsyncMock(return_value=[existing_record])

    # New data with some None values
    new_data = NBAProjectionsCreate(
        season=season,
        projection_date=projection_date,
        team_id=team_id,
        team_name="Test Team",
        source=source,
        reg_season_wins=None,  # This should be skipped
        make_playoffs_prob=0.9,  # This should be updated
        fetched_at=datetime.now(),
    )

    # Act
    result = await repository.upsert(new_data, update_if_exists=True)

    # Assert
    assert result is False  # Updated existing
    assert existing_record.reg_season_wins == 45.5  # Should NOT have changed
    assert existing_record.make_playoffs_prob == 0.9  # Should HAVE changed
    mock_session.add.assert_called_once_with(existing_record)


@pytest.mark.asyncio
async def test_upsert_creates_new_record_if_not_exists(repository, mock_session):
    # Arrange
    team_id = uuid.uuid4()
    season = "2024-25"
    projection_date = date(2024, 1, 1)
    source = "test_source"

    # Mock get_projections to return empty list
    repository.get_projections = AsyncMock(return_value=[])

    new_data = NBAProjectionsCreate(
        season=season,
        projection_date=projection_date,
        team_id=team_id,
        team_name="Test Team",
        source=source,
        reg_season_wins=45.5,
        fetched_at=datetime.now(),
    )

    # Act
    result = await repository.upsert(new_data, update_if_exists=True)

    # Assert
    assert result is True  # Created new
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert isinstance(added_obj, NBAProjections)
    assert added_obj.reg_season_wins == 45.5
