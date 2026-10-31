import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from nba_wins_pool.utils.time import utc_now


class DiscordGuildDefault(SQLModel, table=True):
    """The pool a Discord server's standings command shows when no pool is given."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    guild_id: str = Field(max_length=32, index=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True, ondelete="CASCADE")
    updated_at: datetime = Field(default_factory=utc_now)


class DiscordGuildDefaultUpdate(SQLModel):
    pool_id: uuid.UUID


class DiscordGuildDefaultResponse(SQLModel):
    guild_id: str
    pool_id: uuid.UUID
