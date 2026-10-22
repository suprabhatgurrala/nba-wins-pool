from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from nba_wins_pool.main_backend import app
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.repositories.pool_repository import get_pool_repository
from nba_wins_pool.repositories.roster_slot_repository import get_roster_slot_repository
from nba_wins_pool.services.leaderboard_service import get_leaderboard_service
from nba_wins_pool.services.nba_data_service import get_nba_data_service
from nba_wins_pool.services.wins_race_service import get_wins_race_service

POOL = Pool(slug="sg", name="Pool")
CHECKED_AT = datetime(2026, 1, 5, 2, 30, tzinfo=timezone.utc)


class PoolRepositoryStub:
    async def get_by_slug(self, slug):
        return POOL if slug == POOL.slug else None


class RosterSlotRepositoryStub:
    def __init__(self, drafted):
        self.drafted = drafted

    async def any_for_pool_season(self, pool_id, season):
        return self.drafted


class LeaderboardServiceStub:
    def __init__(self):
        self.calls = []

    async def get_leaderboard(self, pool_id, season):
        self.calls.append("leaderboard")
        return {"roster": [{"name": "Alice"}], "team": []}

    async def get_today_games(self, pool_id, season, game_date=None):
        self.calls.append(("games", game_date))
        return {"date": str(game_date or "2026-01-04"), "games": []}


class WinsRaceServiceStub:
    async def get_wins_race(self, pool_id, season):
        return {"data": [], "metadata": {}}


class NbaDataServiceStub:
    async def get_live_checked_at(self, season):
        return CHECKED_AT


@pytest.fixture
def make_client():
    leaderboard = LeaderboardServiceStub()

    def make(drafted=True):
        app.dependency_overrides[get_pool_repository] = PoolRepositoryStub
        app.dependency_overrides[get_roster_slot_repository] = lambda: RosterSlotRepositoryStub(drafted)
        app.dependency_overrides[get_leaderboard_service] = lambda: leaderboard
        app.dependency_overrides[get_wins_race_service] = WinsRaceServiceStub
        app.dependency_overrides[get_nba_data_service] = NbaDataServiceStub
        return TestClient(app), leaderboard

    yield make
    app.dependency_overrides.clear()


def test_live_returns_standings_wins_race_and_games(make_client):
    client, _ = make_client()

    body = client.get("/api/pools/slug/sg/seasons/2025-26/live").json()

    assert body["leaderboard"]["roster"] == [{"name": "Alice"}]
    assert body["wins_race"] == {"data": [], "metadata": {}}
    assert body["today_games"]["date"] == "2026-01-04"
    assert body["nba_checked_at"] == CHECKED_AT.isoformat()


def test_live_skips_standings_until_a_team_is_drafted(make_client):
    client, leaderboard = make_client(drafted=False)

    body = client.get("/api/pools/slug/sg/seasons/2025-26/live").json()

    assert body["leaderboard"] is None
    assert body["wins_race"] is None
    assert "leaderboard" not in leaderboard.calls


def test_live_unknown_pool_is_404(make_client):
    client, _ = make_client()

    assert client.get("/api/pools/slug/nope/seasons/2025-26/live").status_code == 404


def test_games_for_date(make_client):
    client, leaderboard = make_client()

    body = client.get("/api/pools/slug/sg/seasons/2025-26/games", params={"date": "2026-01-10"}).json()

    assert body["date"] == "2026-01-10"
    assert leaderboard.calls[-1][0] == "games"
