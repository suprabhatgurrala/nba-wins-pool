from fastapi import APIRouter
from .leaderboard import router as leaderboard_router

router = APIRouter()
router.include_router(leaderboard_router)
