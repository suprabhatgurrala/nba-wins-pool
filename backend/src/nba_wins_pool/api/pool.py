from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from nba_wins_pool.aggregations import generate_leaderboard, generate_team_breakdown, generate_race_plot_data
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

# Add this dictionary with season milestone dates
season_milestones = {
    "2024-25": {
        "all_star_break_start": {
            "date": "2025-02-14",
            "description": "All-Star Break"
        },
        "regular_season_end": {
            "date": "2025-04-13",
            "description": "Regular Season Ends",
        },
        "playoffs_start": {
            "date": "2025-04-19",
            "description": "Playoffs Start",
        },
    }
}

@router.get("/{pool_id}/metadata", response_class=Response)
def overview(request: Request, pool_id: str):
    metadata = team_metadata_by_id.get(pool_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Item not found")

    # Add the current season's milestone dates to the metadata
    metadata["milestones"] = season_milestones.get("2024-25", {})

    return JSONResponse(metadata)


@router.get("/{pool_id}/race_plot", response_class=Response)
def race_plot(request: Request, pool_id: str, sampling_factor: int = Query(1, ge=1)):
    """Generate data for a cumulative wins race plot over time for each owner in the pool."""
    game_data_df, _ = get_game_data(pool_id)
    race_plot_df = generate_race_plot_data(game_data_df, sampling_factor)
    
    if request.headers.get("accept") == "text/html":
        return HTMLResponse(race_plot_df.to_html())
    
    # Convert date to string for JSON serialization
    if not race_plot_df.empty and "date" in race_plot_df.columns:
        race_plot_df["date"] = race_plot_df["date"].astype(str)
    
    return JSONResponse(race_plot_df.to_dict(orient="records"))
