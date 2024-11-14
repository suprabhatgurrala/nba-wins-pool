from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

from nba_wins_pool.nba_data import generate_leaderboard

app = FastAPI()

if os.getenv("SERVE_STATIC_FILES") == "true":
    app.mount("/", StaticFiles(directory="static", html=True), name="static")   

@app.get("/leaderboard", response_class=HTMLResponse)
def root():
    leaderboard_df = generate_leaderboard()
    return leaderboard_df.to_html()
