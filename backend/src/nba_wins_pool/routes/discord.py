from fastapi import APIRouter, Depends, HTTPException, status

from nba_wins_pool.models.discord_guild_default import DiscordGuildDefaultResponse, DiscordGuildDefaultUpdate
from nba_wins_pool.repositories.pool_repository import PoolRepository, get_pool_repository
from nba_wins_pool.services.discord_guild_default_service import (
    DiscordGuildDefaultService,
    get_discord_guild_default_service,
)

router = APIRouter(prefix="/discord", tags=["discord"])


@router.get("/guilds/{guild_id}/default-pool", response_model=DiscordGuildDefaultResponse)
async def get_default_pool(
    guild_id: str,
    service: DiscordGuildDefaultService = Depends(get_discord_guild_default_service),
):
    """Get the default pool for a Discord server"""
    guild_default = await service.get_default(guild_id)
    if not guild_default:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No default pool for guild {guild_id}")
    return guild_default


@router.put("/guilds/{guild_id}/default-pool", response_model=DiscordGuildDefaultResponse)
async def set_default_pool(
    guild_id: str,
    update: DiscordGuildDefaultUpdate,
    service: DiscordGuildDefaultService = Depends(get_discord_guild_default_service),
    pool_repo: PoolRepository = Depends(get_pool_repository),
):
    """Set the default pool for a Discord server"""
    if not await pool_repo.get_by_id(update.pool_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pool with id {update.pool_id} not found")
    return await service.set_default(guild_id, update.pool_id)


@router.delete("/guilds/{guild_id}/default-pool", status_code=status.HTTP_204_NO_CONTENT)
async def clear_default_pool(
    guild_id: str,
    service: DiscordGuildDefaultService = Depends(get_discord_guild_default_service),
):
    """Clear the default pool for a Discord server"""
    await service.clear_default(guild_id)
