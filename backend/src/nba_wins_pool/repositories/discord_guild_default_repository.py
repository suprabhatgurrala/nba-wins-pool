from typing import Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.discord_guild_default import DiscordGuildDefault


class DiscordGuildDefaultRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, guild_default: DiscordGuildDefault) -> DiscordGuildDefault:
        self.session.add(guild_default)
        await self.session.commit()
        await self.session.refresh(guild_default)
        return guild_default

    async def get_by_guild_id(self, guild_id: str) -> Optional[DiscordGuildDefault]:
        statement = select(DiscordGuildDefault).where(DiscordGuildDefault.guild_id == guild_id)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def delete(self, guild_default: DiscordGuildDefault) -> bool:
        await self.session.delete(guild_default)
        await self.session.commit()
        return True


def get_discord_guild_default_repository(
    db: AsyncSession = Depends(get_db_session),
) -> DiscordGuildDefaultRepository:
    return DiscordGuildDefaultRepository(db)
