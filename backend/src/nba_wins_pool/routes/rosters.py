from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from nba_wins_pool.models.roster import Roster, RosterCreate, RosterUpdate
from nba_wins_pool.repositories.roster_repository import RosterRepository, get_roster_repository
from nba_wins_pool.types.season_str import SeasonStr

router = APIRouter(tags=["rosters"])


@router.post("/rosters", response_model=Roster, status_code=status.HTTP_201_CREATED)
async def create_roster(
    roster_data: RosterCreate,
    roster_repo: RosterRepository = Depends(get_roster_repository),
):
    roster = Roster.model_validate(roster_data)
    roster = await roster_repo.save(roster)
    return roster


@router.get("/rosters/{roster_id}", response_model=Roster)
async def get_roster(roster_id: UUID, roster_repo: RosterRepository = Depends(get_roster_repository)):
    """Get a specific roster by ID"""
    roster = await roster_repo.get_by_id(roster_id)

    if not roster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Roster with id {roster_id} not found")

    return roster


@router.patch("/rosters/{roster_id}", response_model=Roster)
async def update_roster(
    roster_id: UUID,
    roster_update: RosterUpdate,
    roster_repo: RosterRepository = Depends(get_roster_repository),
):
    """Update a specific roster by ID"""
    roster = await roster_repo.get_by_id(roster_id)

    if not roster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Roster with id {roster_id} not found")

    roster_data = roster_update.model_dump(exclude_unset=True)
    roster.sqlmodel_update(roster_data)
    return await roster_repo.save(roster)


@router.delete("/rosters/{roster_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_roster(roster_id: UUID, roster_repo: RosterRepository = Depends(get_roster_repository)):
    roster = await roster_repo.get_by_id(roster_id)
    if not roster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Roster with id {roster_id} not found")
    await roster_repo.delete(roster)


@router.get("/rosters", response_model=List[Roster])
async def get_rosters(
    pool_id: UUID | None = None,
    season: SeasonStr | None = None,
    roster_repo: RosterRepository = Depends(get_roster_repository),
):
    """Query rosters"""
    return await roster_repo.get_all(pool_id, season)
