from fastapi import APIRouter

from .auction_bids import router as auction_bids_router
from .auction_lots import router as auction_lots_router
from .auction_participants import router as auction_participants_router
from .auctions import router as auctions_router
from .health import router as health_router
from .pools import router as pools_router
from .roster_slots import router as roster_slots_router
from .rosters import router as rosters_router
from .sse import router as sse_router

# register routers here
api_router = APIRouter(prefix="/api")
api_router.include_router(pools_router)
api_router.include_router(rosters_router)
api_router.include_router(auctions_router)
api_router.include_router(auction_participants_router)
api_router.include_router(auction_lots_router)
api_router.include_router(auction_bids_router)
api_router.include_router(roster_slots_router)

internal_router = APIRouter(prefix="/internal", tags=["internal"])
internal_router.include_router(health_router)
internal_router.include_router(sse_router)

app_router = APIRouter()
app_router.include_router(api_router)
app_router.include_router(internal_router)
