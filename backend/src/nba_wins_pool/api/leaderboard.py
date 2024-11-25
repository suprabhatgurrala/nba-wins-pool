from fastapi import APIRouter
from fastapi.responses import Response, JSONResponse, HTMLResponse
from fastapi.requests import Request
from nba_wins_pool.nba_data import generate_leaderboard

router = APIRouter()

@router.get("/leaderboard", response_class=Response)
def leaderboard(request: Request):
    leaderboard_df = generate_leaderboard()
    if request.headers.get("accept") == "text/html":
        return HTMLResponse(leaderboard_df.to_html())
    
    return JSONResponse(leaderboard_df.to_dict(orient='records'))
