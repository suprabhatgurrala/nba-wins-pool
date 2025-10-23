from datetime import date
from uuid import uuid4

import pandas as pd
import pytest

from nba_wins_pool.services.leaderboard_service import LeaderboardService
from nba_wins_pool.services.nba_data_service import NBAGameStatus
from nba_wins_pool.services.pool_season_service import TeamRosterMappings
from nba_wins_pool.types.season_str import SeasonStr


class FakeNbaDataService:
    def __init__(self, scoreboard_data, schedule_data, scoreboard_date):
        self._scoreboard_data = scoreboard_data
        self._schedule_data = schedule_data
        self._scoreboard_date = scoreboard_date
        self._current_season = "2024-25"

    async def get_scoreboard_cached(self):
        return self._scoreboard_data, self._scoreboard_date

    async def get_schedule_cached(self, scoreboard_date, season):
        # In the test, we want to return the schedule data regardless of the date
        # since we're testing the leaderboard logic, not the caching
        return self._schedule_data, self._current_season

    async def get_current_season(self):
        return self._current_season


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
            "gameId": "1234"
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
            "gameId": "1233"
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

    service = LeaderboardService(
        db_session=None,
        pool_repository=None,
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=fake_pool_season_service,
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
        async def get_scoreboard_cached(self):
            return [], date.today()
            
        async def get_schedule_cached(self, scoreboard_date, season):
            return [], season
            
        async def get_current_season(self):
            return "2024-25"
            
    fake_nba_service = EmptyNbaDataService()

    class FakePoolSeasonService:
        async def get_team_roster_mappings(self, **_: object):
            teams_df = pd.DataFrame(columns=["roster_name", "auction_price", "logo_url", "team_name", "abbreviation"])
            teams_df.index.name = "team_external_id"
            return TeamRosterMappings(teams_df=teams_df, roster_names=[])

    fake_pool_season_service = FakePoolSeasonService()

    service = LeaderboardService(
        db_session=None,
        pool_repository=None,
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=fake_pool_season_service,
    )

    result = await service.get_leaderboard(pool_id, season)

    assert result["roster"] == []
    assert result["team"] == []
