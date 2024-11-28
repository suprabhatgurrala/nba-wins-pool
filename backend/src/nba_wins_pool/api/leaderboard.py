from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from nba_wins_pool.aggregations import generate_leaderboard, generate_team_breakdown
from nba_wins_pool.nba_data import get_game_data

router = APIRouter()


@router.get("/{pool_id}/leaderboard", response_class=Response)
def leaderboard(request: Request, pool_id: str):
    leaderboard_df = generate_leaderboard(*get_game_data(pool_id))
    if request.headers.get("accept") == "text/html":
        return HTMLResponse(leaderboard_df.to_html())

    return JSONResponse(leaderboard_df.to_dict(orient="records"))


@router.get("/{pool_id}/team_breakdown", response_class=Response)
def team_breakdown(request: Request, pool_id: str):
    team_breakdown_df = generate_team_breakdown(*get_game_data(pool_id))
    if request.headers.get("accept") == "text/html":
        return HTMLResponse(team_breakdown_df.to_html())

    return JSONResponse(team_breakdown_df.to_dict(orient="records"))
