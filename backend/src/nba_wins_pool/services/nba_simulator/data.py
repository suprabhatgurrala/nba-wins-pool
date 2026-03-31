import concurrent.futures
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.types.nba_game_status import NBAGameStatus

ESPN_MAX_WORKERS = 4  # Conservative concurrency to avoid ESPN API rate limiting


def get_espn_schedule(start_date, end_date):
    ESPN_SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
    formatted_start_date = pd.to_datetime(start_date).strftime("%Y%m%d")
    formatted_end_date = pd.to_datetime(end_date).strftime("%Y%m%d")
    params = {"dates": f"{formatted_start_date}-{formatted_end_date}", "limit": 1000}
    response = requests.get(ESPN_SCHEDULE_URL, params=params)
    response.raise_for_status()
    return response.json()


def get_espn_prediction(gameId):
    ESPN_PREDICTOR_URL = "http://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{gameId}/competitions/{gameId}/predictor?lang=en&region=us"
    response = requests.get(ESPN_PREDICTOR_URL.format(gameId=gameId))
    response.raise_for_status()
    return response.json()


def _make_service() -> NbaDataService:
    """Create a minimal NbaDataService with no DB — only use methods that don't touch the DB."""
    return NbaDataService(db_session=None, external_data_repository=None)


def get_nba_schedule() -> pd.DataFrame:
    """Fetch the full current-season NBA schedule.

    Returns:
        DataFrame with one row per game, including date_time, game_id, home_team,
        away_team, status, winning_team, losing_team, and related fields.
        Past/completed games have winning_team/losing_team populated; future games do not.
    """
    return _make_service().get_schedule_with_odds()


def _parse_espn_prediction(pred: dict) -> dict | None:
    """Parse home/away win probabilities from an ESPN predictor response.

    Returns dict with home_win_prob and away_win_prob, or None on failure.
    """
    away_stats = {s["name"]: s["value"] for s in pred.get("awayTeam", {}).get("statistics", [])}
    home_stats = {s["name"]: s["value"] for s in pred.get("homeTeam", {}).get("statistics", [])}

    if "gameProjection" in away_stats:
        away_win_prob = away_stats["gameProjection"] / 100
    elif "gameProjection" in home_stats:
        away_win_prob = 1 - home_stats["gameProjection"] / 100
    else:
        return None

    return {"home_win_prob": 1 - away_win_prob, "away_win_prob": away_win_prob}


def get_espn_bpi_predictions(game_df: pd.DataFrame) -> pd.DataFrame:
    """Build a game probability DataFrame for Monte Carlo simulation.

    Filters to upcoming games with determined opponents, fetches ESPN BPI win probabilities,
    and combines with FanDuel odds (FanDuel takes priority, BPI as fallback).

    Args:
        game_df: NBA schedule DataFrame from get_nba_schedule().

    Returns:
        DataFrame with columns: game_code, home_tricode, away_tricode, home_win_prob.
    """
    espn_to_nba: dict[str, str] = json.loads((Path(__file__).parent / "espn_to_nba_abbrev_map.json").read_text())

    pregame = game_df[(game_df["status"] == NBAGameStatus.PREGAME) & (game_df["game_code"] != "")].copy()
    if pregame.empty:
        return pd.DataFrame(columns=["game_code", "home_tricode", "away_tricode", "home_win_prob"])

    dates = pregame["date_time"].dt.date
    scoreboard = get_espn_schedule(dates.min(), dates.max())

    # Build lookup: game_code (e.g. "20260330/PHIMIA") -> espn_event_id
    # shortName format: "AWAY @ HOME" in ESPN abbreviations; game_code uses NBA tricodes
    event_lookup: dict[str, str] = {}
    for event in scoreboard.get("events", []):
        if event.get("season", {}).get("type") != 2:
            continue
        parts = event.get("shortName", "").split(" @ ")
        if len(parts) != 2:
            continue
        away_espn, home_espn = parts[0].strip(), parts[1].strip()
        away_nba = espn_to_nba.get(away_espn, away_espn)
        home_nba = espn_to_nba.get(home_espn, home_espn)
        event_dt = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
        event_date = pd.Timestamp(event_dt).tz_convert("US/Eastern").strftime("%Y%m%d")
        game_code = f"{event_date}/{away_nba}{home_nba}"
        event_lookup[game_code] = event["id"]

    matched: dict[str, str] = {
        row["game_code"]: event_lookup[row["game_code"]]
        for _, row in pregame.iterrows()
        if row["game_code"] in event_lookup
    }

    bpi_probs: dict[str, float] = {}
    if matched:

        def fetch_prediction(item: tuple[str, str]) -> tuple[str, dict | None]:
            game_code, event_id = item
            try:
                return game_code, get_espn_prediction(event_id)
            except Exception:
                return game_code, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=ESPN_MAX_WORKERS) as executor:
            raw_predictions = list(executor.map(fetch_prediction, matched.items()))

        for game_code, pred in raw_predictions:
            if pred is None:
                continue
            parsed = _parse_espn_prediction(pred)
            if parsed is not None:
                bpi_probs[game_code] = parsed["home_win_prob"]

    pregame["home_win_prob"] = pregame["home_win_prob"].fillna(pregame["game_code"].map(bpi_probs))
    return pregame[["game_id", "game_code", "home_tricode", "away_tricode", "home_win_prob"]].reset_index(drop=True)
