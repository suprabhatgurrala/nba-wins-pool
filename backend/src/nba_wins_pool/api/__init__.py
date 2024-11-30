from fastapi import APIRouter

from .pool import router as pool_router

router = APIRouter()
router.include_router(pool_router, prefix="/pool")
