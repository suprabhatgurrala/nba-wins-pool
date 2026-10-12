"""How uncertain each team's power rating is, for offsetting ratings once per simulation.

A point rating treats team strength as known, so a team's season win total only
varies with game-by-game luck: a standard deviation of ~4.4 wins over 82 games.
The market's is ~8 preseason (FanDuel's "X+ Regular Season Wins" ladder), because
nobody knows exactly how good a team is. Offsetting each team's rating once per
simulation, ``r + N(0, τ²)``, and using it for every game adds that uncertainty;
it's shared across all of a team's games, which is what widens the season total.

τ comes from the ladder while FanDuel lists it (early in the season only):

1. Fit a normal distribution to each team's ladder (probit regression of
   ``P(wins >= x)`` on ``x``) for the market's spread ``σ_mkt``.
2. Solve ``σ_mkt² = Bernoulli variance + Σⱼ τⱼ² (∂wins/∂rⱼ)²`` for τ, using
   :class:`~.rating_calibration.WinTotalModel` on the schedule as of the ladder.
3. Convert to the preseason equivalent: every game played is a noisy look at the
   rating (``GAME_MARGIN_SD`` points), so ``1/τ² = 1/τ₀² + n_played/GAME_MARGIN_SD²``.

Then τ shrinks by the same rule as games are played, after the ladder is gone.
Without any ladder, τ₀ is :data:`DEFAULT_PRESEASON_RATING_SD`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy.special import ndtri

from nba_wins_pool.services.nba_simulator.core.constants import GAME_MARGIN_SD
from nba_wins_pool.services.nba_simulator.core.game_probability import home_adjustment
from nba_wins_pool.services.nba_simulator.core.rating_calibration import WinTotalModel
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import completed_standings_games
from nba_wins_pool.services.nba_simulator.core.schedule import GameStatus

# Preseason rating uncertainty (points) when no ladder has been seen this season: the
# median τ₀ from the 2026-27 preseason ladder (FanDuel, Sep 15 2026; median σ_mkt 8.1
# wins), fit on the 2025-26 preseason schedule. Range 2.6 (OKC) to 3.8 (SAC).
DEFAULT_PRESEASON_RATING_SD = 3.0
# Cap on τ₀: a ladder wider than this implies is treated as noise
MAX_RATING_SD = 6.0
_PROB_LIMIT = 1e-3
# Ladders fetched within this of the newest count as the same snapshot
_SAME_FETCH = timedelta(hours=1)


@dataclass
class WinLadder:
    """One team's FanDuel "X+ Regular Season Wins" prices."""

    probs: dict[int, float]  # threshold -> P(wins >= threshold)
    as_of: datetime  # when it was fetched (naive UTC, like the schedule's date_time)


def fit_ladder(probs: dict[int, float]) -> tuple[float, float] | None:
    """Mean and standard deviation of a normal fit to ``P(wins >= x)`` points.

    ``P(W >= x) = 1 - Φ((x - 0.5 - μ)/σ)``, so ``Φ⁻¹(1 - p)`` is linear in ``x - 0.5``
    with slope ``1/σ``; ordinary least squares gives both. Near-certain points (outside
    ``[_PROB_LIMIT, 1 - _PROB_LIMIT]``) are dropped: their z-scores are unstable and would
    bend the line. Returns None with fewer than two usable points or a non-decreasing ladder.
    """
    points = [(x, p) for x, p in probs.items() if _PROB_LIMIT <= p <= 1.0 - _PROB_LIMIT]
    if len(points) < 2:
        return None
    x = np.array([pt[0] for pt in points], dtype=np.float64) - 0.5
    z = ndtri(1.0 - np.array([pt[1] for pt in points], dtype=np.float64))
    slope, intercept = np.polyfit(x, z, 1)
    if slope <= 0:
        return None
    sigma = 1.0 / slope
    return -intercept * sigma, sigma


def shrink_rating_sd(preseason_sd: float, games_played: float) -> float:
    """Rating uncertainty after *games_played* games: ``1/τ² = 1/τ₀² + n/GAME_MARGIN_SD²``."""
    if preseason_sd <= 0:
        return 0.0
    return float(1.0 / np.sqrt(1.0 / preseason_sd**2 + games_played / GAME_MARGIN_SD**2))


def preseason_equivalent_sd(rating_sd: float, games_played: float) -> float:
    """Invert :func:`shrink_rating_sd`: the τ₀ that shrinks to *rating_sd* after *games_played*."""
    if rating_sd <= 0:
        return 0.0
    precision = 1.0 / rating_sd**2 - games_played / GAME_MARGIN_SD**2
    return MAX_RATING_SD if precision <= 1.0 / MAX_RATING_SD**2 else float(1.0 / np.sqrt(precision))


def games_played(schedule: pd.DataFrame, before: datetime | None = None) -> dict[str, int]:
    """Standings games each team has finished (tipped off before *before*, when given)."""
    done = completed_standings_games(schedule)
    if before is not None:
        done = done[_naive_utc(done["date_time"]) < pd.Timestamp(before)]
    counts = pd.concat([done["home_tricode"], done["away_tricode"]]).value_counts()
    return {str(t): int(n) for t, n in counts.items()}


def schedule_as_of(schedule: pd.DataFrame, when: datetime) -> pd.DataFrame:
    """The schedule as it stood at *when*: games tipping off later are unplayed and unpriced."""
    out = schedule.copy()
    later = (_naive_utc(out["date_time"]) >= pd.Timestamp(when)).to_numpy()
    out.loc[later, "status"] = GameStatus.PREGAME
    out.loc[later, ["home_score", "away_score"]] = np.nan
    if "home_win_prob" in out:
        out.loc[later, "home_win_prob"] = np.nan
    return out


def _naive_utc(times: pd.Series) -> pd.Series:
    times = pd.to_datetime(times)
    return times.dt.tz_convert("UTC").dt.tz_localize(None) if times.dt.tz is not None else times


def preseason_rating_sd(
    schedule: pd.DataFrame,
    ladders: dict[str, WinLadder],
    ratings: dict[str, float],
    team_meta: dict[str, dict[str, str]] | None = None,
    stored: dict[str, float] | None = None,
) -> dict[str, float]:
    """Preseason-equivalent rating uncertainty τ₀ per team, from the latest ladders.

    Only the newest fetch's ladders are fit, against the schedule as of that fetch. A team
    whose ladder is older (FanDuel dropped it since) or missing keeps its *stored* τ₀ (the
    last simulation's, computed while its ladder was current); failing that, the median of
    the teams fit, or :data:`DEFAULT_PRESEASON_RATING_SD` when none are.
    """
    stored = stored or {}
    fits = {t: fit_ladder(lad.probs) for t, lad in ladders.items()}
    fits = {t: f for t, f in fits.items() if f is not None}
    model = WinTotalModel(schedule, team_meta)
    if not fits:
        return {t: float(stored.get(t, DEFAULT_PRESEASON_RATING_SD)) for t in model.teams}

    # A ladder is a snapshot: comparing an older one with the model as of a later date
    # would read its spread over more games than are left (τ too high), so fit only the
    # latest fetch's
    as_of = max(ladders[t].as_of for t in fits)
    fits = {t: f for t, f in fits.items() if ladders[t].as_of >= as_of - _SAME_FETCH}
    model_schedule = schedule_as_of(schedule, as_of)
    model = WinTotalModel(model_schedule, team_meta)
    r = model.ratings_array(ratings)
    _, var0 = model.moments(r)
    jac2 = model.sensitivities(r) ** 2
    has = np.array([t in fits for t in model.teams])
    market_var = np.array([fits[t][1] ** 2 if t in fits else 0.0 for t in model.teams])
    excess = np.maximum(market_var - var0, 0.0)

    # Solve excess_i = Σⱼ τⱼ² J_ij² for teams with a ladder. Own-rating terms dominate
    # (opponents' are a few percent), so a few Jacobi sweeps converge; teams without a
    # ladder are held at the median of the rest.
    tau2 = np.where(has, excess / np.maximum(np.diag(jac2), 1e-9), 0.0)
    for _ in range(10):
        tau2[~has] = np.median(tau2[has])
        others = jac2 @ tau2 - np.diag(jac2) * tau2
        tau2 = np.where(has, np.maximum(excess - others, 0.0) / np.maximum(np.diag(jac2), 1e-9), tau2)
    tau2[~has] = np.median(tau2[has])

    # The linearized variance overstates what τ adds (it ignores the probability shrink),
    # so rescale each τ² by target / achieved excess variance until they agree.
    for _ in range(4):
        sd = {t: float(np.sqrt(tau2[i])) for i, t in enumerate(model.teams)}
        _, var_tau = WinTotalModel(model_schedule, team_meta, rating_sd=sd).moments(r)
        achieved = var_tau - var0
        scale = np.where(achieved > 1e-9, excess / np.maximum(achieved, 1e-9), 1.0)
        tau2 = np.where(has, tau2 * scale, tau2)
        tau2[~has] = np.median(tau2[has])

    played = games_played(schedule, before=as_of)
    tau0 = np.array(
        [preseason_equivalent_sd(float(np.sqrt(tau2[i])), played.get(t, 0)) for i, t in enumerate(model.teams)]
    )
    tau0[~has] = np.median(tau0[has])
    return {t: float(tau0[i] if has[i] else stored.get(t, tau0[i])) for i, t in enumerate(model.teams)}


def current_rating_sd(schedule: pd.DataFrame, preseason_sd: dict[str, float]) -> dict[str, float]:
    """Each team's rating uncertainty now: *preseason_sd* shrunk by games played so far."""
    played = games_played(schedule)
    return {t: shrink_rating_sd(sd, played.get(t, 0)) for t, sd in preseason_sd.items()}


# ---------------------------------------------------------------------------
# Ratings learning from results (when no market prices a team)
# ---------------------------------------------------------------------------

# Final margins beyond this are mostly garbage time: clipped before they move a rating
RESULT_MARGIN_CAP = 30.0


def results_cutoff(schedule: pd.DataFrame) -> datetime | None:
    """Latest tip-off whose result is settled: just before the earliest game in progress,
    else the last finished standings game. None before any game is final."""
    tip = _naive_utc(schedule["date_time"])
    live = tip[(schedule["status"] == GameStatus.INGAME).to_numpy()]
    if not live.empty:
        return (live.min() - pd.Timedelta(microseconds=1)).to_pydatetime()
    done = completed_standings_games(schedule)
    if done.empty:
        return None
    return _naive_utc(done["date_time"]).max().to_pydatetime()


def update_ratings_from_results(
    schedule: pd.DataFrame,
    ratings: dict[str, float],
    preseason_sd: dict[str, float],
    after: datetime,
    through: datetime,
) -> dict[str, float]:
    """*ratings* updated by each standings game that tipped off in ``(after, through]``.

    The model τ already assumes: a game's margin is ``r_home − r_away`` + home court + rest
    plus noise of :data:`~.constants.GAME_MARGIN_SD`, and each team's rating is uncertain
    by τ (its τ₀ shrunk by the games it had played). In tip-off order, each result moves
    both ratings by their share of the surprise (a Kalman update)::

        e = margin − expected,  S = σ² + τ_home² + τ_away²
        r_home += τ_home² · e / S,  r_away −= τ_away² · e / S

    which shrinks each τ the way :func:`shrink_rating_sd` does. Margins are clipped to
    ±:data:`RESULT_MARGIN_CAP`. Applying each window once (``after`` = the previous run's
    *through*) keeps ratings learning from results when no FanDuel line or ESPN projection
    prices a team; teams the market does price are refit to it on top.
    """
    done = completed_standings_games(schedule)
    tip = _naive_utc(done["date_time"])
    games = done[((tip > pd.Timestamp(after)) & (tip <= pd.Timestamp(through))).to_numpy()]
    games = games.dropna(subset=["home_score", "away_score"])
    if games.empty:
        return dict(ratings)
    games = games.iloc[np.argsort(_naive_utc(games["date_time"]).to_numpy(), kind="stable")]
    adjustment = home_adjustment(schedule, games)
    # Games already played: tipped off at or before *after* (the previous window's end)
    earlier = done[(tip <= pd.Timestamp(after)).to_numpy()]
    count = pd.concat([earlier["home_tricode"], earlier["away_tricode"]]).value_counts().to_dict()
    r = dict(ratings)
    for (home, away, hs, aws), adj in zip(
        games[["home_tricode", "away_tricode", "home_score", "away_score"]].itertuples(index=False), adjustment
    ):
        var_h = shrink_rating_sd(preseason_sd.get(home, DEFAULT_PRESEASON_RATING_SD), count.get(home, 0)) ** 2
        var_a = shrink_rating_sd(preseason_sd.get(away, DEFAULT_PRESEASON_RATING_SD), count.get(away, 0)) ** 2
        margin = float(np.clip(float(hs) - float(aws), -RESULT_MARGIN_CAP, RESULT_MARGIN_CAP))
        surprise = margin - (r.get(home, 0.0) - r.get(away, 0.0) + float(adj))
        total = GAME_MARGIN_SD**2 + var_h + var_a
        r[home] = r.get(home, 0.0) + var_h * surprise / total
        r[away] = r.get(away, 0.0) - var_a * surprise / total
        count[home] = count.get(home, 0) + 1
        count[away] = count.get(away, 0) + 1
    return r
