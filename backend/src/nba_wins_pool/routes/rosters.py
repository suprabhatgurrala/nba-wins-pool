from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from nba_wins_pool.models.roster import Roster, RosterBatchCreate, RosterCreate, RosterUpdate
from nba_wins_pool.repositories.pool_season_repository import PoolSeasonRepository, get_pool_season_repository
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


@router.post("/rosters/batch", response_model=List[Roster], status_code=status.HTTP_201_CREATED)
async def create_rosters_batch(
    roster_batch_create: RosterBatchCreate,
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
    roster_repo: RosterRepository = Depends(get_roster_repository),
) -> List[Roster]:
    """Batch create rosters from various sources"""
    if roster_batch_create.source == "poolseason":
        if not roster_batch_create.source_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No source ID provided when source is 'poolseason'"
            )
        if not roster_batch_create.target_pool_season_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No target pool season ID provided when source is 'poolseason'",
            )

        source_pool_season_id = UUID(roster_batch_create.source_id)
        target_pool_season_id = UUID(roster_batch_create.target_pool_season_id)

        # Get source pool season
        source_pool_season = await pool_season_repo.get_by_id(source_pool_season_id)
        if not source_pool_season:
            raise HTTPException(status_code=404, detail="Source pool season not found")

        # Get target pool season
        target_pool_season = await pool_season_repo.get_by_id(target_pool_season_id)
        if not target_pool_season:
            raise HTTPException(status_code=404, detail="Target pool season not found")

        # Verify both pool seasons belong to the same pool
        if source_pool_season.pool_id != target_pool_season.pool_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source and target pool seasons must belong to the same pool",
            )

        # Get rosters from source season
        source_rosters = await roster_repo.get_all(pool_id=source_pool_season.pool_id, season=source_pool_season.season)
        if not source_rosters:
            raise HTTPException(status_code=404, detail="No rosters found in source season")

        # Check if target season already has rosters
        existing_rosters = await roster_repo.get_all(
            pool_id=target_pool_season.pool_id, season=target_pool_season.season
        )
        if existing_rosters:
            raise HTTPException(
                status_code=409, detail="Target season already has rosters. Delete existing rosters before importing"
            )

        # Create new rosters for target season (copy names only, not roster slots)
        new_rosters = []
        for source_roster in source_rosters:
            new_roster = Roster(
                pool_id=target_pool_season.pool_id,
                season=target_pool_season.season,
                name=source_roster.name,
            )
            new_rosters.append(new_roster)

        # Save all new rosters
        return await roster_repo.save_all(new_rosters)

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid source")
