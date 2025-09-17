from fastapi import APIRouter
from sqlmodel import SQLModel

from nba_wins_pool.db.core import test_connection

router = APIRouter()


class HealthCheckResponse(SQLModel):
    status: str
    database: str


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Health check endpoint that also tests database connectivity"""
    db_healthy = await test_connection()
    return HealthCheckResponse(
        status="healthy" if db_healthy else "unhealthy",
        database="connected" if db_healthy else "disconnected",
    )
