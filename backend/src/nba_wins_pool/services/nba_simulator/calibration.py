"""Calibrate playoff power ratings to match FanDuel market odds.

Iteratively adjusts per-team power ratings until the Monte Carlo simulation
reproduces the FanDuel implied championship and conference-win probabilities
stored in the database.

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


def _calibrate_ratings(
    market: dict,
    pbpi_map: dict[str, float],
    raw: dict,
    play_in_results: dict[str, ConferencePlayInResults] | None = None,
    bracket_state: PlayoffBracketState | None = None,
    n_sims: int = _DEFAULT_N_SIMS,
    seed: int = _DEFAULT_SEED,
    initial_ratings: dict[str, float] | None = None,
) -> CalibrationResult:
    """Optimise power ratings so the playoff simulation matches FanDuel odds.

    Pure-Python, synchronous version — callers are responsible for fetching
    *market* and *pbpi_map* from the database before calling this function.
    Use :func:`calibrate_ratings` for the async convenience wrapper.

    Adjusts per-team power ratings to minimise the sum of squared errors
    between simulated championship / conference-win probabilities and the
    FanDuel implied probabilities.  The objective function is made
    deterministic by seeding the RNG from the same value on every evaluation.

    Args:
        market: FanDuel futures dict keyed by tricode, as returned by
            ``NBAProjectionsRepository.get_latest_fanduel_futures()``.
        pbpi_map: ESPN playoff BPI dict keyed by tricode, as returned by
            ``NBAProjectionsRepository.get_latest_playoff_bpi()``.
        raw: Raw seedings dict returned by ``compute_raw_seedings()``.  Must
            contain ``seeds``, ``total_wins``, ``all_tricodes``, ``team_idx``,
            ``east_teams``, ``west_teams``, ``n_teams``.
        play_in_results: Known play-in game winners from
            ``get_play_in_results()``.  ``None`` entries are simulated.
        bracket_state: Known series results from ``get_playoff_bracket_state()``.
            ``None`` means every series is simulated from scratch.
        n_sims: Monte Carlo trials per objective evaluation (default 20 000).
            Higher values reduce objective noise but slow each evaluation.
        seed: Master RNG seed.  Fixing this makes the entire calibration
            reproducible.
        initial_ratings: Per-team power ratings to use as the optimiser
            starting point (tricode → rating).  When provided, each playoff
            team's initial value is taken from here first, falling back to
            *pbpi_map* for any teams not present.  Pass ``None`` (default) to
            start entirely from ESPN BPI.

    Returns:
        :class:`CalibrationResult` with optimised ratings and diagnostics.
    """
    tricodes_all: list[str] = raw["all_tricodes"]
    n_t: int = raw["n_teams"]

    # Playoff teams only (seeds 1–8 after play-in)
    playoff_global_idx = [i for i in range(n_t) if int(raw["seeds"][i, 0]) <= 8]
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

    # Starting ratings: stored calibrated ratings where available, ESPN BPI as fallback
    if initial_ratings:
        x0 = np.array(
            [initial_ratings.get(tc, pbpi_map.get(tc, 0.0)) for tc in playoff_tcs],
            dtype=np.float64,
        )
        logger.info("Using stored power ratings as calibration starting point (%d teams)", len(initial_ratings))
    else:
        x0 = np.array([pbpi_map.get(tc, 0.0) for tc in playoff_tcs], dtype=np.float64)
        logger.info("No stored power ratings found; starting calibration from ESPN BPI")

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
        n_teams=n_t,
        n_sims=n_sims,
        rng=np.random.default_rng(seed),
        playoff_bpi=pbpi_map,
        team_idx=raw["team_idx"],
        play_in_results=play_in_results,
    )

    # ------------------------------------------------------------------
    # 3. Objective function
    # ------------------------------------------------------------------

    def _run_sim(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return (champ_pct, conf_pct, reach_conf_finals_pct, reach_conf_semis_pct) per team."""
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
        # Advancement counts derived from games won:
        # won Round 1 (conf semis) ↔ po_w >= 4; won Round 2 (conf finals) ↔ po_w >= 8
        sim_reach_conf_finals = (po_w >= 8).mean(axis=1).astype(np.float64)
        sim_reach_conf_semis = (po_w >= 4).mean(axis=1).astype(np.float64)
        return sim_champ, east_cf + west_cf, sim_reach_conf_finals, sim_reach_conf_semis

    loss_history: list[float] = []

    def _loss(x: np.ndarray) -> float:
        sim_champ, sim_conf, sim_reach_conf_finals, sim_reach_conf_semis = _run_sim(x)
        v = 0.0
        if has_champ.any():
            v += float(np.sum((sim_champ[has_champ] - target_champ[has_champ]) ** 2))
        if has_conf.any():
            v += float(np.sum((sim_conf[has_conf] - target_conf[has_conf]) ** 2))
        if has_conf_finals.any():
            v += float(np.sum((sim_reach_conf_finals[has_conf_finals] - target_conf_finals[has_conf_finals]) ** 2))
        if has_conf_semis.any():
            v += float(np.sum((sim_reach_conf_semis[has_conf_semis] - target_conf_semis[has_conf_semis]) ** 2))
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

    _last_logged_iter = [0]
    _last_checked_loss = [loss_start]

    def _callback(x: np.ndarray) -> bool | None:
        iteration = len(loss_history)
        current_loss = loss_history[-1]
        rel_improvement = (_last_checked_loss[0] - current_loss) / (_last_checked_loss[0] + 1e-12)
        _last_checked_loss[0] = current_loss
        if iteration - _last_logged_iter[0] >= 50:
            logger.info(
                "calibration iter %d: loss=%.5f (rel_improvement=%.2f%%)",
                iteration,
                current_loss,
                rel_improvement * 100,
            )
            _last_logged_iter[0] = iteration
        if rel_improvement < 0.01:
            logger.info(
                "calibration stopping at iter %d: rel_improvement=%.4f%% < 1%%", iteration, rel_improvement * 100
            )
            return True
        return None

    result = minimize(
        _loss,
        x0,
        method="Nelder-Mead",
        callback=_callback,
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


async def calibrate_ratings(
    repo: NBAProjectionsRepository | None,
    raw: dict,
    play_in_results: dict[str, ConferencePlayInResults] | None = None,
    bracket_state: PlayoffBracketState | None = None,
    n_sims: int = _DEFAULT_N_SIMS,
    seed: int = _DEFAULT_SEED,
    *,
    fanduel_futures: dict | None = None,
    playoff_bpi: dict | None = None,
    initial_ratings: dict[str, float] | None = None,
) -> CalibrationResult:
    """Calibrate power ratings so the playoff simulation matches FanDuel futures odds.

    Fetches FanDuel futures from the database and ESPN playoff BPI, then
    adjusts per-team power ratings to minimise sum-of-squared-errors between
    simulated championship / conference-win probabilities and the implied
    market odds.

    Args:
        repo: ``NBAProjectionsRepository`` for DB access.  May be ``None`` when
            pre-fetched *fanduel_futures* and *playoff_bpi* are supplied directly.
        raw: Raw seedings dict returned by ``compute_raw_seedings()``.
        play_in_results: Known play-in game winners.
        bracket_state: Known series results.
        n_sims: Monte Carlo trials per objective evaluation (default 20 000).
        seed: Master RNG seed.
        fanduel_futures: Pre-fetched futures dict (tricode → probs) to use
            directly, skipping the repo fetch.
        playoff_bpi: Pre-fetched ESPN playoff BPI dict (tricode → rating).
            When provided, the repo fetch is skipped.
        initial_ratings: Per-team power ratings to use as the optimiser
            starting point (tricode → rating).  Typically the calibrated
            ratings from the previous simulation run stored in the database.
            Falls back to ESPN BPI for any missing teams.  Pass ``None``
            (default) to start entirely from ESPN BPI.

    Returns:
        :class:`CalibrationResult` with optimised ratings and diagnostics.
    """
    if fanduel_futures is None:
        if repo is None:
            raise ValueError("Either repo or fanduel_futures must be provided")
        fanduel_futures = await repo.get_latest_fanduel_futures()
    if playoff_bpi is None:
        if repo is None:
            raise ValueError("Either repo or playoff_bpi must be provided")
        playoff_bpi = await repo.get_latest_playoff_bpi()
    return _calibrate_ratings(
        fanduel_futures, playoff_bpi, raw, play_in_results, bracket_state, n_sims, seed, initial_ratings
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
