from fastapi import APIRouter

from .auction import router as auction_router
from .pool import router as pool_router

router = APIRouter()
router.include_router(pool_router, prefix="/pool")
router.include_router(auction_router, prefix="/auction")
