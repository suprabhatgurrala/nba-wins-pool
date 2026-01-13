import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.nba_projections import NBAProjections
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.auction_participant_repository import AuctionParticipantRepository
from nba_wins_pool.repositories.auction_repository import AuctionRepository
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.repositories.pool_season_repository import PoolSeasonRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.auction_valuation_service import AuctionValuationService


@pytest.fixture
def mock_db_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_external_data_repo():
    return MagicMock(spec=ExternalDataRepository)


@pytest.fixture
def mock_team_repo():
    return AsyncMock(spec=TeamRepository)


@pytest.fixture
def mock_auction_repo():
    return MagicMock(spec=AuctionRepository)


@pytest.fixture
def mock_auction_participant_repo():
    return MagicMock(spec=AuctionParticipantRepository)


@pytest.fixture
def mock_nba_projections_repo():
    return AsyncMock(spec=NBAProjectionsRepository)


@pytest.fixture
def mock_pool_season_repo():
    return AsyncMock(spec=PoolSeasonRepository)


@pytest.fixture
def service(
    mock_db_session,
    mock_external_data_repo,
    mock_team_repo,
    mock_auction_repo,
    mock_auction_participant_repo,
    mock_nba_projections_repo,
    mock_pool_season_repo,
):
    return AuctionValuationService(
        db_session=mock_db_session,
        external_data_repository=mock_external_data_repo,
        team_repository=mock_team_repo,
        auction_repository=mock_auction_repo,
        auction_participant_repository=mock_auction_participant_repo,
        nba_projections_repository=mock_nba_projections_repo,
        pool_season_repository=mock_pool_season_repo,
    )


@pytest.mark.asyncio
async def test_get_expected_wins_merging_and_calculation(service, mock_nba_projections_repo, mock_team_repo):
    # Arrange
    season = "2024-25"
    team1_id = uuid.uuid4()
    team2_id = uuid.uuid4()

    # FanDuel projections: Team 1 has everything, Team 2 missing make_playoffs_prob
    fd_projections = [
        NBAProjections(
            team_id=team1_id,
            team_name="Lakers",
            season=season,
            source="fanduel",
            projection_date=date(2024, 1, 1),
            reg_season_wins=45.5,
            make_playoffs_prob=0.8,
            win_conference_prob=0.1,
            fetched_at=datetime.now(),
        ),
        NBAProjections(
            team_id=team2_id,
            team_name="Celtics",
            season=season,
            source="fanduel",
            projection_date=date(2024, 1, 1),
            reg_season_wins=55.5,
            make_playoffs_prob=None,  # Missing
            win_conference_prob=0.3,
            fetched_at=datetime.now(),
        ),
    ]

    # ESPN projections: Provides make_playoffs_prob for Team 2
    espn_projections = [
        NBAProjections(
            team_id=team1_id,
            team_name="Lakers",
            season=season,
            source="espn",
            projection_date=date(2024, 1, 1),
            make_playoffs_prob=0.75,
            fetched_at=datetime.now(),
        ),
        NBAProjections(
            team_id=team2_id,
            team_name="Celtics",
            season=season,
            source="espn",
            projection_date=date(2024, 1, 1),
            make_playoffs_prob=0.95,
            fetched_at=datetime.now(),
        ),
    ]

    mock_nba_projections_repo.get_projections.side_effect = lambda season, source, projection_date=None: (
        fd_projections if source == "fanduel" else espn_projections
    )

    # Mock team repository to return some teams for merging
    mock_team_repo.get_all_by_league_slug.return_value = [
        Team(
            id=team1_id,
            league_slug=LeagueSlug.NBA,
            external_id="1",
            name="Lakers",
            abbreviation="LAL",
            logo_url="lakers_logo",
            conference="West",
        ),
        Team(
            id=team2_id,
            league_slug=LeagueSlug.NBA,
            external_id="2",
            name="Celtics",
            abbreviation="BOS",
            logo_url="celtics_logo",
            conference="East",
        ),
    ]

    # Act
    df, _, _ = await service.get_expected_wins(season)

    # Assert
    assert not df.empty
    assert len(df) == 2

    # Verify Team 1 (Lakers) - should keep FanDuel's 0.8
    lakers = df[df["team_id"] == team1_id].iloc[0]
    assert lakers["make_playoffs_prob"] == 0.8
    # Expected: 45.5 + (0.8 * 2.7828) + (0.1 * 19.7734)
    # = 45.5 + 2.22624 + 1.97734 = 49.70358
    assert pytest.approx(lakers["expected_wins"], rel=1e-5) == 49.70358

    # Verify Team 2 (Celtics) - should fill with ESPN's 0.95
    celtics = df[df["team_id"] == team2_id].iloc[0]
    assert celtics["make_playoffs_prob"] == 0.95
    # Expected: 55.5 + (0.95 * 2.7828) + (0.3 * 19.7734)
    # = 55.5 + 2.64366 + 5.93202 = 64.07568
    assert pytest.approx(celtics["expected_wins"], rel=1e-5) == 64.07568


@pytest.mark.asyncio
async def test_get_expected_wins_empty_fanduel(service, mock_nba_projections_repo, mock_team_repo):
    # Arrange
    mock_nba_projections_repo.get_projections.return_value = []
    mock_team_repo.get_all_by_league_slug.return_value = []

    # Act
    df, _, _ = await service.get_expected_wins("2024-25")

    # Assert
    assert df.empty
