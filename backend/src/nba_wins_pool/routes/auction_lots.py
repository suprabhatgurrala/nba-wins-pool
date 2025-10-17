from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from nba_wins_pool.models.auction_lot import (
    AuctionLot,
    AuctionLotBatchCreate,
    AuctionLotCreate,
    AuctionLotStatus,
    AuctionLotUpdate,
)
from nba_wins_pool.models.team import LeagueSlug
from nba_wins_pool.repositories.auction_lot_repository import AuctionLotRepository, get_auction_lot_repository
from nba_wins_pool.services.auction_draft_service import AuctionDraftService, get_auction_draft_service

router = APIRouter(tags=["auction lots"])


@router.post(
    "/auction-lots",
    response_model=AuctionLot,
    status_code=status.HTTP_201_CREATED,
)
async def create_lot(
    lot_data: AuctionLotCreate,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Create an auction lot"""
    return await auction_service.create_lot(lot_data)


@router.patch("/auction-lots/{lot_id}", response_model=AuctionLot)
async def update_lot(
    lot_id: UUID,
    lot_update: AuctionLotUpdate,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Update an auction lot. Only supports closing lots."""
    if lot_update.status == AuctionLotStatus.CLOSED:
        return await auction_service.close_lot(lot_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid lot update")


# Lot Management
@router.post("/auction-lots/batch", response_model=List[AuctionLot])
async def batch_add_auction_lots(
    auction_lot_batch_create: AuctionLotBatchCreate,
    auction_lot_repository: AuctionLotRepository = Depends(get_auction_lot_repository),
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Batch add team lots to the auction"""
    if auction_lot_batch_create.source == "league":
        if not auction_lot_batch_create.auction_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No auction ID provided when source is 'league'"
            )
        if not auction_lot_batch_create.source_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No source ID provided when source is 'league'"
            )
        league_slug = LeagueSlug(auction_lot_batch_create.source_id)
        return await auction_service.add_lots_by_league(auction_lot_batch_create.auction_id, league_slug)
    elif auction_lot_batch_create.source == "request":
        if not auction_lot_batch_create.auction_lots:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No auction lots provided when source is 'request'"
            )
        return await auction_lot_repository.save_all(auction_lot_batch_create.auction_lots)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Source is not supported",
    )
