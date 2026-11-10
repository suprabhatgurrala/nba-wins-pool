import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nba_wins_pool.main_backend import app
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.repositories.pool_repository import get_pool_repository
from nba_wins_pool.services.win_probability_history_service import (
    WinProbabilityHistoryService,
    get_win_probability_history_service,
)

ALICE = uuid.uuid4()
BOB = uuid.uuid4()
GONE = uuid.uuid4()
T1 = datetime(2026, 10, 21, 3, 0)
T2 = datetime(2026, 10, 21, 4, 0)
MILESTONES = [{"slug": "all_star_break", "date": "2027-02-13", "description": "All-Star Break"}]


def _ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


class SimRepoStub:
    def __init__(self, rows):
        self.rows = rows

    async def get_roster_history(self, season, pool_id):
        return self.rows


class RosterRepoStub:
    async def get_all(self, pool_id=None, season=None):
        return [SimpleNamespace(id=BOB, name="Bob"), SimpleNamespace(id=ALICE, name="Alice")]


class NbaDataStub:
    async def get_season_milestones(self, season):
        return MILESTONES


def _service(rows) -> WinProbabilityHistoryService:
    return WinProbabilityHistoryService(SimRepoStub(rows), RosterRepoStub(), NbaDataStub())


@pytest.mark.asyncio
async def test_history_aligns_each_roster_to_the_shared_timestamps():
    rows = [(T1, ALICE, 0.315), (T1, BOB, 0.685), (T2, BOB, 0.6), (T2, GONE, 0.1)]

    history = await _service(rows).get_history(uuid.uuid4(), "2026-27")

    assert history["rosters"] == [{"id": str(ALICE), "name": "Alice"}, {"id": str(BOB), "name": "Bob"}]
    assert history["timestamps"] == [_ms(T1), _ms(T2)]
    assert history["series"] == {str(ALICE): [31.5, None], str(BOB): [68.5, 60.0]}
    assert history["milestones"] == MILESTONES


@pytest.mark.asyncio
async def test_history_is_empty_without_stored_runs():
    history = await _service([]).get_history(uuid.uuid4(), "2024-25")

    assert history == {"rosters": [], "timestamps": [], "series": {}, "milestones": []}


def test_route_returns_the_pools_history():
    pool = Pool(slug="sg", name="Pool")

    class PoolRepoStub:
        async def get_by_slug(self, slug):
            return pool if slug == "sg" else None

    app.dependency_overrides[get_pool_repository] = PoolRepoStub
    app.dependency_overrides[get_win_probability_history_service] = lambda: _service([(T1, ALICE, 0.5)])
    try:
        client = TestClient(app)
        body = client.get("/api/pools/slug/sg/seasons/2026-27/win-probability-history").json()
        missing = client.get("/api/pools/slug/nope/seasons/2026-27/win-probability-history")
    finally:
        app.dependency_overrides.clear()

    assert body["series"] == {str(ALICE): [50.0]}
    assert missing.status_code == 404
