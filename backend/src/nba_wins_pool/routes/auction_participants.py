from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from nba_wins_pool.models.auction_participant import (
    AuctionParticipant,
    AuctionParticipantBatchCreate,
    AuctionParticipantCreate,
)
from nba_wins_pool.services.auction_draft_service import AuctionDraftService, get_auction_draft_service

router = APIRouter(tags=["auction participants"])


@router.post(
    "/auction-participants",
    response_model=AuctionParticipant,
    status_code=status.HTTP_201_CREATED,
)
async def add_participant(
    participant_data: AuctionParticipantCreate,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Add a participant to an auction"""
    return await auction_service.add_participant(participant_data)


@router.delete(
    "/auction-participants/{participant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_participant(
    participant_id: UUID,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Remove a participant from an auction"""
    await auction_service.remove_participant(participant_id)


@router.post("/auction-participants/batch", response_model=List[AuctionParticipant])
async def add_participants_by_pool(
    auction_participant_batch_create: AuctionParticipantBatchCreate,
    auction_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    """Add all pool members as participants to the auction"""

    if auction_participant_batch_create.source == "pool":
        if not auction_participant_batch_create.auction_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No auction ID provided when source is 'pool'",
            )
        return await auction_service.add_participants_by_pool(auction_participant_batch_create.auction_id)
    elif auction_participant_batch_create.source == "request":
        if not auction_participant_batch_create.auction_participants:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No auction participants provided when source is 'request'",
            )
        return await auction_service.add_participants_by_pool(auction_participant_batch_create.auction_participants)
