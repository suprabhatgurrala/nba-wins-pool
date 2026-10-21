from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from nba_wins_pool.services.nba_data_service import NBAGameStatus
from nba_wins_pool.services.pool_season_service import TeamRosterMappings
from nba_wins_pool.services.wins_race_service import WinsRaceService
from nba_wins_pool.types.season_str import SeasonStr


class FakeNbaDataService:
    def __init__(self, scoreboard_data, schedule_data, scoreboard_date, season, milestones=None):
        self._scoreboard_data = scoreboard_data
        self._schedule_data = schedule_data
        self._scoreboard_date = scoreboard_date
        self._season = season
        self._milestones = milestones or []

    async def get_scoreboard_cached(self):
        return self._scoreboard_data, self._scoreboard_date

    async def get_gamecardfeed_cached(self):
        return self._scoreboard_data, self._scoreboard_date

    async def get_schedule_cached(self, scoreboard_date, season):
        assert season == self._season
        assert scoreboard_date == self._scoreboard_date
        return self._schedule_data, self._season

    def get_current_season(self):
        return self._season

    async def get_season_milestones(self, season_year):
        return self._milestones

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


class FakeAuctionRepository:
    def __init__(self, started_at=None):
        self._auctions = [SimpleNamespace(started_at=started_at, completed_at=None)] if started_at else []

    async def get_all(self, **_: object):
        return self._auctions


@pytest.mark.asyncio
async def test_wins_race_builds_timeseries():
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

    test_milestones = [{"slug": "opening-night", "date": "2024-10-24", "description": "Opening Night"}]
    fake_nba_service._milestones = test_milestones

    service = WinsRaceService(
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=fake_pool_season_service,
        auction_repository=FakeAuctionRepository(started_at=datetime(2024, 10, 2, 2, 0)),
    )

    result = await service.get_wins_race(pool_id, season)

    assert result["metadata"]["rosters"] == [{"name": "Roster A"}, {"name": "Roster B"}]
    assert result["metadata"]["milestones"][0]["slug"] == "opening-night"

    wins_by_date = {(entry["date"], entry["roster"]): entry["wins"] for entry in result["data"]}
    assert wins_by_date[("2024-10-15", "Roster A")] == 2
    assert wins_by_date[("2024-10-15", "Roster B")] == 0

    assert result["data"][0]["date"] == "2024-10-01"
    assert wins_by_date[("2024-10-01", "Roster A")] == 0
    assert wins_by_date[("2024-10-01", "Roster B")] == 0

    assert len({date for date, _ in wins_by_date}) == 15
    assert wins_by_date[("2024-10-07", "Roster A")] == 0


@pytest.mark.asyncio
async def test_wins_race_returns_empty_when_no_games():
    pool_id = uuid4()
    season = SeasonStr("2024-25")

    test_milestones = [{"slug": "opening-night", "date": "2024-10-24", "description": "Opening Night"}]
    fake_nba_service = FakeNbaDataService(
        [], [], scoreboard_date=pd.Timestamp("2024-10-16").date(), season=season, milestones=test_milestones
    )

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

    service = WinsRaceService(
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=fake_pool_season_service,
        auction_repository=FakeAuctionRepository(),
    )

    result = await service.get_wins_race(pool_id, season)

    assert result["data"] == []
    assert result["metadata"]["rosters"] == [{"name": "Roster A"}]
    assert result["metadata"]["milestones"][0]["slug"] == "opening-night"


@pytest.mark.asyncio
async def test_wins_race_starts_at_auction_after_season_start():
    pool_id = uuid4()
    season = SeasonStr("2024-25")

    def final(date_time, home_team, home_score, away_team, away_score):
        return {
            "date_time": date_time,
            "home_team": home_team,
            "home_score": home_score,
            "away_team": away_team,
            "away_score": away_score,
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
        }

    schedule_data = [
        final("2024-10-22T23:30:00Z", 100, 110, 200, 100),
        final("2024-10-23T23:30:00Z", 100, 100, 200, 110),
        final("2024-10-24T23:30:00Z", 100, 100, 200, 110),
    ]
    fake_nba_service = FakeNbaDataService(
        scoreboard_data=[], schedule_data=schedule_data, scoreboard_date=None, season=season
    )

    class FakePoolSeasonService:
        async def get_team_roster_mappings(self, **_: object):
            teams_df = pd.DataFrame(
                [
                    {"team_external_id": 100, "roster_name": "Roster A"},
                    {"team_external_id": 200, "roster_name": "Roster B"},
                ]
            ).set_index("team_external_id")
            return TeamRosterMappings(teams_df=teams_df, roster_names=["Roster A", "Roster B"])

    service = WinsRaceService(
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=FakePoolSeasonService(),
        auction_repository=FakeAuctionRepository(started_at=datetime(2024, 10, 23, 18, 0)),
    )

    result = await service.get_wins_race(pool_id, season)

    wins_by_date = {(entry["date"], entry["roster"]): entry["wins"] for entry in result["data"]}
    assert sorted({date for date, _ in wins_by_date}) == ["2024-10-23", "2024-10-24"]
    assert wins_by_date[("2024-10-23", "Roster A")] == 1
    assert wins_by_date[("2024-10-23", "Roster B")] == 1
    assert wins_by_date[("2024-10-24", "Roster A")] == 1
    assert wins_by_date[("2024-10-24", "Roster B")] == 2


@pytest.mark.asyncio
async def test_wins_race_runs_through_last_game_without_owned_wins():
    pool_id = uuid4()
    season = SeasonStr("2024-25")

    schedule_data = [
        {
            "date_time": date_time,
            "home_team": 300,
            "home_score": 110,
            "away_team": 100,
            "away_score": 100,
            "status_text": "Final",
            "status": NBAGameStatus.FINAL,
        }
        for date_time in ["2024-10-22T23:30:00Z", "2024-10-24T23:30:00Z"]
    ]
    fake_nba_service = FakeNbaDataService(
        scoreboard_data=[], schedule_data=schedule_data, scoreboard_date=None, season=season
    )

    class FakePoolSeasonService:
        async def get_team_roster_mappings(self, **_: object):
            teams_df = pd.DataFrame([{"team_external_id": 100, "roster_name": "Roster A"}]).set_index(
                "team_external_id"
            )
            return TeamRosterMappings(teams_df=teams_df, roster_names=["Roster A"])

    service = WinsRaceService(
        roster_repository=None,
        roster_slot_repository=None,
        team_repository=None,
        nba_data_service=fake_nba_service,
        pool_season_service=FakePoolSeasonService(),
        auction_repository=FakeAuctionRepository(started_at=datetime(2024, 10, 20, 18, 0)),
    )

    result = await service.get_wins_race(pool_id, season)

    assert result["data"] == [
        {"date": date, "roster": "Roster A", "wins": 0}
        for date in ["2024-10-20", "2024-10-21", "2024-10-22", "2024-10-23", "2024-10-24"]
    ]
