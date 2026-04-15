"""Calibrate playoff power ratings to match FanDuel market odds.

Runs a Nelder-Mead optimisation over per-team power ratings until the Monte
Carlo simulation reproduces the FanDuel implied championship and
conference-win probabilities stored in the database.

Typical usage::

    raw = compute_raw_seedings(...)
    result = await calibrate_ratings(repo, raw, play_in_results, bracket_state)
    # result.ratings is a tricode -> rating dict ready for simulate_playoffs()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.services.nba_simulator.play_in_tournament import (
    ConferencePlayInResults,
    compute_play_in_results,
)
from nba_wins_pool.services.nba_simulator.playoff_sim import PlayoffBracketState, simulate_playoffs

logger = logging.getLogger(__name__)

_DEFAULT_N_SIMS = 20_000
_DEFAULT_SEED = 123


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


async def calibrate_ratings(
    repo: NBAProjectionsRepository,
    raw: dict,
    play_in_results: dict[str, ConferencePlayInResults] | None = None,
    bracket_state: PlayoffBracketState | None = None,
    n_sims: int = _DEFAULT_N_SIMS,
    seed: int = _DEFAULT_SEED,
) -> CalibrationResult:
    """Optimise power ratings so the playoff simulation matches FanDuel odds.

    Fetches the latest FanDuel futures and ESPN playoff BPI from the database,
    then runs Nelder-Mead to minimise the sum of squared errors between the
    simulated championship / conference-win probabilities and the FanDuel
    implied probabilities.

    The objective function is made deterministic by seeding the RNG from the
    same value on every evaluation, so the optimiser sees a stable landscape
    rather than a noisy one.

    Args:
        repo: ``NBAProjectionsRepository`` for DB access.
        raw: Raw seedings dict returned by ``compute_raw_seedings()``.  Must
            contain ``seeds``, ``total_wins``, ``all_tricodes``, ``team_idx``,
            ``team_meta``, ``east_teams``, ``west_teams``, ``n_teams``.
        play_in_results: Known play-in game winners from
            ``get_play_in_results()``.  ``None`` entries are simulated.
        bracket_state: Known series results from ``get_playoff_bracket_state()``.
            ``None`` means every series is simulated from scratch.
        n_sims: Monte Carlo trials per objective evaluation (default 20 000).
            Higher values reduce objective noise but slow each evaluation.
        seed: Master RNG seed.  Fixing this makes the entire calibration
            reproducible.

    Returns:
        :class:`CalibrationResult` with optimised ratings and diagnostics.
    """
    # ------------------------------------------------------------------
    # 1. Fetch market targets and starting ratings from DB
    # ------------------------------------------------------------------
    market = await repo.get_latest_fanduel_futures()
    pbpi_map = await repo.get_latest_playoff_bpi()

    tricodes_all: list[str] = raw["all_tricodes"]
    n_t: int = raw["n_teams"]

    # Playoff teams only (seeds 1–8 after play-in)
    playoff_global_idx = [i for i in range(n_t) if int(raw["seeds"][i, 0]) <= 8]
    playoff_tcs = [tricodes_all[i] for i in playoff_global_idx]

    # Market targets aligned to tricodes_all; 0.0 for teams with no FanDuel row
    target_champ = np.array(
        [(market.get(tc) or {}).get("win_finals_prob") or 0.0 for tc in tricodes_all],
        dtype=np.float64,
    )
    target_conf = np.array(
        [(market.get(tc) or {}).get("win_conference_prob") or 0.0 for tc in tricodes_all],
        dtype=np.float64,
    )
    has_market = np.array(
        [tc in market and (market[tc].get("win_finals_prob") is not None) for tc in tricodes_all],
        dtype=bool,
    )
    market_coverage = int(has_market[playoff_global_idx].sum())

    # Starting ratings: ESPN playoff BPI where available, 0.0 otherwise
    x0 = np.array([pbpi_map.get(tc, 0.0) for tc in playoff_tcs], dtype=np.float64)

    # ------------------------------------------------------------------
    # 2. Pre-build fixed simulation inputs
    # ------------------------------------------------------------------
    seeds_opt = np.repeat(raw["seeds"], n_sims, axis=1)
    total_wins_opt = np.repeat(raw["total_wins"], n_sims, axis=1)

    # Pre-simulate play-in once (fixed seed → same seed–7/8 assignment every eval)
    play_in_7_opt, play_in_8_opt = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds_opt,
        total_wins=total_wins_opt,
        n_teams=n_t,
        n_sims=n_sims,
        rng=np.random.default_rng(seed),
        team_idx=raw["team_idx"],
        play_in_results=play_in_results,
    )

    # ------------------------------------------------------------------
    # 3. Objective function
    # ------------------------------------------------------------------

    def _run_sim(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return (champ_pct, conf_pct) per team for ratings vector *x*."""
        ratings_arr = np.zeros(n_t, dtype=np.float32)
        for j, gi in enumerate(playoff_global_idx):
            ratings_arr[gi] = float(x[j])

        # Recreate RNG from the same seed every call → deterministic landscape
        po_w, champ_s, east_champ_s, west_champ_s = simulate_playoffs(
            east_teams=raw["east_teams"],
            west_teams=raw["west_teams"],
            seeds=seeds_opt,
            total_wins=total_wins_opt,
            n_teams=n_t,
            n_sims=n_sims,
            rng=np.random.default_rng(seed + 1),
            ratings=ratings_arr,
            bracket_state=bracket_state,
            team_idx=raw["team_idx"],
            play_in_7=play_in_7_opt,
            play_in_8=play_in_8_opt,
        )
        sim_champ = np.bincount(champ_s, minlength=n_t).astype(np.float64) / n_sims
        east_cf = np.bincount(east_champ_s, minlength=n_t).astype(np.float64) / n_sims
        west_cf = np.bincount(west_champ_s, minlength=n_t).astype(np.float64) / n_sims
        return sim_champ, east_cf + west_cf

    loss_history: list[float] = []

    def _loss(x: np.ndarray) -> float:
        sim_champ, sim_conf = _run_sim(x)
        m = has_market
        v = float(np.sum((sim_champ[m] - target_champ[m]) ** 2 + (sim_conf[m] - target_conf[m]) ** 2))
        loss_history.append(v)
        if len(loss_history) % 100 == 0:
            logger.debug("calibration eval %d: loss=%.5f", len(loss_history), v)
        return v

    # ------------------------------------------------------------------
    # 4. Run optimiser
    # ------------------------------------------------------------------
    loss_start = _loss(x0)
    logger.info(
        "calibration starting: %d playoff teams, %d with market odds, loss=%.5f",
        len(playoff_tcs),
        market_coverage,
        loss_start,
    )

    result = minimize(
        _loss,
        x0,
        method="Nelder-Mead",
        options={
            "maxiter": 3000,
            "xatol": 0.05,
            "fatol": 1e-5,
            "adaptive": True,
        },
    )
    x_opt: np.ndarray = result.x

    logger.info(
        "calibration done: loss %.5f → %.5f (%d evals, converged=%s)",
        loss_start,
        result.fun,
        result.nfev,
        result.success,
    )

    ratings = {tc: float(x_opt[j]) for j, tc in enumerate(playoff_tcs)}

    return CalibrationResult(
        ratings=ratings,
        loss_start=loss_start,
        loss_final=float(result.fun),
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
