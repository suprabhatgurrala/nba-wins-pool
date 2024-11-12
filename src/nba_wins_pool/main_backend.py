from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from nba_wins_pool.nba_data import generate_leaderboard

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def root():
    leaderboard_df = generate_leaderboard()
    return leaderboard_df.to_html()
