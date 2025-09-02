from fastapi import APIRouter

from .health import router as health_router
from .pool import router as pool_router

# register routers here
api_router = APIRouter(prefix="/api")
api_router.include_router(pool_router)

internal_router = APIRouter(prefix="/internal")
internal_router.include_router(health_router)

app_router = APIRouter()
app_router.include_router(api_router)
app_router.include_router(internal_router)
