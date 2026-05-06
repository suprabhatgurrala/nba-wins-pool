from fastapi import APIRouter

from ..services.team_colors_service import get_matchup_colors, get_matchup_colors_debug

router = APIRouter(tags=["team-colors"])


@router.get("/team-colors")
def get_team_colors() -> dict[str, dict[str, dict[str, str]]]:
    return get_matchup_colors()


@router.get("/team-colors/debug")
def get_team_colors_debug() -> dict[str, dict[str, dict[str, str]]]:
    return get_matchup_colors_debug()
