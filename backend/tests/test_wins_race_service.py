from uuid import uuid4

import pandas as pd
import pytest

from nba_wins_pool.services.nba_data_service import NBAGameStatus
from nba_wins_pool.services.pool_season_service import TeamRosterMappings
from nba_wins_pool.services.wins_race_service import WinsRaceService
from nba_wins_pool.types.season_str import SeasonStr


class FakeNbaDataService:
    def __init__(self, scoreboard_data, schedule_data, scoreboard_date, season):
        self._scoreboard_data = scoreboard_data
        self._schedule_data = schedule_data
        self._scoreboard_date = scoreboard_date
        self._season = season

    async def get_scoreboard_cached(self):
        return self._scoreboard_data, self._scoreboard_date

    async def get_schedule_cached(self, scoreboard_date, season):
        assert season == self._season
        assert scoreboard_date == self._scoreboard_date
        return self._schedule_data, self._season

    def get_current_season(self):
        return self._season


@pytest.mark.asyncio
async def test_wins_race_builds_timeseries(monkeypatch):
    pool_id = uuid4()
    season = SeasonStr("2024-25")

    scoreboard_date = pd.Timestamp("2024-10-16", tz="UTC").date()

    scoreboard_data = [
        {
            "date_time": "2024-10-16T00:00:00Z",
            "home_team": 100,
            "home_score": 108,
            "away_team": 200,
            "away_score": 101,
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
        }
    ]
    schedule_data = [
        {
            "date_time": "2024-10-15T00:00:00Z",
            "home_team": 200,
            "home_score": 104,
            "away_team": 100,
            "away_score": 110,
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
        }
    ]

    fake_nba_service = FakeNbaDataService(
        scoreboard_data=scoreboard_data,
        schedule_data=schedule_data,
        scoreboard_date=scoreboard_date,
        season=season,
    )

    class FakePoolSeasonService:
        async def get_team_roster_mappings(self, **_: object):
            teams_data = [
                {
                    "team_external_id": 100,
                    "roster_name": "Roster A",
                    "auction_price": 10.0,
                    "logo_url": "logo-a",
                    "team_name": "Team A",
                    "abbreviation": "TMA",
                },
                {
                    "team_external_id": 200,
                    "roster_name": "Roster B",
                    "auction_price": 12.0,
                    "logo_url": "logo-b",
                    "team_name": "Team B",
                    "abbreviation": "TMB",
                },
            ]
            teams_df = pd.DataFrame(teams_data).set_index("team_external_id")
            return TeamRosterMappings(teams_df=teams_df, roster_names=["Roster A", "Roster B"])

    fake_pool_season_service = FakePoolSeasonService()

    # Mock SEASON_MILESTONES dictionary
    test_milestones = {
        "2024-25": [
            {
                "slug": "opening-night",
                "date": "2024-10-24",
                "description": "Opening Night",
            }
        ]
    }
    monkeypatch.setattr(
        "nba_wins_pool.services.wins_race_service.SEASON_MILESTONES",
        test_milestones,
    )

    service = WinsRaceService(
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=fake_pool_season_service,
    )

    result = await service.get_wins_race(pool_id, season)

    assert result["metadata"]["rosters"] == [{"name": "Roster A"}, {"name": "Roster B"}]
    assert result["metadata"]["milestones"][0]["slug"] == "opening-night"

    wins_by_date = {(entry["date"], entry["roster"]): entry["wins"] for entry in result["data"]}
    assert wins_by_date[("2024-10-15", "Roster A")] == 2
    assert wins_by_date[("2024-10-15", "Roster B")] == 0


@pytest.mark.asyncio
async def test_wins_race_returns_empty_when_no_games(monkeypatch):
    pool_id = uuid4()
    season = SeasonStr("2024-25")

    fake_nba_service = FakeNbaDataService([], [], scoreboard_date=pd.Timestamp("2024-10-16").date(), season=season)

    class FakePoolSeasonService:
        async def get_team_roster_mappings(self, **_: object):
            teams_data = [
                {
                    "team_external_id": 100,
                    "roster_name": "Roster A",
                    "auction_price": None,
                    "logo_url": "logo-a",
                    "team_name": "Team A",
                    "abbreviation": "TMA",
                },
            ]
            teams_df = pd.DataFrame(teams_data).set_index("team_external_id")
            return TeamRosterMappings(teams_df=teams_df, roster_names=["Roster A"])

    fake_pool_season_service = FakePoolSeasonService()

    # Mock SEASON_MILESTONES dictionary
    test_milestones = {"2024-25": [{"slug": "opening-night", "date": "2024-10-24", "description": "Opening Night"}]}
    monkeypatch.setattr(
        "nba_wins_pool.services.wins_race_service.SEASON_MILESTONES",
        test_milestones,
    )

    service = WinsRaceService(
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=fake_pool_season_service,
    )

    result = await service.get_wins_race(pool_id, season)

    assert result["data"] == []
    assert result["metadata"]["rosters"] == [{"name": "Roster A"}]
    assert result["metadata"]["milestones"][0]["slug"] == "opening-night"
