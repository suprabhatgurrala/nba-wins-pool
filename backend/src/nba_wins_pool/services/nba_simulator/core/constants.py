"""Empirically-derived adjustment constants for the NBA simulator.

These are market-calibrated numbers pulled from real closing lines rather than
guessed — see the derivation note on each constant for the data source and
method. :mod:`.game_probability` applies them to every rating-based game
probability (regular season, NBA Cup, play-in and playoffs).
"""

# ---------------------------------------------------------------------------
# Spread -> win probability
# ---------------------------------------------------------------------------
# Slope of the logistic curve the market uses to turn a point spread into a
# moneyline: P(home win) = 1 / (1 + exp(SPREAD_TO_WIN_PROB_K * home_spread)),
# i.e. 1 / (1 + exp(-k * expected home margin)). Fitted by least squares on
# probabilities to DraftKings/ESPN BET closing lines, 2021-22 through 2025-26
# (all season types), via the espn-nba-odds skill: n=6,605 games with a closing
# spread and both moneylines, vig removed by Shin's method like every price in the
# app (utils/odds.shin_devig; median overround 4.2%);
# 20 games whose spread and moneyline favored different teams were dropped.
# RMSE 0.020 in probability. By season: 0.1359, 0.1328, 0.1338, 0.1340, 0.1294
# (flattening slightly); regular season 0.1332, play-in + playoffs 0.1320.
# Proportional de-vigging gave 0.12641: Shin gives favorites more of each price.
#
# Known shape error, inherent to a curve through 50% at a pick'em: games can't
# end tied, so a 1-point favorite wins whenever it covers *or* wins by exactly 1,
# and the market prices small favorites lower than any such curve. The fit runs
# ~2 pp high for spreads under 4 and ~2 pp low for 10+ point favorites.
SPREAD_TO_WIN_PROB_K = 0.13314

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


# ---------------------------------------------------------------------------
# Game margin noise
# ---------------------------------------------------------------------------
# Standard deviation of a game's final margin around the closing spread (actual
# home margin + home_spread_close), from ESPN BET closing lines for 2025-26
# (nba_wins_pool_prep/nba_2025_26_spreads.csv): 13.9 points over 1,231
# regular-season games (15.9 over 85 playoff games). Consistent with
# SPREAD_TO_WIN_PROB_K: its logistic margin distribution has sd π/(k√3) ≈ 13.6
# (NBA Cup point differentials are sampled from it, see nba_cup.margins_from_uniforms).
# Used as the per-game information about a team's rating in rating_uncertainty.py.
GAME_MARGIN_SD = 14.0
