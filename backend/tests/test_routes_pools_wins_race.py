from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nba_wins_pool.main_backend import app
from nba_wins_pool.services.wins_race_service import WinsRaceService, get_wins_race_service


class WinsRaceServiceStub(WinsRaceService):
    def __init__(self, payload):
        self.payload = payload

    async def get_wins_race(self, pool_id, season):  # type: ignore[override]
        return self.payload


@pytest.fixture
def client(monkeypatch):
    payload = {
        "data": [
            {"date": "2024-10-15", "roster": "Roster A", "wins": 1},
            {"date": "2024-10-15", "roster": "Roster B", "wins": 0},
        ],
        "metadata": {
            "rosters": [{"name": "Roster A"}, {"name": "Roster B"}],
            "milestones": [{"slug": "opening-night", "date": "2024-10-24", "description": "Opening Night"}],
        },
    }

    stub = WinsRaceServiceStub(payload)
    app.dependency_overrides[get_wins_race_service] = lambda: stub

    client = TestClient(app)
    try:
        yield client, payload
    finally:
        app.dependency_overrides.pop(get_wins_race_service, None)


def test_wins_race_v2_endpoint_returns_stubbed_payload(client):
    client, payload = client
    pool_id = uuid4()
    season = "2024-25"

    response = client.get(f"/api/pools/{pool_id}/season/{season}/wins-race")

    assert response.status_code == 200
    assert response.json() == payload
