import uuid
from typing import Optional

from fastapi import Depends

from nba_wins_pool.models.discord_guild_default import DiscordGuildDefault
from nba_wins_pool.repositories.discord_guild_default_repository import (
    DiscordGuildDefaultRepository,
    get_discord_guild_default_repository,
)
from nba_wins_pool.utils.time import utc_now


class DiscordGuildDefaultService:
    """Keeps at most one default pool per Discord server."""

    def __init__(self, repository: DiscordGuildDefaultRepository):
        self.repository = repository

    async def get_default(self, guild_id: str) -> Optional[DiscordGuildDefault]:
        return await self.repository.get_by_guild_id(guild_id)

    async def set_default(self, guild_id: str, pool_id: uuid.UUID) -> DiscordGuildDefault:
        guild_default = await self.repository.get_by_guild_id(guild_id)
        if guild_default:
            guild_default.pool_id = pool_id
            guild_default.updated_at = utc_now()
        else:
            guild_default = DiscordGuildDefault(guild_id=guild_id, pool_id=pool_id)
        return await self.repository.save(guild_default)

    async def clear_default(self, guild_id: str) -> None:
        guild_default = await self.repository.get_by_guild_id(guild_id)
        if guild_default:
            await self.repository.delete(guild_default)


def get_discord_guild_default_service(
    repository: DiscordGuildDefaultRepository = Depends(get_discord_guild_default_repository),
) -> DiscordGuildDefaultService:
    return DiscordGuildDefaultService(repository)
