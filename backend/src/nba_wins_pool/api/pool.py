from fastapi import APIRouter, HTTPException
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


team_metadata_by_id = {
    "sg": {
        "name": "West Coast Boys",
        "description": "I thought you meant weast",
        "rules": "1st: 50%, 2nd: 15%, 1st All-Star: 20%, 2nd All-Star: 10%, IST: 5%",
    },
    "kk": {
        "name": "Kalhan Kup",
        "description": "Some scrubs who know Kartik",
        "rules": "Don't suck",
    },
}


@router.get("/{pool_id}/metadata", response_class=Response)
def overview(request: Request, pool_id: str):
    metadata = team_metadata_by_id.get(pool_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Item not found")

    return JSONResponse(metadata)
