from fastapi import APIRouter

from .health import router as health_router
from .pool import router as pool_router

# API router for external endpoints
api_router = APIRouter()
api_router.include_router(pool_router)

# Internal router for health checks and internal endpoints
internal_router = APIRouter()
internal_router.include_router(health_router)

# Combined router if needed
router = APIRouter()
router.include_router(pool_router)
router.include_router(health_router)
