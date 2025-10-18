from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from nba_wins_pool.models.roster_slot import RosterSlot, RosterSlotBatchCreate, RosterSlotCreate
from nba_wins_pool.repositories.roster_slot_repository import RosterSlotRepository, get_roster_slot_repository
from nba_wins_pool.services.auction_draft_service import AuctionDraftService, get_auction_draft_service

router = APIRouter(tags=["roster slots"])


@router.post("/roster-slots/batch", response_model=List[RosterSlot])
async def create_roster_slots_batch(
    roster_slot_batch_create: RosterSlotBatchCreate,
    roster_slot_repo: RosterSlotRepository = Depends(get_roster_slot_repository),
    auction_draft_service: AuctionDraftService = Depends(get_auction_draft_service),
):
    if roster_slot_batch_create.source == "auction":
        if not roster_slot_batch_create.source_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No source ID provided when source is 'auction'"
            )
        auction_id = UUID(roster_slot_batch_create.source_id)
        return await auction_draft_service.create_roster_slots_from_lots_won(auction_id)
    if roster_slot_batch_create.source == "request":
        if not roster_slot_batch_create.roster_slots:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No roster slots provided when source is 'request'"
            )
        roster_slots = [
            RosterSlotCreate.model_validate(roster_slot) for roster_slot in roster_slot_batch_create.roster_slots
        ]
        return await roster_slot_repo.save_all(roster_slots)

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid source")
