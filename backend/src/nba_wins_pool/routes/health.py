from fastapi import APIRouter

from nba_wins_pool.db.core import test_connection


router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint that also tests database connectivity"""
    db_healthy = await test_connection()
    return {
        "status": "healthy" if db_healthy else "unhealthy",
        "database": "connected" if db_healthy else "disconnected",
    }
