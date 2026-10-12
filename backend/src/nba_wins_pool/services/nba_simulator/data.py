import logging

import numpy as np
import pandas as pd

from nba_wins_pool.services.nba_data_service import NbaDataService, shown_win_probability
from nba_wins_pool.services.nba_simulator.core.constants import PLAYOFF_HOME_COURT_ADVANTAGE_POINTS
from nba_wins_pool.services.nba_simulator.core.game_probability import live_home_win_probability, remaining_fraction
from nba_wins_pool.services.nba_simulator.core.play_in_tournament import ConferencePlayInResults
from nba_wins_pool.services.nba_simulator.core.playoff_sim import KnownSeriesResult, PlayoffBracketState
from nba_wins_pool.services.nba_simulator.core.schedule import with_cup_rounds
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.nba_game_type import NBAGameType
from nba_wins_pool.utils.safe_cast import safe_int

# Maps bracket matchupType -> ConferencePlayInResults field prefix (a/b/c)
_PLAY_IN_MATCHUP_GAME: dict[str, str] = {
    "Play-In 7v8": "a",
    "Play-In 9v10": "b",
    "Play-In WvL": "c",
}

logger = logging.getLogger(__name__)


def get_nba_schedule(service: NbaDataService) -> pd.DataFrame:
    """Fetch the full current-season NBA schedule with FanDuel moneyline odds merged in.

    Fetches the CDN schedule (which already includes today's CDN moneyline odds) then
    overlays odds from the FanDuel sportsbook API, which covers a broader set of upcoming
    games (including play-in and playoff matchups) and updates during live games. These
    are the same odds the games tab shows, hidden under the same rule
    (:func:`shown_win_probability`). Sportsbook odds take priority; CDN odds serve as a
    fallback for games that haven't started.

    In-progress games keep only a live sportsbook probability. Without one (FanDuel
    hides it late in close games), a play-in or playoff game gets one from the score and
    the time left (:func:`.core.game_probability.live_home_win_probability`, with the
    playoff home court as the expected margin: the ratings aren't known here); a
    regular-season game's ``home_win_prob`` stays NaN and :func:`.core.game_probability.game_probabilities`
    does the same with its ratings.

    Args:
        service: ``NbaDataService`` instance used to fetch the schedule and odds.

    Returns:
        DataFrame with one row per game, including date_time, game_id, home_team,
        away_team, status, winning_team, losing_team, home_win_prob, away_win_prob,
        cup_round (:func:`.core.schedule.with_cup_rounds`) and related fields.
    """
    schedule = service.get_schedule_with_odds()
    ingame = schedule["status"] == NBAGameStatus.INGAME
    # CDN odds aren't live, so they don't describe a game in progress
    schedule.loc[ingame, ["home_win_prob", "away_win_prob"]] = np.nan

    odds_map = service.get_sportsbook_game_win_probabilities()
    if odds_map:
        period = schedule["period"] if "period" in schedule else pd.Series(0, index=schedule.index)
        for i in schedule.index[schedule["game_code"].isin(odds_map)]:
            odds = shown_win_probability(odds_map[schedule.at[i, "game_code"]], safe_int(period[i]))
            if odds is not None:
                schedule.at[i, "home_win_prob"] = odds["home"]
                schedule.at[i, "away_win_prob"] = odds["away"]

    _live_postseason_probabilities(schedule)
    return with_cup_rounds(schedule)


def _live_postseason_probabilities(schedule: pd.DataFrame) -> None:
    """Fill unpriced play-in / playoff games in progress from their score, in place."""
    if not {"home_score", "away_score"} <= set(schedule.columns):
        return
    lead = pd.to_numeric(schedule["home_score"], errors="coerce") - pd.to_numeric(
        schedule["away_score"], errors="coerce"
    )
    rows = schedule.index[
        (schedule["status"] == NBAGameStatus.INGAME)
        & schedule["game_type"].isin([NBAGameType.PLAY_IN, NBAGameType.PLAYOFFS])
        & schedule["home_win_prob"].isna()
        & lead.notna()
    ]
    for i in rows:
        remaining = remaining_fraction(
            safe_int(schedule.at[i, "period"]) if "period" in schedule else 0,
            schedule.at[i, "game_clock"] if "game_clock" in schedule else None,
        )
        p = float(live_home_win_probability(lead[i], remaining, PLAYOFF_HOME_COURT_ADVANTAGE_POINTS))
        schedule.at[i, "home_win_prob"] = p
        schedule.at[i, "away_win_prob"] = 1.0 - p


# Season phases in order; the current phase is the earliest one with unfinished games
_PHASE_ORDER = (NBAGameType.REGULAR_SEASON, NBAGameType.PLAY_IN, NBAGameType.PLAYOFFS)


def detect_season_phase(schedule: pd.DataFrame) -> NBAGameType:
    """Determine the current season phase from the schedule.

    The current phase is the earliest one (Regular Season → Play-In → Playoffs)
    with unfinished games, i.e. upcoming or in progress. The schedule lists
    placeholder play-in and playoff games weeks before the regular season ends,
    so the presence of later-phase games doesn't mean that phase has started.

    Args:
        schedule: Full season schedule DataFrame from ``get_nba_schedule()``.

    Returns:
        The current ``NBAGameType`` phase.
    """
    unfinished = schedule[schedule["status"] != NBAGameStatus.FINAL]
    game_types = set(unfinished["game_type"])
    for phase in _PHASE_ORDER:
        if phase in game_types:
            return phase

    # Every game is final (e.g. the season is over): the latest phase played
    all_game_types = set(schedule["game_type"])
    for phase in reversed(_PHASE_ORDER):
        if phase in all_game_types:
            return phase
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
    FanDuel moneyline odds from ``schedule`` for each series' next game: live
    odds when that game is in progress, otherwise the pregame line.

    The bracket is keyed by ``(conference, round_num, high_seed_tricode)``.
    ``high_seed_tricode`` is the tricode of the team listed as ``highSeedTricode``
    in the NBA bracket API — the team with home court advantage in that series.

    Args:
        schedule: Full season schedule DataFrame from ``get_nba_schedule()``.
        service: ``NbaDataService`` instance used to fetch the playoff bracket.

    Returns:
        ``PlayoffBracketState`` with a ``KnownSeriesResult`` for every series that
        has a game played or odds for its next game.  Other unstarted series are
        omitted so the simulator falls back to its probability model for them.
    """
    season_year = service.get_current_season()
    bracket = service.fetch_playoff_bracket(season_year)
    series_list = bracket.get("bracket", {}).get("playoffBracketSeries", [])

    # Build lookup: next_game_id -> home_win_prob for unfinished (upcoming or live) playoff games
    playoff_unfinished = schedule[
        (schedule["status"] != NBAGameStatus.FINAL) & (schedule["game_type"] == NBAGameType.PLAYOFFS)
    ]
    home_win_prob_by_game_id: dict[str, float] = {}
    for _, row in playoff_unfinished.iterrows():
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
        next_game_id = str(series.get("nextGameId", ""))
        home_win_prob = home_win_prob_by_game_id.get(next_game_id)
        # Skip series that haven't started and have no odds for Game 1
        if high_wins == 0 and low_wins == 0 and home_win_prob is None:
            continue

        round_num = series.get("roundNumber", 0)
        conf_raw = series.get("seriesConference", "")
        conference = _CONF_MAP.get(conf_raw, conf_raw)
        high_tricode = series.get("highSeedTricode", "")
        if not high_tricode or not conference or not round_num:
            continue

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
