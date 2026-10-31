from typing import Dict, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from nba_wins_pool.main_backend import app
from nba_wins_pool.models.discord_guild_default import DiscordGuildDefault
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.repositories.pool_repository import get_pool_repository
from nba_wins_pool.services.discord_guild_default_service import (
    DiscordGuildDefaultService,
    get_discord_guild_default_service,
)

GUILD_ID = "1234567890123456789"


class FakeDiscordGuildDefaultRepository:
    def __init__(self):
        self.rows: Dict[UUID, DiscordGuildDefault] = {}

    async def save(self, guild_default: DiscordGuildDefault) -> DiscordGuildDefault:
        self.rows[guild_default.id] = guild_default
        return guild_default

    async def get_by_guild_id(self, guild_id: str) -> Optional[DiscordGuildDefault]:
        return next((row for row in self.rows.values() if row.guild_id == guild_id), None)

    async def delete(self, guild_default: DiscordGuildDefault) -> bool:
        self.rows.pop(guild_default.id, None)
        return True


class FakePoolRepository:
    def __init__(self, pools):
        self.pools = {pool.id: pool for pool in pools}

    async def get_by_id(self, pool_id: UUID) -> Optional[Pool]:
        return self.pools.get(pool_id)


@pytest.fixture
def repo():
    return FakeDiscordGuildDefaultRepository()


@pytest.fixture
def service(repo):
    return DiscordGuildDefaultService(repo)


@pytest.fixture
def pool():
    return Pool(slug="sg", name="SG Pool")


@pytest.fixture
def client(service, pool):
    app.dependency_overrides[get_discord_guild_default_service] = lambda: service
    app.dependency_overrides[get_pool_repository] = lambda: FakePoolRepository([pool])
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_default_replaces_the_existing_row(service, repo):
    first, second = uuid4(), uuid4()

    await service.set_default(GUILD_ID, first)
    await service.set_default(GUILD_ID, second)

    assert [row.pool_id for row in repo.rows.values()] == [second]


@pytest.mark.asyncio
async def test_defaults_are_per_guild(service):
    pool_a, pool_b = uuid4(), uuid4()

    await service.set_default("1", pool_a)
    await service.set_default("2", pool_b)

    assert (await service.get_default("1")).pool_id == pool_a
    assert (await service.get_default("2")).pool_id == pool_b


@pytest.mark.asyncio
async def test_clear_default_removes_the_row_and_is_idempotent(service, repo):
    await service.set_default(GUILD_ID, uuid4())

    await service.clear_default(GUILD_ID)
    await service.clear_default(GUILD_ID)

    assert repo.rows == {}


def test_get_default_pool_is_404_when_unset(client):
    response = client.get(f"/api/discord/guilds/{GUILD_ID}/default-pool")

    assert response.status_code == 404


def test_put_then_get_default_pool(client, pool):
    put = client.put(f"/api/discord/guilds/{GUILD_ID}/default-pool", json={"pool_id": str(pool.id)})
    get = client.get(f"/api/discord/guilds/{GUILD_ID}/default-pool")

    assert put.status_code == 200
    assert get.json() == {"guild_id": GUILD_ID, "pool_id": str(pool.id)}


def test_put_default_pool_rejects_an_unknown_pool(client, repo):
    response = client.put(f"/api/discord/guilds/{GUILD_ID}/default-pool", json={"pool_id": str(uuid4())})

    assert response.status_code == 404
    assert repo.rows == {}


def test_delete_default_pool(client, pool):
    client.put(f"/api/discord/guilds/{GUILD_ID}/default-pool", json={"pool_id": str(pool.id)})

    first = client.delete(f"/api/discord/guilds/{GUILD_ID}/default-pool")
    second = client.delete(f"/api/discord/guilds/{GUILD_ID}/default-pool")

    assert (first.status_code, second.status_code) == (204, 204)
    assert client.get(f"/api/discord/guilds/{GUILD_ID}/default-pool").status_code == 404
