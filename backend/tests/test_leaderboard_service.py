from datetime import date
from uuid import uuid4

import pandas as pd
import pytest

from nba_wins_pool.services.leaderboard_service import LeaderboardService
from nba_wins_pool.services.nba_data_service import NBAGameStatus
from nba_wins_pool.services.pool_season_service import TeamRosterMappings
from nba_wins_pool.types.season_str import SeasonStr

UNDRAFTED = "Undrafted"


class FakeSimulationResultsRepository:
    async def get_latest_roster_results(self, season, pool_id):
        return []

    async def get_latest_team_results(self, season):
        return []


class FakeNbaDataService:
    def __init__(self, scoreboard_data, schedule_data, scoreboard_date):
        self._scoreboard_data = scoreboard_data
        self._schedule_data = schedule_data
        self._scoreboard_date = scoreboard_date
        self._current_season = "2024-25"

    async def get_scoreboard_cached(self):
        return self._scoreboard_data, self._scoreboard_date

    async def get_gamecardfeed_cached(self):
        return self._scoreboard_data, self._scoreboard_date

    async def get_schedule_cached(self, scoreboard_date, season):
        # In the test, we want to return the schedule data regardless of the date
        # since we're testing the leaderboard logic, not the caching
        return self._schedule_data, self._current_season

    async def get_current_season(self):
        return self._current_season

    async def get_game_data(self, season):
        # Combine schedule and scoreboard data
        combined_data = self._schedule_data + self._scoreboard_data
        game_df = pd.DataFrame(combined_data)

        if len(game_df) == 0:
            return game_df

        # Convert date_time to datetime if it's a string
        if not pd.api.types.is_datetime64_any_dtype(game_df["date_time"]):
            game_df["date_time"] = pd.to_datetime(game_df["date_time"], utc=True).dt.tz_convert("US/Eastern")

        # Add winning_team and losing_team columns
        game_df["winning_team"] = game_df["home_team"].where(
            (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score > game_df.away_score),
            other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
        )
        game_df["losing_team"] = game_df["home_team"].where(
            (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score < game_df.away_score),
            other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
        )
        return game_df


@pytest.mark.asyncio
async def test_leaderboard_generates_roster_and_team_rows(monkeypatch):
    pool_id = uuid4()
    season = SeasonStr("2024-25")

    # Use a fixed date that matches our test data
    scoreboard_date = date(2024, 10, 16)
    # Patch date.today() to return our fixed date
    monkeypatch.setattr("datetime.date", lambda *args, **kw: scoreboard_date)

    scoreboard_data = [
        {
            "date_time": "2024-10-16T00:00:00Z",
            "home_team": 100,
            "home_score": 108,
            "home_team_tricode": "TMA",
            "away_team": 200,
            "away_score": 101,
            "away_team_tricode": "TMB",
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
            "gameId": "1234",
        }
    ]
    schedule_data = [
        {
            "date_time": "2024-10-15T00:00:00Z",
            "home_team": 200,
            "home_score": 90,
            "home_team_tricode": "TMB",
            "away_team": 100,
            "away_score": 95,
            "away_team_tricode": "TMA",
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
            "gameId": "1233",
        }
    ]

    fake_nba_service = FakeNbaDataService(scoreboard_data, schedule_data, scoreboard_date)

    class FakePoolSeasonService:
        async def get_team_roster_mappings(self, **_: object):
            teams_data = [
                {
                    "team_external_id": 100,
                    "roster_name": "Roster A",
                    "auction_price": 25.0,
                    "logo_url": "logo-a",
                    "team_name": "Team A",
                    "abbreviation": "TMA",
                },
                {
                    "team_external_id": 200,
                    "roster_name": "Roster B",
                    "auction_price": 30.0,
                    "logo_url": "logo-b",
                    "team_name": "Team B",
                    "abbreviation": "TMB",
                },
            ]
            teams_df = pd.DataFrame(teams_data).set_index("team_external_id")
            return TeamRosterMappings(teams_df=teams_df, roster_names=["Roster A", "Roster B"])

    fake_pool_season_service = FakePoolSeasonService()

    class FakeAuctionValuationService:
        async def get_expected_wins(self, season=None, projection_date=None):
            df = pd.DataFrame({"expected_wins": [45, 35], "abbreviation": ["TMA", "TMB"]})
            return df, date.today(), "test_source"

    fake_auction_valuation_service = FakeAuctionValuationService()

    service = LeaderboardService(
        db_session=None,
        pool_repository=None,
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=fake_pool_season_service,
        auction_valuation_service=fake_auction_valuation_service,
        simulation_results_repository=FakeSimulationResultsRepository(),
    )

    result = await service.get_leaderboard(pool_id, season)

    assert result["roster"], "Expected roster rows"
    assert result["team"], "Expected team rows"

    roster_names = {row["name"] for row in result["roster"]}
    assert roster_names == {"Roster A", "Roster B"}

    team_names = {row["team"] for row in result["team"]}
    assert team_names == {"Team A", "Team B"}

    for row in result["team"]:
        assert row["logo_url"] in {"logo-a", "logo-b"}
        assert row["auction_price"] in {25.0, 30.0}


@pytest.mark.asyncio
async def test_leaderboard_returns_empty_when_no_games(monkeypatch):
    pool_id = uuid4()
    season = SeasonStr("2024-25")

    # Use a fixed date that matches our test data
    scoreboard_date = date(2024, 10, 16)
    # Patch date.today() to return our fixed date
    monkeypatch.setattr("datetime.date", lambda *args, **kw: scoreboard_date)

    # For the empty games test, we need to ensure we don't try to access scoreboard_date
    # when there are no games. The service should handle this case gracefully.
    class EmptyNbaDataService:
        async def get_gamecardfeed_cached(self):
            return [], date.today()

        async def get_schedule_cached(self, scoreboard_date, season):
            return [], season

        async def get_current_season(self):
            return "2024-25"

        async def get_game_data(self, season):
            return pd.DataFrame()

    fake_nba_service = EmptyNbaDataService()

    class FakePoolSeasonService:
        async def get_team_roster_mappings(self, **_: object):
            teams_df = pd.DataFrame(columns=["roster_name", "auction_price", "logo_url", "team_name", "abbreviation"])
            teams_df.index.name = "team_external_id"
            return TeamRosterMappings(teams_df=teams_df, roster_names=[])

    fake_pool_season_service = FakePoolSeasonService()

    class FakeAuctionValuationService:
        async def get_expected_wins(self, season=None, projection_date=None):
            df = pd.DataFrame(columns=["expected_wins", "abbreviation"])
            return df, date.today(), "test_source"

    fake_auction_valuation_service = FakeAuctionValuationService()

    service = LeaderboardService(
        db_session=None,
        pool_repository=None,
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=fake_pool_season_service,
        auction_valuation_service=fake_auction_valuation_service,
        simulation_results_repository=FakeSimulationResultsRepository(),
    )

    result = await service.get_leaderboard(pool_id, season)

    assert result["roster"] == []
    assert result["team"] == []


# ---------------------------------------------------------------------------
# Helpers shared by get_today_games tests
# ---------------------------------------------------------------------------


def _make_today_games_df():
    """Build a DataFrame matching the sample gamecardfeed fixture (2026-03-24 Eastern)."""
    # 4 games from the fixture, all on 2026-03-24 US/Eastern
    rows = [
        # DEN @ PHX — INGAME (halftime)
        {
            "date_time": pd.Timestamp("2026-03-25T03:00:00Z", tz="UTC"),
            "game_id": "0022501050",
            "game_url": "https://www.nba.com/game/den-vs-phx-0022501050",
            "home_team": 1610612756,  # PHX
            "home_tricode": "PHX",
            "home_score": 57,
            "away_team": 1610612743,  # DEN
            "away_tricode": "DEN",
            "away_score": 67,
            "status": NBAGameStatus.INGAME,
            "status_text": "Half",
            "game_clock": "",
        },
        # SAC @ CHA — FINAL
        {
            "date_time": pd.Timestamp("2026-03-25T00:00:00Z", tz="UTC"),
            "game_id": "0022501047",
            "game_url": "https://www.nba.com/game/sac-vs-cha-0022501047",
            "home_team": 1610612766,  # CHA
            "home_tricode": "CHA",
            "home_score": 134,
            "away_team": 1610612758,  # SAC
            "away_tricode": "SAC",
            "away_score": 90,
            "status": NBAGameStatus.FINAL,
            "status_text": "Final",
            "game_clock": "",
        },
        # NOP @ NYK — FINAL
        {
            "date_time": pd.Timestamp("2026-03-25T00:30:00Z", tz="UTC"),
            "game_id": "0022501048",
            "game_url": "https://www.nba.com/game/nop-vs-nyk-0022501048",
            "home_team": 1610612752,  # NYK
            "home_tricode": "NYK",
            "home_score": 121,
            "away_team": 1610612740,  # NOP
            "away_tricode": "NOP",
            "away_score": 116,
            "status": NBAGameStatus.FINAL,
            "status_text": "Final",
            "game_clock": "",
        },
        # ORL @ CLE — FINAL
        {
            "date_time": pd.Timestamp("2026-03-25T01:00:00Z", tz="UTC"),
            "game_id": "0022501049",
            "game_url": "https://www.nba.com/game/orl-vs-cle-0022501049",
            "home_team": 1610612739,  # CLE
            "home_tricode": "CLE",
            "home_score": 136,
            "away_team": 1610612753,  # ORL
            "away_tricode": "ORL",
            "away_score": 131,
            "status": NBAGameStatus.FINAL,
            "status_text": "Final",
            "game_clock": "",
        },
    ]
    game_df = pd.DataFrame(rows)
    game_df["date_time"] = pd.to_datetime(game_df["date_time"], utc=True).dt.tz_convert("US/Eastern")
    game_df["winning_team"] = game_df["home_team"].where(
        (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score > game_df.away_score),
        other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
    )
    game_df["losing_team"] = game_df["home_team"].where(
        (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score < game_df.away_score),
        other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
    )
    return game_df


def _make_today_games_service(game_df, teams_data):
    """Construct a LeaderboardService wired to the given DataFrame and teams."""

    class FakeNbaDataService:
        def get_current_season(self):
            return "2025-26"

        async def get_game_data(self, season):
            return game_df

    class FakePoolSeasonService:
        async def get_team_roster_mappings(self, **_):
            df = pd.DataFrame(teams_data).set_index("team_external_id")
            roster_names = sorted({r["roster_name"] for r in teams_data if r["roster_name"] != UNDRAFTED})
            return TeamRosterMappings(teams_df=df, roster_names=roster_names)

    service = LeaderboardService(
        db_session=None,
        pool_repository=None,
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=FakeNbaDataService(),
        pool_season_service=FakePoolSeasonService(),
        auction_valuation_service=None,
        simulation_results_repository=FakeSimulationResultsRepository(),
    )
    # Avoid live HTTP calls in tests that don't exercise odds logic
    service.nba_data_service.get_fanduel_moneyline_odds = lambda: {}
    return service


# ---------------------------------------------------------------------------
# get_today_games tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_today_games_returns_all_four_fixture_games():
    teams_data = [
        {
            "team_external_id": 1610612756,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Suns",
            "abbreviation": "PHX",
        },
        {
            "team_external_id": 1610612743,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Nuggets",
            "abbreviation": "DEN",
        },
        {
            "team_external_id": 1610612766,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Hornets",
            "abbreviation": "CHA",
        },
        {
            "team_external_id": 1610612758,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Kings",
            "abbreviation": "SAC",
        },
        {
            "team_external_id": 1610612752,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Knicks",
            "abbreviation": "NYK",
        },
        {
            "team_external_id": 1610612740,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Pelicans",
            "abbreviation": "NOP",
        },
        {
            "team_external_id": 1610612739,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Cavaliers",
            "abbreviation": "CLE",
        },
        {
            "team_external_id": 1610612753,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Magic",
            "abbreviation": "ORL",
        },
    ]
    service = _make_today_games_service(_make_today_games_df(), teams_data)
    result = await service.get_today_games(uuid4(), SeasonStr("2025-26"))

    assert len(result["games"]) == 4
    game_ids = {g["game_id"] for g in result["games"]}
    assert game_ids == {"0022501050", "0022501047", "0022501048", "0022501049"}


@pytest.mark.asyncio
async def test_today_games_ingame_sorts_first():
    """INGAME games appear before FINAL games."""
    teams_data = [
        {
            "team_external_id": 1610612756,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Suns",
            "abbreviation": "PHX",
        },
        {
            "team_external_id": 1610612743,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Nuggets",
            "abbreviation": "DEN",
        },
        {
            "team_external_id": 1610612766,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Hornets",
            "abbreviation": "CHA",
        },
        {
            "team_external_id": 1610612758,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Kings",
            "abbreviation": "SAC",
        },
        {
            "team_external_id": 1610612752,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Knicks",
            "abbreviation": "NYK",
        },
        {
            "team_external_id": 1610612740,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Pelicans",
            "abbreviation": "NOP",
        },
        {
            "team_external_id": 1610612739,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Cavaliers",
            "abbreviation": "CLE",
        },
        {
            "team_external_id": 1610612753,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Magic",
            "abbreviation": "ORL",
        },
    ]
    service = _make_today_games_service(_make_today_games_df(), teams_data)
    result = await service.get_today_games(uuid4(), SeasonStr("2025-26"))

    assert result["games"][0]["game_id"] == "0022501050"  # DEN @ PHX — only INGAME game
    assert result["games"][0]["status"] == NBAGameStatus.INGAME
    for game in result["games"][1:]:
        assert game["status"] == NBAGameStatus.FINAL


@pytest.mark.asyncio
async def test_today_games_scores():
    teams_data = [
        {
            "team_external_id": 1610612766,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Hornets",
            "abbreviation": "CHA",
        },
        {
            "team_external_id": 1610612758,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Kings",
            "abbreviation": "SAC",
        },
    ]
    # Use only the SAC @ CHA game
    full_df = _make_today_games_df()
    game_df = full_df[full_df["game_id"] == "0022501047"].copy()
    service = _make_today_games_service(game_df, teams_data)
    result = await service.get_today_games(uuid4(), SeasonStr("2025-26"))

    assert len(result["games"]) == 1
    game = result["games"][0]
    assert game["home_score"] == 134  # CHA
    assert game["away_score"] == 90  # SAC
    assert game["status_text"] == "Final"


@pytest.mark.asyncio
async def test_today_games_game_url():
    teams_data = [
        {
            "team_external_id": 1610612756,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Suns",
            "abbreviation": "PHX",
        },
        {
            "team_external_id": 1610612743,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Nuggets",
            "abbreviation": "DEN",
        },
    ]
    full_df = _make_today_games_df()
    game_df = full_df[full_df["game_id"] == "0022501050"].copy()
    service = _make_today_games_service(game_df, teams_data)
    result = await service.get_today_games(uuid4(), SeasonStr("2025-26"))

    assert result["games"][0]["game_url"] == "https://www.nba.com/game/den-vs-phx-0022501050"


@pytest.mark.asyncio
async def test_today_games_owner_mapping():
    """Teams drafted to a roster show the owner; undrafted teams show None."""
    teams_data = [
        {
            "team_external_id": 1610612743,
            "roster_name": "Alice",
            "auction_price": 30.0,
            "logo_url": "",
            "team_name": "Nuggets",
            "abbreviation": "DEN",
        },
        {
            "team_external_id": 1610612756,
            "roster_name": "Bob",
            "auction_price": 25.0,
            "logo_url": "",
            "team_name": "Suns",
            "abbreviation": "PHX",
        },
        {
            "team_external_id": 1610612766,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Hornets",
            "abbreviation": "CHA",
        },
        {
            "team_external_id": 1610612758,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Kings",
            "abbreviation": "SAC",
        },
    ]
    full_df = _make_today_games_df()
    game_df = full_df[full_df["game_id"].isin(["0022501050", "0022501047"])].copy()
    service = _make_today_games_service(game_df, teams_data)
    result = await service.get_today_games(uuid4(), SeasonStr("2025-26"))

    den_phx = next(g for g in result["games"] if g["game_id"] == "0022501050")
    assert den_phx["away_owner"] == "Alice"  # DEN
    assert den_phx["home_owner"] == "Bob"  # PHX

    sac_cha = next(g for g in result["games"] if g["game_id"] == "0022501047")
    assert sac_cha["away_owner"] is None  # SAC — undrafted
    assert sac_cha["home_owner"] is None  # CHA — undrafted


@pytest.mark.asyncio
async def test_today_games_empty_when_no_games():
    class EmptyNbaDataService:
        def get_current_season(self):
            return "2025-26"

        async def get_game_data(self, season):
            return pd.DataFrame()

    class FakePoolSeasonService:
        async def get_team_roster_mappings(self, **_):
            df = pd.DataFrame(columns=["roster_name", "auction_price", "logo_url", "team_name", "abbreviation"])
            df.index.name = "team_external_id"
            return TeamRosterMappings(teams_df=df, roster_names=[])

    service = LeaderboardService(
        db_session=None,
        pool_repository=None,
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=EmptyNbaDataService(),
        pool_season_service=FakePoolSeasonService(),
        auction_valuation_service=None,
        simulation_results_repository=FakeSimulationResultsRepository(),
    )
    result = await service.get_today_games(uuid4(), SeasonStr("2025-26"))

    assert result == {"date": None, "games": []}


@pytest.mark.asyncio
async def test_today_games_includes_odds_for_pregame():
    """Pregame games include vig-adjusted win percentages from FanDuel."""
    rows = [
        {
            "date_time": pd.Timestamp("2026-03-25T23:00:00Z", tz="UTC"),
            "game_id": "0022501042",
            "game_url": None,
            "home_team": 1610612741,
            "home_tricode": "CHI",
            "home_score": None,
            "away_team": 1610612745,
            "away_tricode": "HOU",
            "away_score": None,
            "status": NBAGameStatus.PREGAME,
            "status_text": "7:30 pm ET",
            "game_clock": "",
        }
    ]
    game_df = pd.DataFrame(rows)
    game_df["date_time"] = pd.to_datetime(game_df["date_time"], utc=True).dt.tz_convert("US/Eastern")
    game_df["winning_team"] = None
    game_df["losing_team"] = None

    teams_data = [
        {
            "team_external_id": 1610612741,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Bulls",
            "abbreviation": "CHI",
        },
        {
            "team_external_id": 1610612745,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Rockets",
            "abbreviation": "HOU",
        },
    ]
    service = _make_today_games_service(game_df, teams_data)

    fixed_odds = {"0022501042": {"home": 0.2289, "away": 0.7711}}
    service.nba_data_service.get_fanduel_moneyline_odds = lambda: fixed_odds

    result = await service.get_today_games(uuid4(), SeasonStr("2025-26"))

    assert len(result["games"]) == 1
    game = result["games"][0]
    assert game["home_win_pct"] == pytest.approx(0.2289)
    assert game["away_win_pct"] == pytest.approx(0.7711)


@pytest.mark.asyncio
async def test_today_games_odds_null_when_fanduel_unavailable():
    """home_win_pct and away_win_pct are None when FanDuel odds are unavailable."""
    rows = [
        {
            "date_time": pd.Timestamp("2026-03-25T23:00:00Z", tz="UTC"),
            "game_id": "0022501042",
            "game_url": None,
            "home_team": 1610612741,
            "home_tricode": "CHI",
            "home_score": None,
            "away_team": 1610612745,
            "away_tricode": "HOU",
            "away_score": None,
            "status": NBAGameStatus.PREGAME,
            "status_text": "7:30 pm ET",
            "game_clock": "",
        }
    ]
    game_df = pd.DataFrame(rows)
    game_df["date_time"] = pd.to_datetime(game_df["date_time"], utc=True).dt.tz_convert("US/Eastern")
    game_df["winning_team"] = None
    game_df["losing_team"] = None

    teams_data = [
        {
            "team_external_id": 1610612741,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Bulls",
            "abbreviation": "CHI",
        },
        {
            "team_external_id": 1610612745,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Rockets",
            "abbreviation": "HOU",
        },
    ]
    service = _make_today_games_service(game_df, teams_data)
    service.nba_data_service.get_fanduel_moneyline_odds = lambda: {}

    result = await service.get_today_games(uuid4(), SeasonStr("2025-26"))

    assert result["games"][0]["home_win_pct"] is None
    assert result["games"][0]["away_win_pct"] is None


@pytest.mark.asyncio
async def test_today_games_game_time_is_utc_string():
    """game_time is serialized as a UTC ISO string regardless of the stored US/Eastern timezone."""
    # 7:30 PM ET on 2026-03-25 = 23:30 UTC
    rows = [
        {
            "date_time": pd.Timestamp("2026-03-25T23:30:00Z", tz="UTC"),
            "game_id": "0022501042",
            "game_url": None,
            "home_team": 1610612741,
            "home_tricode": "CHI",
            "home_score": None,
            "away_team": 1610612745,
            "away_tricode": "HOU",
            "away_score": None,
            "status": NBAGameStatus.PREGAME,
            "status_text": "7:30 pm ET",
            "game_clock": "",
        }
    ]
    game_df = pd.DataFrame(rows)
    game_df["date_time"] = pd.to_datetime(game_df["date_time"], utc=True).dt.tz_convert("US/Eastern")
    game_df["winning_team"] = None
    game_df["losing_team"] = None

    teams_data = [
        {
            "team_external_id": 1610612741,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Bulls",
            "abbreviation": "CHI",
        },
        {
            "team_external_id": 1610612745,
            "roster_name": UNDRAFTED,
            "auction_price": None,
            "logo_url": "",
            "team_name": "Rockets",
            "abbreviation": "HOU",
        },
    ]
    service = _make_today_games_service(game_df, teams_data)

    result = await service.get_today_games(uuid4(), SeasonStr("2025-26"))

    assert result["games"][0]["game_time"] == "2026-03-25T23:30:00"
