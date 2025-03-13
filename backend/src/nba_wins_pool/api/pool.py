from fastapi import APIRouter, HTTPException
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from nba_wins_pool.aggregations import generate_leaderboard
from nba_wins_pool.nba_data import get_game_data, team_owner_cache

router = APIRouter()


@router.get("/{pool_slug}/leaderboard", response_class=Response)
def leaderboard(request: Request, pool_slug: str):
    owner_df, team_df = generate_leaderboard(pool_slug, *get_game_data(pool_slug))
    return JSONResponse({"owner": owner_df.to_dict(orient="records"), "team": team_df.to_dict(orient="records")})


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


@router.get("/{pool_slug}/metadata", response_class=Response)
def overview(request: Request, pool_slug: str):
    metadata = team_metadata_by_id.get(pool_slug)
    if not metadata:
        raise HTTPException(status_code=404, detail="Item not found")

    return JSONResponse(metadata)
