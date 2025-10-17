from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends

from nba_wins_pool.models.bid import Bid, BidCreate
from nba_wins_pool.repositories.bid_repository import BidRepository, get_bid_repository
from nba_wins_pool.services.auction_draft_service import AuctionDraftService, get_auction_draft_service

router = APIRouter(tags=["auction bids"])


# Bidding Operations
@router.post("/bids", response_model=Bid)
async def place_bid(
    bid_create: BidCreate,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    return await auction_service.place_bid(bid_create)


@router.get("/bids", response_model=List[Bid])
async def get_bids(
    lot_id: Optional[UUID] = None,
    participant_id: Optional[UUID] = None,
    bid_repository: BidRepository = Depends(get_bid_repository),
):
    return await bid_repository.get_all(lot_id=lot_id, participant_id=participant_id)
