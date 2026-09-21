"""Empirically-derived adjustment constants for the NBA simulator.

These are market-calibrated numbers pulled from real closing lines rather than
guessed — see the derivation note on each constant for the data source and
method. Nothing in the simulator consumes these yet; they're collected here so
the regular-season and playoff models have a single place to pull from once
they're wired in (see the TODOs in README.md).
"""

# ---------------------------------------------------------------------------
# Home court advantage
# ---------------------------------------------------------------------------
# Derived from DraftKings/ESPN BET closing point spreads (2021-22 through
# 2025-26 seasons, 5 full seasons), via the espn-nba-odds skill. Value is the
# average number of points the market adds to the home team's expected margin.
# True neutral-site games (All-Star, NBA Cup Vegas final, Global Games) are
# excluded. Note: ESPN's neutralSite flag misses the NBA Cup semifinal games
# (also played at a neutral Las Vegas arena) — those ~2 games/season are still
# counted as "home" games here, a small known contamination of the regular
# season figure.

# Regular season + in-season tournament group play, n=6,138 games.
REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS = 2.065

# Play-in + playoffs, n=452 games. Notably larger than the regular-season
# figure across every one of the 5 seasons individually, not just in aggregate.
PLAYOFF_HOME_COURT_ADVANTAGE_POINTS = 3.430

# ---------------------------------------------------------------------------
# Rest days advantage
# ---------------------------------------------------------------------------
# Derived from the same 5-season closing-line dataset, regular season + IST
# group play only (n=6,057 games with a known rest count for both teams).
# Game dates were converted from ESPN's raw UTC timestamp to US/Eastern before
# computing rest -- most NBA tip times are close enough to the UTC midnight
# boundary that using the UTC date directly puts 71% of games on the wrong
# calendar day and corrupts back-to-back detection.
#
# Rest days per team = calendar days since that team's previous game, minus 1
# (so a back-to-back is 0 days of rest), capped at 2 ("2+"). Only three tiers
# are tracked -- equal rest, a 1-day edge, and a 2+-day edge -- since games
# with a rest edge of 3+ are rare enough (well under 1% of the dataset) that
# splitting them out added noise rather than signal. A team's first game of
# the season has no rest value and is excluded.
#
# Fit: home_spread_close = -1.996 + (-1.185 * rest_diff), where rest_diff is
# home team's rest days minus away team's (each side capped at 2, so
# rest_diff ranges -2..+2). Correlation is modest (-0.127, n=6,057) -- rest is
# a real but secondary factor next to team quality and home court.
#
# Raw bucketed deltas (mean home spread, relative to the equal-rest baseline
# of -1.82) are consistent in direction but noisier than the fit:
#   away +2+: n=169   away +1: n=1020
#   equal rest: n=3368 (baseline)
#   home +1: n=1282   home +2+: n=218
REST_DAY_ADVANTAGE_POINTS_PER_DAY = 1.185

# Cap on the rest-day differential (in days) used above -- differentials
# beyond this are folded into the "2+" tier rather than extrapolated further.
REST_DAY_DIFFERENTIAL_CAP = 2


def rest_day_adjustment_points(home_rest_days: int, away_rest_days: int) -> float:
    """Market-implied point adjustment to the home spread from rest alone.

    Positive means the extra rest favors the home team. Both inputs should
    already be capped at REST_DAY_DIFFERENTIAL_CAP by the caller (rest days
    since each team's previous game, back-to-back = 0).
    """
    diff = max(-REST_DAY_DIFFERENTIAL_CAP, min(REST_DAY_DIFFERENTIAL_CAP, home_rest_days - away_rest_days))
    return REST_DAY_ADVANTAGE_POINTS_PER_DAY * diff
