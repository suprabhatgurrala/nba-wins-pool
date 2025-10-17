from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.team_repository import TeamRepository, get_team_repository

router = APIRouter(tags=["teams"])


@router.get("/teams", response_model=List[Team])
async def list_teams(
    league_slug: LeagueSlug | None = LeagueSlug.NBA,
    team_repo: TeamRepository = Depends(get_team_repository),
) -> List[Team]:
    if league_slug is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="league_slug is required")
    return await team_repo.get_all_by_league_slug(league_slug)


# @router.post("/teams", response_model=Team, status_code=status.HTTP_201_CREATED)
# async def create_team(
#     team_data: TeamCreate,
#     team_repo: TeamRepository = Depends(get_team_repository),
# ) -> Team:
#     # Simple create; caller responsible for providing proper external_id
#     team = Team.model_validate(team_data)
#     return await team_repo.save(team)
