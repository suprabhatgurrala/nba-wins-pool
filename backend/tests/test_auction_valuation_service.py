import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.auction_valuation import AuctionValuationData, TeamValuation
from nba_wins_pool.models.projection import ProjectionMarket
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.auction_participant_repository import AuctionParticipantRepository
from nba_wins_pool.repositories.auction_repository import AuctionRepository
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.pool_season_repository import PoolSeasonRepository
from nba_wins_pool.repositories.projection_repository import LatestQuote, ProjectionRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.auction_valuation_service import (
    POSTSEASON_WIN_COEFFICIENTS,
    AuctionValuationService,
    postseason_win_coefficients,
)
from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.types.nba_game_status import NBAGameStatus


def _expected_wins(season: str, reg_season_wins: float, make_playoffs_prob: float, win_conference_prob: float) -> float:
    c = postseason_win_coefficients(season)
    return (
        reg_season_wins
        + make_playoffs_prob * c.playoff_odds
        + win_conference_prob * c.conf_odds
        + make_playoffs_prob * (1 - make_playoffs_prob) * c.play_in_odds
    )


def test_postseason_win_coefficients_by_season():
    fits = POSTSEASON_WIN_COEFFICIENTS
    first, newest = fits[min(fits)], fits[max(fits)]
    for season, coefficients in fits.items():
        assert postseason_win_coefficients(season) == coefficients
    assert postseason_win_coefficients("2000-01") == first
    assert postseason_win_coefficients("2024-25") == fits["2022-23"]
    assert postseason_win_coefficients("2099-00") == newest
    assert postseason_win_coefficients(None) == newest


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
def mock_projection_repo():
    return AsyncMock(spec=ProjectionRepository)


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
    mock_projection_repo,
    mock_pool_season_repo,
):
    return AuctionValuationService(
        db_session=mock_db_session,
        external_data_repository=mock_external_data_repo,
        team_repository=mock_team_repo,
        auction_repository=mock_auction_repo,
        auction_participant_repository=mock_auction_participant_repo,
        projection_repository=mock_projection_repo,
        pool_season_repository=mock_pool_season_repo,
    )


def _quote(team_id, tricode, market, *, line=None, prob=None, fetched_at=None) -> LatestQuote:
    return LatestQuote(
        tricode=tricode,
        team_id=team_id,
        market=market,
        line=line,
        prob=prob,
        odds=None,
        opp_odds=None,
        fetched_at=fetched_at or datetime.now(),
    )


@pytest.mark.asyncio
async def test_get_expected_wins_merging_and_calculation(service, mock_projection_repo, mock_team_repo):
    season = "2024-25"
    team1_id = uuid.uuid4()
    team2_id = uuid.uuid4()

    # FanDuel: Lakers have everything, Celtics have no make-playoffs quote
    fd_quotes = [
        _quote(team1_id, "LAL", ProjectionMarket.WIN_TOTAL, line=45.5),
        _quote(team1_id, "LAL", ProjectionMarket.MAKE_PLAYOFFS, prob=0.8),
        _quote(team1_id, "LAL", ProjectionMarket.WIN_CONF, prob=0.1),
        _quote(team2_id, "BOS", ProjectionMarket.WIN_TOTAL, line=55.5),
        _quote(team2_id, "BOS", ProjectionMarket.WIN_CONF, prob=0.3),
    ]
    espn_quotes = [
        _quote(team1_id, "LAL", ProjectionMarket.MAKE_PLAYOFFS, prob=0.75),
        _quote(team2_id, "BOS", ProjectionMarket.MAKE_PLAYOFFS, prob=0.95),
    ]
    mock_projection_repo.get_latest_quotes.side_effect = lambda season, source, markets, as_of=None: (
        fd_quotes if source == "fanduel" else espn_quotes if source == "espn_bpi" else []
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
    assert pytest.approx(lakers["expected_wins"], rel=1e-5) == _expected_wins(season, 45.5, 0.8, 0.1)

    # Verify Team 2 (Celtics) - should fill with ESPN's 0.95
    celtics = df[df["team_id"] == team2_id].iloc[0]
    assert celtics["make_playoffs_prob"] == 0.95
    assert pytest.approx(celtics["expected_wins"], rel=1e-5) == _expected_wins(season, 55.5, 0.95, 0.3)


@pytest.mark.asyncio
async def test_get_expected_wins_blends_an_aged_line_and_falls_back_to_draftkings(
    service, mock_projection_repo, mock_team_repo
):
    as_of = datetime(2024, 3, 10, 12)
    team_id = uuid.uuid4()
    dk_quotes = [
        _quote(team_id, "LAL", ProjectionMarket.WIN_TOTAL, line=40.0, fetched_at=as_of - timedelta(days=3)),
        _quote(team_id, "LAL", ProjectionMarket.MAKE_PLAYOFFS, prob=0.5, fetched_at=as_of),
    ]
    espn_quotes = [_quote(team_id, "LAL", ProjectionMarket.ESPN_WINS, line=44.0, fetched_at=as_of)]
    mock_projection_repo.get_latest_quotes.side_effect = lambda season, source, markets, as_of=None: {
        "draftkings": dk_quotes,
        "espn_bpi": espn_quotes,
    }.get(source, [])
    mock_team_repo.get_all_by_league_slug.return_value = []

    df, fetched_at, source = await service.get_expected_wins("2023-24", as_of=as_of)

    assert source == "draftkings"
    assert fetched_at == as_of
    lakers = df.iloc[0]
    assert lakers["reg_season_wins"] == pytest.approx(42.0)
    assert lakers["expected_wins"] == pytest.approx(_expected_wins("2023-24", 42.0, 0.5, 0.0))
    assert all(call.args[3] == as_of for call in mock_projection_repo.get_latest_quotes.call_args_list)


@pytest.mark.asyncio
async def test_get_expected_wins_empty_fanduel(service, mock_projection_repo, mock_team_repo):
    # Arrange
    mock_projection_repo.get_latest_quotes.return_value = []
    mock_team_repo.get_all_by_league_slug.return_value = []

    # Act
    df, _, _ = await service.get_expected_wins("2024-25")

    # Assert
    assert df.empty


def _stub_expected_wins(service, expected_wins):
    import pandas as pd

    df = pd.DataFrame(
        {
            "team_name": [f"Team {i}" for i in range(len(expected_wins))],
            "expected_wins": expected_wins,
        }
    )
    service.get_expected_wins = AsyncMock(return_value=(df, datetime(2024, 1, 1, 12), "fanduel"))


@pytest.mark.asyncio
async def test_get_valuation_data_floors_at_min_bid_increment(service):
    # 1 participant x 2 teams => replacement level is the 2nd best team (50 wins)
    _stub_expected_wins(service, [60.0, 50.0, 49.0, 40.0])

    result = await service.get_valuation_data(
        season="2024-25",
        num_participants=1,
        budget_per_participant=100,
        teams_per_participant=2,
        min_bid_increment=5.0,
    )

    values = [t.auction_value for t in result.data]
    # Best team takes the whole budget; replacement level and below are floored at the increment
    assert values == [100.0, 5.0, 5.0, 5.0]


@pytest.mark.asyncio
async def test_get_valuation_data_defaults_to_one_dollar_floor(service):
    _stub_expected_wins(service, [60.0, 50.0, 40.0])

    result = await service.get_valuation_data(
        season="2024-25",
        num_participants=1,
        budget_per_participant=100,
        teams_per_participant=2,
    )

    assert [t.auction_value for t in result.data] == [100.0, 1.0, 1.0]


def _valuation(*team_ids: uuid.UUID) -> AuctionValuationData:
    return AuctionValuationData(
        data=[TeamValuation(team_name=f"Team {i}", team_id=team_id) for i, team_id in enumerate(team_ids)],
        num_participants=2,
        budget_per_participant=200,
        teams_per_participant=5,
        projection_fetched_at=datetime(2026, 1, 1),
        source="fanduel",
    )


def _game(day: int, status: NBAGameStatus, winner: int | None, loser: int | None) -> dict:
    return {
        "date_time": pd.Timestamp(f"2026-01-{day:02d} 19:00", tz="US/Eastern"),
        "status": status,
        "winning_team": winner,
        "losing_team": loser,
    }


def _record_service(mock_team_repo, games: pd.DataFrame, *teams: Team) -> AuctionValuationService:
    nba_data_service = MagicMock(spec=NbaDataService)
    nba_data_service.get_game_data = AsyncMock(return_value=games)
    mock_team_repo.get_all_by_league_slug.return_value = list(teams)
    return AuctionValuationService(
        db_session=AsyncMock(spec=AsyncSession),
        external_data_repository=MagicMock(spec=ExternalDataRepository),
        team_repository=mock_team_repo,
        auction_repository=MagicMock(spec=AuctionRepository),
        auction_participant_repository=MagicMock(spec=AuctionParticipantRepository),
        projection_repository=AsyncMock(spec=ProjectionRepository),
        pool_season_repository=AsyncMock(spec=PoolSeasonRepository),
        nba_data_service=nba_data_service,
    )


def _team(external_id: int) -> Team:
    return Team(
        league_slug=LeagueSlug.NBA,
        external_id=str(external_id),
        name=f"Team {external_id}",
        abbreviation=f"T{external_id}",
        logo_url="",
        conference="East",
        division=None,
    )


@pytest.mark.asyncio
async def test_add_records_counts_completed_games_up_to_as_of(mock_team_repo):
    """Only final games on or before as_of count; a team with no games gets 0-0."""
    a, b, c = _team(1), _team(2), _team(3)
    games = pd.DataFrame(
        [
            _game(1, NBAGameStatus.FINAL, 1, 2),
            _game(2, NBAGameStatus.FINAL, 1, 2),
            _game(3, NBAGameStatus.FINAL, 2, 1),
            _game(4, NBAGameStatus.INGAME, None, None),
            _game(9, NBAGameStatus.FINAL, 2, 1),
        ]
    )
    service = _record_service(mock_team_repo, games, a, b, c)
    valuation = _valuation(a.id, b.id, c.id)

    await service._add_records(valuation, "2025-26", datetime(2026, 1, 5))

    assert [(t.wins, t.losses) for t in valuation.data] == [(2, 1), (1, 2), (0, 0)]


@pytest.mark.asyncio
async def test_add_records_leaves_records_empty_before_any_game(mock_team_repo):
    """Before any game is final the records stay unset, so the frontend hides the column."""
    a = _team(1)
    games = pd.DataFrame([_game(9, NBAGameStatus.FINAL, 1, 2)])
    service = _record_service(mock_team_repo, games, a)
    valuation = _valuation(a.id)

    await service._add_records(valuation, "2025-26", datetime(2026, 1, 5))

    assert (valuation.data[0].wins, valuation.data[0].losses) == (None, None)
