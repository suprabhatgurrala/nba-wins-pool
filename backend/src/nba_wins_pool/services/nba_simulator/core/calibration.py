"""Calibrate playoff power ratings to match FanDuel market odds.

Fits per-team power ratings so the exact playoff bracket (:mod:`.playoff_bracket`)
reproduces FanDuel's implied round, conference and championship probabilities.

Typical usage::

    raw = compute_raw_seedings(...)
    result = calibrate_ratings(fanduel_futures, power_ratings, raw, play_in_results, bracket_state)
    # result.ratings is a tricode -> rating dict ready for simulate_playoffs()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from nba_wins_pool.services.nba_simulator.core.play_in_tournament import (
    ConferencePlayInResults,
    compute_play_in_results,
)
from nba_wins_pool.services.nba_simulator.core.playoff_bracket import Bracket
from nba_wins_pool.services.nba_simulator.core.playoff_sim import PlayoffBracketState

logger = logging.getLogger(__name__)

_DEFAULT_N_SIMS = 100_000
_DEFAULT_SEED = 123
# Residual weight (probability per point) pulling each fit rating toward its start: only
# differences between alive teams are priced, so this just pins the level
_LEVEL_PULL = 1e-4


@dataclass
class CalibrationResult:
    """Output of :func:`calibrate_ratings`.

    Attributes:
        ratings: Optimised power rating per playoff team tricode.  Ready to
            pass as ``ratings`` to :func:`simulate_playoffs` after converting
            to a full-length numpy array.
        loss_start: Sum-of-squared-errors before optimisation.
        loss_final: Sum-of-squared-errors after optimisation.
        n_evals: Total objective evaluations consumed by the optimiser.
        converged: ``True`` when scipy reported successful convergence.
        market_coverage: Number of playoff teams that had FanDuel odds.
    """

    ratings: dict[str, float]
    loss_start: float
    loss_final: float
    n_evals: int
    converged: bool
    market_coverage: int
    loss_history: list[float] = field(default_factory=list)


def calibrate_ratings(
    market: dict,
    power_ratings: dict[str, float],
    raw: dict,
    play_in_results: dict[str, ConferencePlayInResults] | None = None,
    bracket_state: PlayoffBracketState | None = None,
    n_sims: int = _DEFAULT_N_SIMS,
    seed: int = _DEFAULT_SEED,
    initial_ratings: dict[str, float] | None = None,
) -> CalibrationResult:
    """Optimise power ratings so the playoff simulation matches FanDuel odds.

    Callers are responsible for fetching *market* and *power_ratings* (e.g. from
    the database) before calling this function.

    Adjusts per-team power ratings to minimise the sum of squared errors between the
    bracket's championship / conference / round probabilities and FanDuel's. The
    bracket is priced exactly (:class:`.playoff_bracket.Bracket`: no series sampled),
    over the play-in's outcomes drawn once (they use *power_ratings*, not the fit),
    so the objective is smooth and least squares converges in a few dozen evaluations.

    Args:
        market: FanDuel futures dict keyed by tricode, as returned by
            ``NBAProjectionsRepository.get_latest_fanduel_futures()``.
        power_ratings: Tricode → power rating (the last stored ratings, else ESPN
            playoff BPI). Used for the play-in and as the fallback starting point.
        raw: Raw seedings dict returned by ``compute_raw_seedings()``.  Must
            contain ``seeds``, ``total_wins``, ``all_tricodes``, ``team_idx``,
            ``east_teams``, ``west_teams``, ``n_teams``.
        play_in_results: Known play-in game winners from
            ``get_play_in_results()``.  ``None`` entries are simulated.
        bracket_state: Known series results from ``get_playoff_bracket_state()``.
            ``None`` means every series is simulated from scratch.
        n_sims: Play-in draws (default 100 000); collapsed to their distinct outcomes,
            so this only sets how precisely the play-in's odds are weighted.
        seed: Play-in RNG seed.  Fixing this makes the calibration reproducible.
        initial_ratings: Per-team power ratings to use as the optimiser
            starting point (tricode → rating).  When provided, each playoff
            team's initial value is taken from here first, falling back to
            *power_ratings* for any teams not present.  Pass ``None`` (default) to
            start entirely from *power_ratings*.

    Returns:
        :class:`CalibrationResult` with optimised ratings and diagnostics.
    """
    tricodes_all: list[str] = raw["all_tricodes"]
    n_t: int = raw["n_teams"]

    # Postseason teams: regular-season seeds 1-10 (9 and 10 can win the play-in). Only those
    # still alive are fit (see below); the rest keep their starting ratings.
    playoff_global_idx = [i for i in range(n_t) if int(raw["seeds"][i, 0]) <= 10]
    playoff_tcs = [tricodes_all[i] for i in playoff_global_idx]

    # Market targets aligned to tricodes_all; 0.0 for teams with no data for that tier
    def _target(key: str) -> np.ndarray:
        return np.array(
            [(market.get(tc) or {}).get(key) or 0.0 for tc in tricodes_all],
            dtype=np.float64,
        )

    def _has(key: str) -> np.ndarray:
        return np.array(
            [tc in market and (market[tc].get(key) is not None) for tc in tricodes_all],
            dtype=bool,
        )

    target_champ = _target("win_finals_prob")
    target_conf = _target("win_conference_prob")
    target_conf_finals = _target("reach_conf_finals_prob")
    target_conf_semis = _target("reach_conf_semis_prob")

    has_champ = _has("win_finals_prob")
    has_conf = _has("win_conference_prob")
    has_conf_finals = _has("reach_conf_finals_prob")
    has_conf_semis = _has("reach_conf_semis_prob")

    market_coverage = int(has_champ[playoff_global_idx].sum())
    logger.info(
        "market coverage: champ=%d  conf=%d  conf_finals=%d  conf_semis=%d (of %d playoff teams)",
        market_coverage,
        int(has_conf[playoff_global_idx].sum()),
        int(has_conf_finals[playoff_global_idx].sum()),
        int(has_conf_semis[playoff_global_idx].sum()),
        len(playoff_tcs),
    )

    if initial_ratings:
        x0 = np.array(
            [initial_ratings.get(tc, power_ratings.get(tc, 0.0)) for tc in playoff_tcs],
            dtype=np.float64,
        )
        logger.info("Using stored power ratings as calibration starting point (%d teams)", len(initial_ratings))
    else:
        x0 = np.array([power_ratings.get(tc, 0.0) for tc in playoff_tcs], dtype=np.float64)
        logger.info("No initial ratings given; starting calibration from power_ratings")

    # ------------------------------------------------------------------
    # Fixed inputs: the play-in (drawn once with power_ratings), collapsed to its
    # distinct outcomes, and the bracket priced exactly for any ratings
    # ------------------------------------------------------------------
    seeds_opt = np.repeat(raw["seeds"], n_sims, axis=1)
    play_in_7_opt, play_in_8_opt = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds_opt,
        n_teams=n_t,
        n_sims=n_sims,
        rng=np.random.default_rng(seed),
        power_ratings=power_ratings,
        team_idx=raw["team_idx"],
        play_in_results=play_in_results,
    )
    outcomes, first, counts = np.unique(
        np.concatenate([play_in_7_opt, play_in_8_opt]).T, axis=0, return_index=True, return_counts=True
    )
    n_out = len(outcomes)
    bracket = Bracket(
        raw["east_teams"],
        raw["west_teams"],
        np.repeat(raw["seeds"], n_out, axis=1),
        np.repeat(raw["total_wins"], n_out, axis=1),
        n_t,
        play_in_7=play_in_7_opt[:, first],
        play_in_8=play_in_8_opt[:, first],
        weights=counts / n_sims,
        bracket_state=bracket_state,
        team_idx=raw["team_idx"],
    )

    def _prices(x_all: np.ndarray) -> np.ndarray:
        """(champ, conf, reach conf finals, reach conf semis) per team, exactly."""
        ratings_arr = np.zeros(n_t)
        ratings_arr[playoff_global_idx] = x_all
        semis, finals, conf, champ = bracket.probabilities(ratings_arr)
        return np.stack([champ, conf, finals, semis])

    targets = np.stack([target_champ, target_conf, target_conf_finals, target_conf_semis])
    has = np.stack([has_champ, has_conf, has_conf_finals, has_conf_semis])

    # Teams still alive: some chance at the title, not yet won. An eliminated team's rating
    # no longer affects any price, so it's held at its start.
    title0 = _prices(x0)[0]
    alive = np.array([0.0 < title0[gi] < 1.0 for gi in playoff_global_idx], dtype=bool)
    logger.info(
        "calibrating %d of %d postseason teams still alive (%s held at their starting ratings)",
        int(alive.sum()),
        len(playoff_tcs),
        ", ".join(tc for tc, a in zip(playoff_tcs, alive) if not a) or "none",
    )

    if not alive.any():  # the Finals are over: nothing left to fit
        return CalibrationResult(
            ratings={tc: float(x0[j]) for j, tc in enumerate(playoff_tcs)},
            loss_start=0.0,
            loss_final=0.0,
            n_evals=0,
            converged=True,
            market_coverage=market_coverage,
        )

    def _with(x: np.ndarray) -> np.ndarray:
        """Full postseason rating vector: optimized alive teams, the rest at x0."""
        x_all = x0.copy()
        x_all[alive] = x
        return x_all

    loss_history: list[float] = []

    def _residuals(x: np.ndarray) -> np.ndarray:
        miss = (_prices(_with(x)) - targets)[has]
        loss_history.append(float(miss @ miss))
        return np.concatenate([miss, _LEVEL_PULL * (x - x0[alive])])

    # ------------------------------------------------------------------
    # Least squares on the exact prices (sum of squared probability misses)
    # ------------------------------------------------------------------
    _residuals(x0[alive])
    loss_start = loss_history[0]
    logger.info(
        "calibration starting: %d playoff teams, %d with market odds, loss=%.5f",
        len(playoff_tcs),
        market_coverage,
        loss_start,
    )
    result = least_squares(_residuals, x0[alive], diff_step=1e-4, xtol=1e-6, ftol=1e-10, max_nfev=200)
    x_opt: np.ndarray = _with(result.x)
    loss_final = float(np.sum((_prices(x_opt) - targets)[has] ** 2))
    logger.info(
        "calibration done: loss %.5f → %.5f (%d evals, converged=%s)",
        loss_start,
        loss_final,
        result.nfev,
        result.success,
    )

    return CalibrationResult(
        ratings={tc: float(x_opt[j]) for j, tc in enumerate(playoff_tcs)},
        loss_start=loss_start,
        loss_final=loss_final,
        n_evals=int(result.nfev),
        converged=bool(result.success),
        market_coverage=market_coverage,
        loss_history=loss_history,
    )


def build_ratings_array(ratings: dict[str, float], all_tricodes: list[str]) -> np.ndarray:
    """Convert a tricode → rating dict to a full-length numpy array.

    Non-playoff teams absent from *ratings* receive 0.0 (league average).
    The returned array is indexed the same way as ``raw["all_tricodes"]`` so
    it can be passed directly to :func:`simulate_playoffs` as ``ratings``.

    Args:
        ratings: Tricode → power rating, e.g. from
            :attr:`CalibrationResult.ratings`.
        all_tricodes: Ordered list of all team tricodes (``raw["all_tricodes"]``).

    Returns:
        ``(n_teams,)`` float32 array.
    """
    arr = np.zeros(len(all_tricodes), dtype=np.float32)
    for i, tc in enumerate(all_tricodes):
        if tc in ratings:
            arr[i] = float(ratings[tc])
    return arr


# ---------------------------------------------------------------------------
# Regular-season phase: playoff strength on top of the regular-season ratings
# ---------------------------------------------------------------------------

# FanDuel's playoff ladder, in market keys; each rung depends on playoff strength.
# (make_playoffs_prob is the regular season plus the play-in, so it isn't used.)
PLAYOFF_ROUNDS = ("reach_conf_semis_prob", "reach_conf_finals_prob", "win_conference_prob", "win_finals_prob")
# Teams the market gives less than this chance to reach the conference semis keep δ = 0:
# their deeper prices are mostly vig and rounding
PLAYOFF_ADJUSTMENT_MIN_PROB = 0.02
# Ridge toward δ = 0 (squared scaled log-odds per squared point): only pins the contenders'
# shared level, which the prices pin weakly
PLAYOFF_ADJUSTMENT_PRIOR_WEIGHT = 0.001
PLAYOFF_ADJUSTMENT_MAX = 8.0
_PLAYOFF_FIT_SIMS = 100_000
_PLAYOFF_FIT_SEED = 321
_PLAYOFF_FIT_MAX_ITER = 12
_PLAYOFF_FIT_STEP_TOLERANCE = 0.01  # points
_JACOBIAN_STEP = 0.05  # points (the exact bracket is smooth: no sampling to smooth over)
# The Jacobian is taken on the first simulations only; the residuals use every simulation
_JACOBIAN_SIMS = 10_000


@dataclass
class PlayoffAdjustmentFit:
    """Output of :func:`fit_playoff_adjustments`."""

    adjustments: dict[str, float]  # tricode -> δ (points); playoff rating = rating + δ
    n_market_teams: int  # teams fit (the rest have δ = 0)
    max_abs_logit_error: float  # largest remaining per-round log-odds miss among fit teams
    iterations: int


@dataclass
class _Postseason:
    """The season sim's postseason inputs, priced exactly for any playoff adjustments."""

    raw: dict
    seeds: np.ndarray
    total_wins: np.ndarray
    base: np.ndarray  # (n_teams,) or (n_teams, n_sims) regular-season ratings (+ offsets)
    play_in_7: np.ndarray
    play_in_8: np.ndarray
    bracket: Bracket

    @classmethod
    def build(
        cls, raw: dict, ratings: dict[str, float], rating_offsets: np.ndarray | None, n_sims: int, seed: int
    ) -> _Postseason:
        n = min(n_sims, raw["seeds"].shape[1])
        offsets = rating_offsets[:, :n] if rating_offsets is not None else None
        base = build_ratings_array(ratings, raw["all_tricodes"])
        base = base[:, None] + offsets if offsets is not None else base
        play_in_7, play_in_8 = compute_play_in_results(
            east_teams=raw["east_teams"],
            west_teams=raw["west_teams"],
            seeds=raw["seeds"][:, :n],
            n_teams=raw["n_teams"],
            n_sims=n,
            rng=np.random.default_rng(seed),
            power_ratings=ratings,
            team_idx=raw["team_idx"],
            rating_offsets=offsets,
        )
        seeds, total_wins = raw["seeds"][:, :n], raw["total_wins"][:, :n]
        bracket = Bracket(
            raw["east_teams"],
            raw["west_teams"],
            seeds,
            total_wins,
            raw["n_teams"],
            play_in_7=play_in_7,
            play_in_8=play_in_8,
        )
        return cls(raw, seeds, total_wins, base, play_in_7, play_in_8, bracket)

    @property
    def n_sims(self) -> int:
        return self.seeds.shape[1]

    def head(self, n: int) -> _Postseason:
        """The first *n* simulations (same seeds, play-in and offsets)."""
        if n >= self.n_sims:
            return self
        raw = self.raw
        seeds, total_wins = self.seeds[:, :n], self.total_wins[:, :n]
        p7, p8 = self.play_in_7[:, :n], self.play_in_8[:, :n]
        bracket = Bracket(
            raw["east_teams"], raw["west_teams"], seeds, total_wins, raw["n_teams"], play_in_7=p7, play_in_8=p8
        )
        base = self.base[:, :n] if self.base.ndim == 2 else self.base
        return _Postseason(raw, seeds, total_wins, base, p7, p8, bracket)

    def prices(self, delta: np.ndarray) -> np.ndarray:
        """``(len(PLAYOFF_ROUNDS), n_teams)`` exact probabilities with adjustments *delta*,
        averaged over the simulations' seeds (:class:`.playoff_bracket.Bracket`)."""
        shift = delta[:, None] if self.base.ndim == 2 else delta
        return self.bracket.probabilities(self.base + shift)


def fit_playoff_adjustments(
    raw: dict,
    ratings: dict[str, float],
    market: dict,
    *,
    rating_offsets: np.ndarray | None = None,
    n_sims: int = _PLAYOFF_FIT_SIMS,
    seed: int = _PLAYOFF_FIT_SEED,
    prior_weight: float = PLAYOFF_ADJUSTMENT_PRIOR_WEIGHT,
) -> PlayoffAdjustmentFit:
    """Fit each team's playoff strength over its regular-season rating to FanDuel futures.

    Playoff teams aren't the regular season's: rotations shorten and stars play more, so the
    market prices some teams' playoff runs well above (or below) what their win total
    implies. In the regular-season phase each simulation's seeds come from the season sim;
    this fits a per-team δ so our playoff series (rating + δ) reproduce FanDuel's ladder:
    reach the conference semis, the conference finals, win the conference, win the title
    (:data:`PLAYOFF_ROUNDS`, vig-free within their pools). The semis anchor the level of δ:
    the deeper rounds are decided mostly between contenders, so they barely move when every
    contender's δ shifts together, while round 1 is usually against a weaker team.

    Only the postseason is priced, on the first *n_sims* of the season's simulations with
    their seeds, wins and rating offsets, and the play-in fixed (it uses the regular-season
    ratings, as in the playoff phases). Each simulation's bracket is priced exactly
    (:class:`.playoff_bracket.Bracket`: no series sampled), so the prices are a smooth,
    noise-free function of δ; only the seeds are a sample. A team's miss is its log-odds error
    per round (simulated − market), scaled by √(p(1 − p)) of the market price so near-certain
    and long-shot prices don't dominate. Gauss-Newton with a ridge toward δ = 0 (λ =
    *prior_weight*); the Jacobian comes from bumping each fit team's δ.

    Args:
        raw: ``compute_raw_seedings`` output for the season sim.
        ratings: Tricode → regular-season rating.
        market: ``get_latest_fanduel_futures()`` rows by tricode.
        rating_offsets: ``(n_teams, n_sims)`` per-simulation offsets aligned with *raw*, or None.
        n_sims: Season simulations whose seeds are priced (at most the season's).
        seed: Fixed seed for the play-in draws.
        prior_weight: Pull toward δ = 0 (see :data:`PLAYOFF_ADJUSTMENT_PRIOR_WEIGHT`).
    """
    tricodes: list[str] = raw["all_tricodes"]
    n_t: int = raw["n_teams"]
    target = np.array(
        [[(market.get(tc) or {}).get(key) or np.nan for tc in tricodes] for key in PLAYOFF_ROUNDS], dtype=np.float64
    )
    fit = np.nan_to_num(target[0]) >= PLAYOFF_ADJUSTMENT_MIN_PROB
    if not fit.any():
        return PlayoffAdjustmentFit({}, 0, 0.0, 0)

    post = _Postseason.build(raw, ratings, rating_offsets, n_sims, seed)
    clip = 0.5 / post.n_sims  # a team the sim never sends through still has a finite log-odds

    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(p, clip, 1 - clip)
        return np.log(p / (1 - p))

    # Residuals: per team and round, log-odds miss (simulated − market) scaled by the square root
    # of p(1 − p) on the market price, so near-certain and long-shot prices don't dominate
    has = fit[None, :] & ~np.isnan(target)
    scale = np.sqrt(np.where(has, np.nan_to_num(target) * (1 - np.nan_to_num(target)), 0.0))
    target_logit = _logit(np.nan_to_num(target, nan=0.5))
    idx = np.nonzero(fit)[0]

    def _residuals(delta: np.ndarray, on: _Postseason = post) -> np.ndarray:
        return (scale * (_logit(on.prices(delta)) - target_logit))[has]

    sample = post.head(_JACOBIAN_SIMS)

    def _jacobian(delta: np.ndarray, _base_res: np.ndarray) -> np.ndarray:
        base_res = _residuals(delta, sample)
        cols = []
        for i in idx:
            bumped = delta.copy()
            bumped[i] += _JACOBIAN_STEP
            cols.append((_residuals(bumped, sample) - base_res) / _JACOBIAN_STEP)
        return np.stack(cols, axis=1)

    # Gauss-Newton with a ridge toward δ = 0: minimize |r(δ)|² + λ|δ|². The Jacobian is
    # estimated once by bumping each team's δ on a subsample (it changes slowly) and
    # refreshed if a step stops helping.
    delta = np.zeros(n_t)
    res = _residuals(delta)
    jac = _jacobian(delta, res)
    loss = float(res @ res)
    iterations = 0
    for iterations in range(1, _PLAYOFF_FIT_MAX_ITER + 1):
        d = delta[idx]
        lhs = jac.T @ jac + prior_weight * np.eye(len(idx))
        step = np.linalg.solve(lhs, -(jac.T @ res + prior_weight * d))
        new_delta = delta.copy()
        new_delta[idx] = np.clip(d + step, -PLAYOFF_ADJUSTMENT_MAX, PLAYOFF_ADJUSTMENT_MAX)
        new_res = _residuals(new_delta)
        new_loss = float(new_res @ new_res + prior_weight * new_delta[idx] @ new_delta[idx])
        if new_loss >= loss + prior_weight * d @ d - 1e-9:
            if iterations > 1:
                jac = _jacobian(delta, res)  # stale slopes: refresh once more, then stop
                lhs = jac.T @ jac + prior_weight * np.eye(len(idx))
                step = np.linalg.solve(lhs, -(jac.T @ res + prior_weight * d))
                new_delta[idx] = np.clip(d + step, -PLAYOFF_ADJUSTMENT_MAX, PLAYOFF_ADJUSTMENT_MAX)
                new_res = _residuals(new_delta)
            if float(new_res @ new_res) >= float(res @ res):
                break
        delta, res = new_delta, new_res
        loss = float(res @ res)
        if np.abs(step).max() < _PLAYOFF_FIT_STEP_TOLERANCE:
            break
    miss = np.zeros(n_t)
    misses = _logit(post.prices(delta)) - target_logit
    miss[fit] = np.where(has, np.abs(misses), 0.0).max(axis=0)[fit]

    adjustments = {tc: float(delta[i]) for i, tc in enumerate(tricodes) if fit[i]}
    logger.info(
        "Playoff adjustments fit to FanDuel futures for %d teams in %d passes "
        "(max log-odds miss %.3f; δ range %.1f to %.1f)",
        int(fit.sum()),
        iterations,
        float(np.abs(miss[fit]).max()),
        float(delta[fit].min()),
        float(delta[fit].max()),
    )
    return PlayoffAdjustmentFit(adjustments, int(fit.sum()), float(np.abs(miss[fit]).max()), iterations)
