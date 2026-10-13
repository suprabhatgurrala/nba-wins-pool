"""Fit regular-season power ratings to market win totals and projected wins.

FanDuel lists a full-season win total for every team (a line plus over/under
prices) from preseason until about mid-March, and updates it as the season goes.
:func:`fit_ratings_to_win_totals` finds the ratings under which each team's
modeled ``P(final regular-season wins > line)`` matches the market's
over probability. Teams without a current line can instead be given a projected
win total (e.g. ESPN BPI blended with an aging FanDuel line), which the model's
mean final wins is fit to.

Model per team, for a given set of ratings:

- wins so far in games that count in the standings (Cup Championship excluded,
  like the market's line), plus
- every remaining scheduled game: the market moneyline when listed (fixed),
  otherwise :func:`.game_probability.home_win_probability` with home court and rest, plus
- games still missing because the NBA Cup decides them (82 minus scheduled games),
  each against an average opponent on a neutral court.

Final wins are a sum of independent Bernoulli games: Poisson-binomial, mixed over the
team's own rating uncertainty (:meth:`WinTotalModel.win_distribution`). The fit
first matches z-scores under a normal approximation with the exact mean and variance
-- ``(mean - threshold) / sd`` against ``Φ⁻¹(market over prob)``, fast and doesn't
flatten out when a starting rating is far off -- then corrects to the exact
distribution, which is discrete, bounded and skewed near the bounds (the normal
approximation was off by up to 2.8 points of over probability for the best and worst
teams; the exact one matches the Monte Carlo to its noise).
Projected-wins targets use ``(mean - projected) / sd``, on the same scale, so
``scipy.optimize.least_squares`` fits all 30 in milliseconds (no Monte Carlo,
unlike the playoff futures calibration in :mod:`.calibration`).

Teams with neither (pulled from the board, or before the first fetch) are held
at their *prior* rating; a weak pull toward the prior for everyone else also pins
the overall level (only rating differences affect game probabilities).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.special import ndtr, ndtri

from nba_wins_pool.services.nba_simulator.core.constants import SPREAD_TO_WIN_PROB_K
from nba_wins_pool.services.nba_simulator.core.game_probability import unfinished_game_inputs
from nba_wins_pool.services.nba_simulator.core.nba_cup import REGULAR_SEASON_GAMES
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import load_team_metadata
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import (
    completed_standings_games,
    count_wins_from_completed,
)
from nba_wins_pool.services.nba_simulator.core.schedule import GameType, is_cup_championship

logger = logging.getLogger(__name__)

PRIOR_WEIGHT = 1e-3
NO_LINE_PRIOR_WEIGHT = 1.0
_OVER_PROB_CLIP = 1e-3


@dataclass
class WinTotal:
    """A market regular-season win total for one team."""

    line: float
    over_prob: float


@dataclass
class RegularSeasonCalibration:
    """Output of :func:`fit_ratings_to_win_totals`."""

    ratings: dict[str, float]
    n_market_teams: int
    max_abs_error: float
    model_over_prob: dict[str, float]
    n_projected_teams: int = 0
    max_abs_wins_error: float = 0.0


_QUADRATURE_NODES = 16
_EXACT_CORRECTION_ROUNDS = 4
_EXACT_TOLERANCE = 0.001


class WinTotalModel:
    """Each team's final regular-season wins as a function of the ratings.

    Built once from the schedule; :meth:`moments` and :meth:`over_prob` are cheap
    enough to call inside an optimizer.

    With *rating_sd* (see :mod:`.rating_uncertainty`), each team's rating is
    uncertain: ``r + N(0, sd²)``, sampled once per season, as in the simulation. That
    shrinks ratings-based game probabilities slightly toward 50% (probit
    approximation of the averaged sigmoid) and correlates a team's games, widening
    its win distribution by ``Σⱼ sdⱼ² (∂wins/∂rⱼ)²`` (delta method).
    """

    def __init__(
        self,
        schedule: pd.DataFrame,
        team_meta: dict[str, dict[str, str]] | None = None,
        rating_sd: dict[str, float] | None = None,
    ):
        self.teams = sorted(team_meta or load_team_metadata())
        self.idx = {t: i for i, t in enumerate(self.teams)}
        self.rating_var = np.array([(rating_sd or {}).get(t, 0.0) ** 2 for t in self.teams], dtype=np.float64)

        games = unfinished_game_inputs(schedule)
        games = games[games["home_tricode"].isin(self.idx) & games["away_tricode"].isin(self.idx)]
        self._home = games["home_tricode"].map(self.idx).to_numpy(dtype=int)
        self._away = games["away_tricode"].map(self.idx).to_numpy(dtype=int)
        self._adjustment = games["adjustment"].to_numpy(dtype=np.float64)
        self._market_prob = games["market_prob"].to_numpy(dtype=np.float64)

        wins_so_far = count_wins_from_completed(completed_standings_games(schedule))
        self._base_wins = np.array([wins_so_far.get(t, 0.0) for t in self.teams], dtype=np.float64)

        has_teams = schedule["home_tricode"].fillna("").astype(bool) & schedule["away_tricode"].fillna("").astype(bool)
        scheduled = schedule[
            has_teams & (schedule["game_type"] == GameType.REGULAR_SEASON) & ~is_cup_championship(schedule)
        ]
        counts = pd.concat([scheduled["home_tricode"], scheduled["away_tricode"]]).value_counts()
        self._missing = np.array(
            [max(REGULAR_SEASON_GAMES - counts.get(t, 0), 0) for t in self.teams], dtype=np.float64
        )

        n = len(self.teams)
        slots: list[list[tuple[int, bool]]] = [[] for _ in range(n)]
        for g, (h, a) in enumerate(zip(self._home, self._away)):
            slots[h].append((g, True))
            slots[a].append((g, False))
        width = max((len(sl) + int(self._missing[i]) for i, sl in enumerate(slots)), default=0)
        self._slot_game = np.full((n, width), -1, dtype=int)
        self._slot_home = np.zeros((n, width), dtype=bool)
        self._slot_cup = np.zeros((n, width), dtype=bool)
        for i, sl in enumerate(slots):
            for k, (g, home) in enumerate(sl):
                self._slot_game[i, k], self._slot_home[i, k] = g, home
            self._slot_cup[i, len(sl) : len(sl) + int(self._missing[i])] = True

    def ratings_array(self, ratings: dict[str, float]) -> np.ndarray:
        return np.array([ratings.get(t, 0.0) for t in self.teams], dtype=np.float64)

    def _games(self, r: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Per game: home win prob, its rating sensitivity, and the rating-margin variance.

        Plus the same for each team's Cup-dependent games (vs an average opponent, neutral).
        """
        v = self.rating_var[self._home] + self.rating_var[self._away]
        shrink = 1.0 / np.sqrt(1.0 + np.pi * SPREAD_TO_WIN_PROB_K**2 * v / 8.0)
        rating_prob = 1.0 / (
            1.0 + np.exp(-SPREAD_TO_WIN_PROB_K * shrink * (r[self._home] - r[self._away] + self._adjustment))
        )
        market = ~np.isnan(self._market_prob)
        p_home = np.where(market, self._market_prob, rating_prob)
        slope = np.where(market, 0.0, SPREAD_TO_WIN_PROB_K * shrink * p_home * (1.0 - p_home))

        v_missing = self.rating_var + self.rating_var.mean()
        shrink_m = 1.0 / np.sqrt(1.0 + np.pi * SPREAD_TO_WIN_PROB_K**2 * v_missing / 8.0)
        p_missing = 1.0 / (1.0 + np.exp(-SPREAD_TO_WIN_PROB_K * shrink_m * (r - r.mean())))
        slope_missing = SPREAD_TO_WIN_PROB_K * shrink_m * p_missing * (1.0 - p_missing) * self._missing
        return p_home, slope, v, p_missing, slope_missing

    def sensitivities(self, r: np.ndarray) -> np.ndarray:
        """``J[i, j] = ∂(mean final wins of team i) / ∂r_j``, shape ``(n_teams, n_teams)``."""
        n = len(r)
        _, slope, _, _, slope_missing = self._games(r)
        jac = np.zeros((n, n))
        own = np.bincount(self._home, slope, n) + np.bincount(self._away, slope, n) + slope_missing
        jac[np.arange(n), np.arange(n)] = own
        np.add.at(jac, (self._home, self._away), -slope)
        np.add.at(jac, (self._away, self._home), -slope)
        return jac

    def moments(self, r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Mean and variance of each team's final wins under ratings array *r*."""
        n = len(r)
        p_home, slope, v, p_missing, slope_missing = self._games(r)
        q = p_home * (1.0 - p_home)
        mean = self._base_wins + np.bincount(self._home, p_home, n) + np.bincount(self._away, 1.0 - p_home, n)
        var = np.bincount(self._home, q, n) + np.bincount(self._away, q, n)
        mean = mean + self._missing * p_missing
        var = var + self._missing * p_missing * (1.0 - p_missing)
        if self.rating_var.any():
            var = var + (self.sensitivities(r) ** 2) @ self.rating_var
            per_game = slope**2 * v
            var = var - np.bincount(self._home, per_game, n) - np.bincount(self._away, per_game, n)
            per_missing = slope_missing**2 / np.maximum(self._missing, 1.0) * (self.rating_var + self.rating_var.mean())
            var = var - per_missing
        return mean, np.maximum(var, 0.0)

    def over_z(self, r: np.ndarray, team_idx: np.ndarray, lines: np.ndarray) -> np.ndarray:
        """z-score of ``P(final wins > line)`` for the given teams (``over_prob = Φ(z)``)."""
        mean, var = self.moments(r)
        threshold = np.floor(lines) + 0.5
        sd = np.sqrt(var[team_idx])
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(sd > 0, (mean[team_idx] - threshold) / sd, np.sign(mean[team_idx] - threshold) * np.inf)

    def over_prob(self, r: np.ndarray, team_idx: np.ndarray, lines: np.ndarray) -> np.ndarray:
        """Normal-approximation ``P(final wins > line)`` for the given teams."""
        return ndtr(self.over_z(r, team_idx, lines))

    def win_distribution(self, r: np.ndarray, team_idx: np.ndarray) -> np.ndarray:
        """Exact distribution of each team's remaining wins, ``(len(team_idx), width + 1)``.

        Given the ratings, a team's remaining wins are a sum of independent games with
        different probabilities: Poisson-binomial, so discrete, bounded and skewed near
        the bounds (the normal approximation isn't). With rating uncertainty, the team's
        own offset is shared by all its games, so the distribution is the mixture over it,
        integrated by Gauss-Hermite quadrature (:data:`_QUADRATURE_NODES`). Opponents'
        uncertainty shrinks each game's probability as in :meth:`moments` (their games
        against this team are a few each, so their correlation is left out).
        """
        team_idx = np.asarray(team_idx, dtype=int)
        tau = np.sqrt(self.rating_var[team_idx])
        nodes, node_w = np.polynomial.hermite_e.hermegauss(_QUADRATURE_NODES)
        node_w = node_w / node_w.sum()

        game = self._slot_game[team_idx]
        home = self._slot_home[team_idx]
        cup = self._slot_cup[team_idx]
        g = np.where(game >= 0, game, 0)
        own = team_idx[:, None]
        opp = np.where(home, self._away[g], self._home[g])
        margin = np.where(home, 1.0, -1.0) * (r[self._home[g]] - r[self._away[g]] + self._adjustment[g])
        opp_var = self.rating_var[opp]
        market_p = np.where(home, self._market_prob[g], 1.0 - self._market_prob[g])
        margin = np.where(cup, r[own] - r.mean(), margin)
        opp_var = np.where(cup, self.rating_var.mean(), opp_var)
        is_market = (game >= 0) & ~np.isnan(market_p)
        played = (game >= 0) | cup

        shrink = 1.0 / np.sqrt(1.0 + np.pi * SPREAD_TO_WIN_PROB_K**2 * opp_var / 8.0)
        x = margin[:, None, :] + tau[:, None, None] * nodes[None, :, None]
        p = 1.0 / (1.0 + np.exp(-SPREAD_TO_WIN_PROB_K * shrink[:, None, :] * x))
        p = np.where(is_market[:, None, :], np.nan_to_num(market_p)[:, None, :], p)
        p = np.where(played[:, None, :], p, 0.0)

        pmf = np.zeros(p.shape[:2] + (p.shape[2] + 1,))
        pmf[..., 0] = 1.0
        for k in range(p.shape[2]):
            pk = p[..., k : k + 1]
            pmf[..., 1:] = pmf[..., 1:] * (1.0 - pk) + pmf[..., :-1] * pk
            pmf[..., :1] *= 1.0 - pk
        return np.einsum("tnw,n->tw", pmf, node_w)

    def over_prob_exact(self, r: np.ndarray, team_idx: np.ndarray, lines: np.ndarray) -> np.ndarray:
        """``P(final wins > line)`` from :meth:`win_distribution` (no normal approximation)."""
        team_idx = np.asarray(team_idx, dtype=int)
        pmf = self.win_distribution(r, team_idx)
        wins = self._base_wins[team_idx][:, None] + np.arange(pmf.shape[1])[None, :]
        return np.where(wins > np.asarray(lines)[:, None], pmf, 0.0).sum(axis=1)


def fit_ratings_to_win_totals(
    schedule: pd.DataFrame,
    win_totals: dict[str, WinTotal],
    prior: dict[str, float] | None = None,
    *,
    projected_wins: dict[str, float] | None = None,
    rating_sd: dict[str, float] | None = None,
    prior_weight: float = PRIOR_WEIGHT,
    team_meta: dict[str, dict[str, str]] | None = None,
) -> RegularSeasonCalibration:
    """Fit power ratings so modeled over probabilities match market win totals.

    Args:
        schedule: Full season schedule (see :mod:`.schedule`), with market
            ``home_win_prob`` for games that have a moneyline.
        win_totals: Tricode → :class:`WinTotal` for teams with a current line.
        prior: Tricode → starting rating (e.g. the last fitted ratings). Teams
            without a target stay at it; missing teams default to 0.
        projected_wins: Tricode → projected final regular-season wins (standings
            games, so no Cup Championship), fit as the model's mean for teams not in
            *win_totals*.
        rating_sd: Tricode → rating uncertainty in points (see :mod:`.rating_uncertainty`),
            the same the simulation samples rating offsets with. Widens modeled win distributions.
        prior_weight: Strength of the pull toward *prior* for teams with a target
            (teams without one use :data:`NO_LINE_PRIOR_WEIGHT`).
        team_meta: Optional tricode → ``{conference, division}``.

    Returns:
        :class:`RegularSeasonCalibration`. With no usable targets, the ratings are
        just *prior*.
    """
    model = WinTotalModel(schedule, team_meta, rating_sd=rating_sd)
    x0 = model.ratings_array(prior or {})
    projected_wins = projected_wins or {}

    _, var0 = model.moments(x0)
    open_teams = [t for t in model.teams if var0[model.idx[t]] > 0]
    market_teams = [t for t in open_teams if t in win_totals]
    projected_teams = [t for t in open_teams if t not in win_totals and t in projected_wins]
    if not market_teams and not projected_teams:
        logger.info("No win totals or projected wins to fit; using prior ratings")
        return RegularSeasonCalibration(dict(zip(model.teams, x0.tolist())), 0, 0.0, {})

    m_idx = np.array([model.idx[t] for t in market_teams], dtype=int)
    lines = np.array([win_totals[t].line for t in market_teams], dtype=np.float64)
    target = np.array([win_totals[t].over_prob for t in market_teams], dtype=np.float64)
    target_z = ndtri(np.clip(target, _OVER_PROB_CLIP, 1 - _OVER_PROB_CLIP))
    p_idx = np.array([model.idx[t] for t in projected_teams], dtype=int)
    target_wins = np.array([projected_wins[t] for t in projected_teams], dtype=np.float64)

    weights = np.full(len(model.teams), NO_LINE_PRIOR_WEIGHT)
    weights[m_idx] = prior_weight
    weights[p_idx] = prior_weight
    sqrt_w = np.sqrt(weights)

    def solve(goal_z: np.ndarray, start: np.ndarray):
        def residuals(r: np.ndarray) -> np.ndarray:
            mean, var = model.moments(r)
            projected_z = (mean[p_idx] - target_wins) / np.sqrt(var[p_idx])
            return np.concatenate([model.over_z(r, m_idx, lines) - goal_z, projected_z, sqrt_w * (r - x0)])

        return least_squares(residuals, start, method="trf")

    result = solve(target_z, x0)
    n_evals = result.nfev
    for _ in range(_EXACT_CORRECTION_ROUNDS):
        if not len(m_idx):
            break
        exact = model.over_prob_exact(result.x, m_idx, lines)
        if np.abs(exact - target).max() < _EXACT_TOLERANCE:
            break
        offset = ndtri(np.clip(exact, _OVER_PROB_CLIP, 1 - _OVER_PROB_CLIP)) - model.over_z(result.x, m_idx, lines)
        result = solve(target_z - offset, result.x)
        n_evals += result.nfev
    fitted = model.over_prob_exact(result.x, m_idx, lines) if len(m_idx) else np.array([])
    errors = np.abs(fitted - target)
    wins_errors = np.abs(model.moments(result.x)[0][p_idx] - target_wins)
    max_error = float(errors.max()) if len(errors) else 0.0
    max_wins_error = float(wins_errors.max()) if len(wins_errors) else 0.0
    logger.info(
        "Win-total calibration: %d teams with lines (max |model - market| over prob %.4f), "
        "%d with projected wins (max |model - projected| %.2f wins), %d evals",
        len(market_teams),
        max_error,
        len(projected_teams),
        max_wins_error,
        n_evals,
    )
    return RegularSeasonCalibration(
        ratings=dict(zip(model.teams, result.x.tolist())),
        n_market_teams=len(market_teams),
        max_abs_error=max_error,
        model_over_prob=dict(zip(market_teams, fitted.tolist())),
        n_projected_teams=len(projected_teams),
        max_abs_wins_error=max_wins_error,
    )
