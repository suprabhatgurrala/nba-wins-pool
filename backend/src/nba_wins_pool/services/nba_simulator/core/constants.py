"""Empirically-derived adjustment constants for the NBA simulator.

Fitted to historical closing lines. :mod:`.game_probability` applies them to every
rating-based game probability (regular season, NBA Cup, play-in and playoffs).

Refit them all with ``backend/calibration/game_constants.py`` (``--write`` updates
this file; its docstring describes each fit).
"""

# Logistic slope turning a point spread into a win probability:
# P(home win) = 1 / (1 + exp(SPREAD_TO_WIN_PROB_K * home_spread)).
# Games can't end tied, so the market prices small favorites lower than any curve
# through 50% at a pick'em: this runs a little high for short spreads and low for big ones.
SPREAD_TO_WIN_PROB_K = 0.13317

# Mean points the closing spread gives the home team at a non-neutral site.
REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS = 2.062
PLAYOFF_HOME_COURT_ADVANTAGE_POINTS = 3.430

# Spread points per day of rest edge (rest days = days since previous game - 1,
# so a back-to-back is 0).
REST_DAY_ADVANTAGE_POINTS_PER_DAY = 1.177
REST_DAY_DIFFERENTIAL_CAP = 2


def rest_day_adjustment_points(home_rest_days: int, away_rest_days: int) -> float:
    """Market-implied point adjustment to the home spread from rest alone.

    Positive means the extra rest favors the home team. Both inputs should
    already be capped at REST_DAY_DIFFERENTIAL_CAP by the caller (rest days
    since each team's previous game, back-to-back = 0).
    """
    diff = max(-REST_DAY_DIFFERENTIAL_CAP, min(REST_DAY_DIFFERENTIAL_CAP, home_rest_days - away_rest_days))
    return REST_DAY_ADVANTAGE_POINTS_PER_DAY * diff


# Standard deviation of a game's final home margin around the closing spread.
GAME_MARGIN_SD = 13.4
