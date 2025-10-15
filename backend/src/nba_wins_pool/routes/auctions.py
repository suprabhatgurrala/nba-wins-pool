from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from nba_wins_pool.event.broker import Broker, get_broker
from nba_wins_pool.models.auction import (
    Auction,
    AuctionCompletedEvent,
    AuctionCreate,
    AuctionOverview,
    AuctionStatus,
    AuctionTopic,
    AuctionUpdate,
)
from nba_wins_pool.models.auction_valuation import AuctionValuationData
from nba_wins_pool.services.auction_draft_service import (
    AuctionDraftService,
    get_auction_draft_service,
)
from nba_wins_pool.services.auction_valuation_service import (
    AuctionValuationService,
    get_auction_valuation_service,
)
from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.server_sent_events import sse_event_generator
from nba_wins_pool.utils.time import utc_now

router = APIRouter(tags=["auctions"])


# Auction Management
@router.post("/auctions", response_model=Auction, status_code=status.HTTP_201_CREATED)
async def create_auction(
    auction_data: AuctionCreate,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Create a new auction draft"""
    return await auction_service.create_auction(auction_data)


@router.get("/auctions", response_model=List[Auction])
async def get_auctions(
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
    pool_id: UUID = None,
    season: SeasonStr = None,
    status: AuctionStatus = None,
):
    """Get all auction drafts"""
    return await auction_service.get_auctions(pool_id=pool_id, season=season, status=status)


@router.delete("/auctions/{auction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_auction(
    auction_id: UUID,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Delete an auction draft"""
    await auction_service.delete_auction(auction_id)


@router.patch("/auctions/{auction_id}", response_model=Auction)
async def update_auction(
    auction_id: UUID,
    auction_update: AuctionUpdate,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Update an auction draft"""
    # Handle status transitions
    if auction_update.status == AuctionStatus.ACTIVE:
        return await auction_service.start_auction(auction_id)
    elif auction_update.status == AuctionStatus.COMPLETED:
        return await auction_service.complete_auction(auction_id)
    
    # Handle configuration updates (only allowed when not started)
    if any([
        auction_update.max_lots_per_participant is not None,
        auction_update.min_bid_increment is not None,
        auction_update.starting_participant_budget is not None,
    ]):
        return await auction_service.update_auction_config(auction_id, auction_update)
    
    raise HTTPException(status_code=400, detail="Invalid auction update")


@router.get("/auctions/{auction_id}/overview", response_model=AuctionOverview)
async def get_auction_summary(
    auction_id: UUID,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Get auction summary including lots, participants, and current status"""
    return await auction_service.get_auction_overview(auction_id)


@router.get("/auctions/{auction_id}/events", response_class=EventSourceResponse)
async def subscribe_to_auction_events(
    auction_id: UUID,
    broker: Broker = Depends(get_broker),
):
    """Subscribe to live auction events via SSE"""
    generator = sse_event_generator(AuctionTopic(auction_id=auction_id), broker)
    return EventSourceResponse(generator)


@router.get("/auctions/{auction_id}/events/history")
async def get_auction_event_history(
    auction_id: UUID,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Get historical events for an auction"""
    return await auction_service.get_event_history(auction_id)


@router.post("/auctions/{auction_id}/test_event", status_code=status.HTTP_204_NO_CONTENT)
async def test_event(
    auction_id: UUID,
    broker: Broker = Depends(get_broker),
):
    await broker.publish(
        AuctionTopic(auction_id=auction_id), AuctionCompletedEvent(auction_id=auction_id, completed_at=utc_now())
    )


@router.get("/auctions/{auction_id}/valuation-data", response_model=AuctionValuationData)
async def get_auction_valuation_data(
    auction_id: UUID,
    valuation_service: AuctionValuationService = Depends(get_auction_valuation_service),
):
    """Get auction valuation data based on current FanDuel odds.
    
    Calculates team valuations using the auction's configuration:
    - Number of participants (counted from auction participants)
    - Budget per participant (from auction.starting_participant_budget)
    - Teams per participant (from auction.max_lots_per_participant)
    
    Returns valuation data with expected wins and auction values for all NBA teams.
    """
    return await valuation_service.get_valuation_data_for_auction(auction_id)
