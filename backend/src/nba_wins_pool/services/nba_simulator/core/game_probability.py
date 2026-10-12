"""Game win probabilities from power ratings, home court and rest.

Every rating-based probability in the simulator goes through
:func:`home_win_probability`::

    P(home win) = 1 / (1 + exp(-k * (r_home - r_away + home_court + rest_adjustment)))

- ``k`` (:data:`~.constants.SPREAD_TO_WIN_PROB_K`) is the market's spread-to-moneyline
  slope, fitted to 2021-22 through 2025-26 closing lines.
- ``home_court`` is :data:`~.constants.REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS`
  in the regular season (NBA Cup included), :data:`~.constants.PLAYOFF_HOME_COURT_ADVANTAGE_POINTS`
  in the play-in and playoffs, and 0 at neutral sites.
- ``rest_adjustment`` is :func:`~.constants.rest_day_adjustment_points`. When a
  team's rest isn't known (its first game, or any game without a known date and
  opponent), the team is assumed rested (2+ days). Simulated play-in / playoff
  games and unscheduled Cup games therefore have equal rest and no adjustment.

Market probabilities (e.g. FanDuel moneylines) already price home court and rest,
so :func:`game_probabilities` uses them as-is and only falls back to ratings. For a
game in progress the market probability is the live one, so it also prices the score.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nba_wins_pool.services.nba_simulator.core.constants import (
    REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS,
    REST_DAY_ADVANTAGE_POINTS_PER_DAY,
    REST_DAY_DIFFERENTIAL_CAP,
    SPREAD_TO_WIN_PROB_K,
)
from nba_wins_pool.services.nba_simulator.core.schedule import GameStatus, GameType, is_cup_championship

_PERIOD_SECONDS = 720.0
_OVERTIME_SECONDS = 300.0
_MIN_REMAINING = 1.0 / 2880.0


def remaining_fraction(period: int | float | None, game_clock: str | None) -> float:
    """Fraction of a 48-minute game left, from the live period and clock (``"PT05M23.00S"``).

    An unreadable clock (``"--:--"`` between periods) counts as half the period left.
    Overtime counts its own 5 minutes.
    """
    period = int(period or 0)
    if period <= 0:
        return 1.0
    length = _PERIOD_SECONDS if period <= 4 else _OVERTIME_SECONDS
    try:
        left = min(pd.Timedelta(str(game_clock)).total_seconds(), length)
    except ValueError:
        left = length / 2
    after = max(4 - period, 0) * _PERIOD_SECONDS
    return (after + left) / (4 * _PERIOD_SECONDS)


def live_home_win_probability(
    lead: np.ndarray | float,
    remaining: np.ndarray | float,
    expected_margin: np.ndarray | float = 0.0,
) -> np.ndarray:
    """Home team's chance in a game in progress, from the score and the time left.

    The rest of the game is the win model scaled to the time left: its expected margin is
    *expected_margin* (the pregame one, ratings + home court + rest) × *remaining*, and its
    logistic spread shrinks with √remaining (independent possessions), so the final margin
    is centered on ``lead + expected_margin × remaining`` with scale ``√remaining / k``, as
    the NBA Cup's live margins (:func:`.nba_cup.margins_from_uniforms`). At the start
    (remaining 1, lead 0) this is the pregame probability.

    Args:
        lead: Home score minus away score.
        remaining: Fraction of 48 minutes left (:func:`remaining_fraction`).
        expected_margin: Pregame expected home margin in points.
    """
    remaining = np.maximum(np.asarray(remaining, dtype=float), _MIN_REMAINING)
    center = np.asarray(lead, dtype=float) + np.asarray(expected_margin, dtype=float) * remaining
    return 1.0 / (1.0 + np.exp(-SPREAD_TO_WIN_PROB_K * center / np.sqrt(remaining)))


@dataclass
class RatingOffsets:
    """Per-simulation rating offsets: a team's rating in simulation ``s`` is ``rating + offsets[i, s]``.

    Sampled once per simulation and shared by every game that simulation plays (regular
    season, NBA Cup, play-in, playoffs), so a team that's better than its rating in one
    simulation is better all season. See :mod:`.rating_uncertainty` for the sizes.
    """

    tricodes: list[str]
    offsets: np.ndarray

    @classmethod
    def sample(cls, rating_sd: dict[str, float], n_sims: int, rng: np.random.Generator) -> RatingOffsets:
        tricodes = sorted(rating_sd)
        sd = np.array([rating_sd[t] for t in tricodes], dtype=np.float32)
        return cls(tricodes, rng.standard_normal((len(tricodes), n_sims), dtype=np.float32) * sd[:, None])

    def for_tricodes(self, tricodes) -> np.ndarray:
        """Offsets ``(len(tricodes), n_sims)`` in the given order; zeros for unknown teams."""
        idx = {t: i for i, t in enumerate(self.tricodes)}
        out = np.zeros((len(tricodes), self.offsets.shape[1]), dtype=np.float32)
        for row, t in enumerate(tricodes):
            if t in idx:
                out[row] = self.offsets[idx[t]]
        return out


def per_sim_ratings(ratings: np.ndarray, tricodes, rating_offsets: RatingOffsets | None) -> np.ndarray:
    """*ratings* ``(n_teams,)`` ordered like *tricodes*, plus per-simulation offsets when given."""
    if rating_offsets is None:
        return ratings
    return ratings[:, None] + rating_offsets.for_tricodes(tricodes)


def per_sim_home_prob(game_df: pd.DataFrame, rows: np.ndarray, rating_offsets: RatingOffsets) -> np.ndarray:
    """``(len(rows), n_sims)`` home win probabilities for ratings-based *game_df* rows under *rating_offsets*.

    Uses :func:`game_probabilities`' ``rating_margin`` (NaN for market-priced rows).
    """
    margin = game_df["rating_margin"].to_numpy(dtype=np.float32)[rows]
    off = rating_offsets.for_tricodes(game_df["home_tricode"].iloc[rows]) - rating_offsets.for_tricodes(
        game_df["away_tricode"].iloc[rows]
    )
    return 1.0 / (1.0 + np.exp(-SPREAD_TO_WIN_PROB_K * (margin[:, None] + off)))


def ratings_for(ratings: np.ndarray, teams: np.ndarray) -> np.ndarray:
    """Rating of each simulation's team in *teams* (``(n_sims,)`` team indices).

    *ratings* is either ``(n_teams,)`` (the same in every simulation) or
    ``(n_teams, n_sims)`` (offset per simulation, see :mod:`.rating_uncertainty`).
    """
    if ratings.ndim == 1:
        return ratings[teams]
    return ratings[teams, np.arange(len(teams))]


def home_win_probability(
    home_rating: np.ndarray | float,
    away_rating: np.ndarray | float,
    *,
    home_court: np.ndarray | float = REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS,
    rest_adjustment: np.ndarray | float = 0.0,
) -> np.ndarray:
    """Probability the home team wins, from ratings in points (pass ``home_court=0`` for neutral sites)."""
    margin = np.asarray(home_rating) - np.asarray(away_rating) + home_court + np.asarray(rest_adjustment)
    return 1.0 / (1.0 + np.exp(-SPREAD_TO_WIN_PROB_K * margin))


def rest_days(schedule: pd.DataFrame) -> pd.DataFrame:
    """Days of rest for each team before each game, indexed like *schedule*.

    Rest = calendar days (US/Eastern) since the team's previous game minus 1, so a
    back-to-back is 0, capped at :data:`~.constants.REST_DAY_DIFFERENTIAL_CAP`.
    A team's first game, and rows without both teams set, get NaN.

    Returns:
        DataFrame with ``home_rest`` and ``away_rest`` columns.
    """
    out = pd.DataFrame({"home_rest": np.nan, "away_rest": np.nan}, index=schedule.index)
    has_teams = schedule["home_tricode"].fillna("").astype(bool) & schedule["away_tricode"].fillna("").astype(bool)
    games = schedule[has_teams]
    if games.empty:
        return out

    game_time = pd.to_datetime(games["date_time"])
    if game_time.dt.tz is not None:
        game_time = game_time.dt.tz_convert("US/Eastern")
    game_date = game_time.dt.normalize()

    appearances = pd.concat(
        [
            pd.DataFrame({"row": games.index, "team": games["home_tricode"], "date": game_date, "side": "home_rest"}),
            pd.DataFrame({"row": games.index, "team": games["away_tricode"], "date": game_date, "side": "away_rest"}),
        ]
    ).sort_values(["team", "date"], kind="stable")
    previous = appearances.groupby("team")["date"].shift()
    rest = ((appearances["date"] - previous).dt.days - 1).clip(lower=0, upper=REST_DAY_DIFFERENTIAL_CAP)
    for side in ("home_rest", "away_rest"):
        mask = (appearances["side"] == side).to_numpy()
        out.loc[appearances["row"].to_numpy()[mask], side] = rest.to_numpy()[mask]
    return out


def home_adjustment(schedule: pd.DataFrame, games: pd.DataFrame) -> np.ndarray:
    """Regular-season home court + rest edge (points) for *games*, rows of *schedule*.

    Same as :func:`.constants.rest_day_adjustment_points`, vectorized. Unknown rest (e.g. a
    team's first game) is assumed rested: the 2+ day cap. Neutral sites get no home court.
    """
    rest = rest_days(schedule).loc[games.index].fillna(REST_DAY_DIFFERENTIAL_CAP)
    rest_diff = (rest["home_rest"] - rest["away_rest"]).clip(-REST_DAY_DIFFERENTIAL_CAP, REST_DAY_DIFFERENTIAL_CAP)
    neutral = games["is_neutral"].fillna(False).astype(bool) if "is_neutral" in games else False
    home_court = np.where(neutral, 0.0, REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS)
    return home_court + (REST_DAY_ADVANTAGE_POINTS_PER_DAY * rest_diff).to_numpy()


def unfinished_game_inputs(schedule: pd.DataFrame) -> pd.DataFrame:
    """Rating-independent inputs for every unfinished regular-season game with both teams set.

    Unfinished means upcoming or in progress. The NBA Cup Championship is excluded
    (it's simulated with the Cup).

    Returns:
        DataFrame with ``game_id``, ``game_code``, ``home_tricode``, ``away_tricode``,
        ``adjustment`` (home court + rest, in points, added to ``r_home - r_away``),
        ``market_prob`` (the schedule's ``home_win_prob``, NaN when absent), and for games in
        progress ``live_lead`` (home minus away score) and ``remaining`` (fraction of the
        game left, :func:`remaining_fraction`); NaN for games not started.
    """
    columns = [
        "game_id",
        "game_code",
        "home_tricode",
        "away_tricode",
        "adjustment",
        "market_prob",
        "live_lead",
        "remaining",
    ]
    upcoming = (
        (schedule["status"] != GameStatus.FINAL)
        & (schedule["game_type"] == GameType.REGULAR_SEASON)
        & schedule["game_code"].fillna("").astype(bool)
        & ~is_cup_championship(schedule)
    )
    games = schedule[upcoming]
    if games.empty:
        return pd.DataFrame(columns=columns)

    out = games[["game_id", "game_code", "home_tricode", "away_tricode"]].copy()
    out["adjustment"] = home_adjustment(schedule, games)
    out["market_prob"] = pd.to_numeric(games["home_win_prob"], errors="coerce") if "home_win_prob" in games else np.nan
    live = games["status"] == GameStatus.INGAME
    if {"home_score", "away_score"} <= set(games.columns):
        lead = pd.to_numeric(games["home_score"], errors="coerce") - pd.to_numeric(games["away_score"], errors="coerce")
        live &= lead.notna()
    else:
        lead = pd.Series(np.nan, index=games.index)
    out["live_lead"] = lead.where(live)
    period = games["period"] if "period" in games else pd.Series(0, index=games.index)
    clock = games["game_clock"] if "game_clock" in games else pd.Series(None, index=games.index)
    out["remaining"] = [
        remaining_fraction(int(p) if pd.notna(p) else 0, c) if is_live else np.nan
        for p, c, is_live in zip(pd.to_numeric(period, errors="coerce"), clock, live)
    ]
    return out.reset_index(drop=True)


def game_probabilities(schedule: pd.DataFrame, ratings: dict[str, float]) -> pd.DataFrame:
    """Home-win probability for every unfinished regular-season game with both teams set.

    Uses the schedule's market ``home_win_prob`` (e.g. FanDuel, live for games in
    progress) when present. A game in progress without one (the price is hidden late in
    close games) uses the live score (:func:`live_home_win_probability`); otherwise
    ratings + home court (0 at neutral sites) + rest, with unknown rest treated as rested. The NBA Cup Championship is excluded (it's simulated with
    the Cup).

    Args:
        schedule: Full season schedule (see :mod:`.schedule`). Uses ``date_time``,
            ``is_neutral`` and ``home_win_prob`` when present.
        ratings: Tricode → power rating in points. Teams missing from it count as 0.

    Returns:
        ``game_df`` for :func:`~.regular_season_sim.run_regular_season_simulation`, with
        ``game_id``, ``game_code``, ``home_tricode``, ``away_tricode``, ``home_win_prob``,
        ``prob_source`` (``"market"``, ``"live"`` or ``"ratings"``) and ``rating_margin``
        (expected home margin in points, ``r_home - r_away`` + home court + rest; NaN for
        market and live games),
        which the simulation uses to redo ratings-based probabilities when ratings are
        offset per simulation.
    """
    games = unfinished_game_inputs(schedule)
    if games.empty:
        return pd.DataFrame(
            columns=[
                "game_id",
                "game_code",
                "home_tricode",
                "away_tricode",
                "home_win_prob",
                "prob_source",
                "rating_margin",
            ]
        )
    if not ratings:
        raise ValueError("Power ratings are required to compute game probabilities.")

    rating_margin = (
        games["home_tricode"].map(ratings).fillna(0.0).to_numpy(dtype=float)
        - games["away_tricode"].map(ratings).fillna(0.0).to_numpy(dtype=float)
        + games["adjustment"].to_numpy(dtype=float)
    )
    rating_prob = home_win_probability(rating_margin, 0.0, home_court=0.0)
    live = games["market_prob"].isna() & games["live_lead"].notna()
    live_prob = live_home_win_probability(games["live_lead"].fillna(0.0), games["remaining"].fillna(1.0), rating_margin)
    rating_prob = np.where(live, live_prob, rating_prob)
    market = games["market_prob"]
    out = games[["game_id", "game_code", "home_tricode", "away_tricode"]].copy()
    out["home_win_prob"] = market.where(market.notna(), rating_prob)
    out["prob_source"] = np.where(market.notna(), "market", np.where(live, "live", "ratings"))
    out["rating_margin"] = np.where(market.notna() | live, np.nan, rating_margin)
    return out
