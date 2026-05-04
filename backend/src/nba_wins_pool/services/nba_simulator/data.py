import concurrent.futures
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.services.nba_simulator.play_in_tournament import ConferencePlayInResults
from nba_wins_pool.services.nba_simulator.playoff_sim import KnownSeriesResult, PlayoffBracketState
from nba_wins_pool.services.nba_vegas_projections_service import NBAVegasProjectionsService
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.nba_game_type import NBAGameType

# Maps bracket matchupType -> ConferencePlayInResults field prefix (a/b/c)
_PLAY_IN_MATCHUP_GAME: dict[str, str] = {
    "Play-In 7v8": "a",
    "Play-In 9v10": "b",
    "Play-In WvL": "c",
}

logger = logging.getLogger(__name__)

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


def _make_vegas_service() -> NBAVegasProjectionsService:
    """Create a minimal NBAVegasProjectionsService with no DB — only use methods that don't touch the DB."""
    return NBAVegasProjectionsService(
        db_session=None,
        team_repository=None,
        nba_projections_repository=None,
    )


def get_nba_schedule(service: NbaDataService) -> pd.DataFrame:
    """Fetch the full current-season NBA schedule with FanDuel moneyline odds merged in.

    Fetches the CDN schedule (which already includes today's CDN moneyline odds) then
    overlays odds from the FanDuel sportsbook API, which covers a broader set of upcoming
    games (including play-in and playoff matchups). FanDuel sportsbook odds take priority;
    CDN odds serve as a fallback when the sportsbook has no entry for a game.

    Args:
        service: ``NbaDataService`` instance used to fetch the schedule and CDN odds.

    Returns:
        DataFrame with one row per game, including date_time, game_id, home_team,
        away_team, status, winning_team, losing_team, home_win_prob, away_win_prob,
        and related fields.
    """
    schedule = service.get_schedule_with_odds()

    try:
        fanduel_odds = _make_vegas_service().get_game_win_probabilities()
        if not fanduel_odds.empty:
            odds_idx = fanduel_odds.set_index("gamecode")[["home_win_prob", "away_win_prob"]]
            mask = schedule["game_code"].isin(odds_idx.index)
            for col in ("home_win_prob", "away_win_prob"):
                sportsbook_vals = schedule.loc[mask, "game_code"].map(odds_idx[col])
                # Prefer sportsbook value; fall back to existing (CDN) value when absent.
                schedule.loc[mask, col] = sportsbook_vals.where(sportsbook_vals.notna(), schedule.loc[mask, col])
    except Exception:
        logger.warning("Failed to fetch FanDuel sportsbook moneyline odds; using CDN odds only", exc_info=True)

    return schedule


def detect_season_phase(schedule: pd.DataFrame) -> NBAGameType:
    """Determine the current season phase from the schedule.

    Looks at games that are still in PREGAME status and returns the most
    advanced phase present.  Priority order: Playoffs > Play-In > Regular Season.

    Args:
        schedule: Full season schedule DataFrame from ``get_nba_schedule()``.

    Returns:
        The current ``NBAGameType`` phase.
    """
    pregame = schedule[schedule["status"] == NBAGameStatus.PREGAME]
    if not pregame.empty:
        game_types = set(pregame["game_type"])
        if NBAGameType.PLAY_IN in game_types:
            return NBAGameType.PLAY_IN
        if NBAGameType.PLAYOFFS in game_types:
            return NBAGameType.PLAYOFFS
        return NBAGameType.REGULAR_SEASON

    # Fallback to all games if there are no pregame games (e.g. season is over, or finals are currently ingame)
    all_game_types = set(schedule["game_type"])
    if NBAGameType.PLAYOFFS in all_game_types:
        return NBAGameType.PLAYOFFS
    if NBAGameType.PLAY_IN in all_game_types:
        return NBAGameType.PLAY_IN

    return NBAGameType.REGULAR_SEASON


def get_play_in_results(schedule: pd.DataFrame, service: NbaDataService) -> dict[str, ConferencePlayInResults]:
    """Identify which play-in games have already been played and who won.

    Fetches the official play-in bracket to map each slot (Game A/B/C per
    conference) to its ``game_id``, then cross-references against completed
    play-in games in the schedule to determine known winners.  Unplayed games
    are left as ``None`` so the simulator will sample their outcomes.

    Args:
        schedule: Full season schedule DataFrame from ``get_nba_schedule()``.
        service: ``NbaDataService`` instance used to fetch the play-in bracket.

    Returns:
        Dict mapping ``"East"`` / ``"West"`` to a ``ConferencePlayInResults``
        with winners filled in for completed games and ``None`` for the rest.
    """
    season_year = service.get_current_season()
    bracket = service.fetch_play_in_bracket(season_year)
    series_list = bracket.get("bracket", {}).get("playInBracketSeries", [])

    # Lookup: game_id -> winning tricode, restricted to completed play-in games
    final_play_in = schedule[
        (schedule["status"] == NBAGameStatus.FINAL) & (schedule["game_type"] == NBAGameType.PLAY_IN)
    ]
    winner_by_game_id: dict[str, str] = {}
    for _, row in final_play_in.iterrows():
        game_id = str(row.get("game_id", ""))
        if game_id:
            winner = row["home_tricode"] if row["home_score"] > row["away_score"] else row["away_tricode"]
            winner_by_game_id[game_id] = winner

    # Accumulate known results per conference
    results: dict[str, dict[str, str | None]] = {
        "East": {"game_a_winner": None, "game_b_winner": None, "game_c_winner": None},
        "West": {"game_a_winner": None, "game_b_winner": None, "game_c_winner": None},
    }
    for series in series_list:
        game_key = _PLAY_IN_MATCHUP_GAME.get(series.get("matchupType", ""))
        if game_key is None:
            continue
        conference = series.get("conference")
        if conference not in results:
            continue
        game_id = str(series.get("nextGameId", ""))
        winner = winner_by_game_id.get(game_id)
        if winner:
            results[conference][f"game_{game_key}_winner"] = winner

    return {
        conf: ConferencePlayInResults(
            game_a_winner=data["game_a_winner"],
            game_b_winner=data["game_b_winner"],
            game_c_winner=data["game_c_winner"],
        )
        for conf, data in results.items()
    }


def get_playoff_bracket_state(schedule: pd.DataFrame, service: NbaDataService) -> PlayoffBracketState:
    """Build a ``PlayoffBracketState`` from the official NBA playoff bracket.

    Fetches the bracket JSON (which reports series wins per team) and looks up
    FanDuel moneyline odds from ``schedule`` for the next upcoming game in any
    in-progress series.

    The bracket is keyed by ``(conference, round_num, high_seed_tricode)``.
    ``high_seed_tricode`` is the tricode of the team listed as ``highSeedTricode``
    in the NBA bracket API — the team with home court advantage in that series.

    Args:
        schedule: Full season schedule DataFrame from ``get_nba_schedule()``.
        service: ``NbaDataService`` instance used to fetch the playoff bracket.

    Returns:
        ``PlayoffBracketState`` with a ``KnownSeriesResult`` for every series that
        has at least one game played.  Upcoming (unstarted) series are omitted so
        the simulator falls back to its probability model for those matchups.
    """
    season_year = service.get_current_season()
    bracket = service.fetch_playoff_bracket(season_year)
    series_list = bracket.get("bracket", {}).get("playoffBracketSeries", [])

    # Build lookup: next_game_id -> home_win_prob for upcoming playoff games
    playoff_pregame = schedule[
        (schedule["status"] == NBAGameStatus.PREGAME) & (schedule["game_type"] == NBAGameType.PLAYOFFS)
    ]
    home_win_prob_by_game_id: dict[str, float] = {}
    for _, row in playoff_pregame.iterrows():
        game_id = str(row.get("game_id", ""))
        prob = row.get("home_win_prob")
        if game_id and pd.notna(prob):
            home_win_prob_by_game_id[game_id] = float(prob)

    # Map NBA Finals conference name to canonical form used in PlayoffBracketState
    _CONF_MAP = {"East": "East", "West": "West", "NBA Finals": "Finals"}

    results: dict[tuple[str, int, str], KnownSeriesResult] = {}
    for series in series_list:
        high_wins = series.get("highSeedSeriesWins", 0)
        low_wins = series.get("lowSeedSeriesWins", 0)
        # Skip series that haven't started yet
        if high_wins == 0 and low_wins == 0:
            continue

        round_num = series.get("roundNumber", 0)
        conf_raw = series.get("seriesConference", "")
        conference = _CONF_MAP.get(conf_raw, conf_raw)
        high_tricode = series.get("highSeedTricode", "")
        if not high_tricode or not conference or not round_num:
            continue

        next_game_id = str(series.get("nextGameId", ""))
        home_win_prob = home_win_prob_by_game_id.get(next_game_id)

        results[(conference, round_num, high_tricode)] = KnownSeriesResult(
            higher_seed_wins=int(high_wins),
            lower_seed_wins=int(low_wins),
            next_game_home_win_prob=home_win_prob,
        )

    return PlayoffBracketState(series_results=results)


def get_playoff_bracket_lookups(service: NbaDataService) -> tuple[dict[frozenset, int], dict[str, int]]:
    """Build vig-normalization helpers from the NBA playoff bracket API.

    Returns:
        playoff_round_lookup: maps frozenset([tricode_a, tricode_b]) → round_num (1-4),
            covering every series in the bracket regardless of whether it has started.
        bracket_groups: maps tricode → half-bracket group_id for conf-finals normalization.
            Both teams in a round-1 series share a group_id.  Teams whose series winners
            will meet in the conference semis share a group_id.
            group_id = conference_index * 2 + side, where side 0 = seeds-1/4 half-bracket
            and side 1 = seeds-2/3 half-bracket.

    Returns empty dicts if the bracket is unavailable (e.g. regular season) or on error.
    """
    try:
        season_year = service.get_current_season()
        bracket = service.fetch_playoff_bracket(season_year)
    except Exception:
        logger.warning("Failed to fetch playoff bracket for vig-normalization lookups", exc_info=True)
        return {}, {}

    series_list = bracket.get("bracket", {}).get("playoffBracketSeries", [])
    if not series_list:
        return {}, {}

    _CONF_IDX = {"East": 0, "West": 1}

    playoff_round_lookup: dict[frozenset, int] = {}
    bracket_groups: dict[str, int] = {}

    for series in series_list:
        round_num = series.get("roundNumber", 0)
        high_tricode = series.get("highSeedTricode", "")
        low_tricode = series.get("lowSeedTricode", "")
        if not high_tricode or not low_tricode or not round_num:
            continue

        playoff_round_lookup[frozenset([high_tricode, low_tricode])] = round_num

        if round_num == 1:
            conf = series.get("seriesConference", "")
            high_seed_rank = series.get("highSeedRank", 0)
            # Seeds 1 and 4 share one half-bracket; seeds 2 and 3 share the other.
            side = 0 if high_seed_rank in (1, 4) else 1
            group_id = _CONF_IDX.get(conf, 0) * 2 + side
            bracket_groups[high_tricode] = group_id
            bracket_groups[low_tricode] = group_id

    return playoff_round_lookup, bracket_groups


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
