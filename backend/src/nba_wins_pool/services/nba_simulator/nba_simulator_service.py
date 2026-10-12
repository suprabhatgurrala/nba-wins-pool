"""
Main control flow for the NBA simulator service.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.simulation_results import SimulationRosterResult, SimulationTeamResult
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.repositories.roster_repository import RosterRepository
from nba_wins_pool.repositories.roster_slot_repository import RosterSlotRepository
from nba_wins_pool.repositories.simulation_results_repository import SimulationResultsRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.services.nba_espn_projections_service import NBAEspnProjectionsService
from nba_wins_pool.services.nba_simulator.core.calibration import (
    CalibrationResult,
    calibrate_ratings,
)
from nba_wins_pool.services.nba_simulator.core.game_probability import game_probabilities
from nba_wins_pool.services.nba_simulator.core.play_in_tournament import ConferencePlayInResults
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import compute_raw_seedings
from nba_wins_pool.services.nba_simulator.core.playoff_sim import PlayoffBracketState
from nba_wins_pool.services.nba_simulator.core.pool_sim import compute_pool_outcomes
from nba_wins_pool.services.nba_simulator.core.rating_calibration import WinTotal, fit_ratings_to_win_totals
from nba_wins_pool.services.nba_simulator.core.rating_uncertainty import (
    WinLadder,
    current_rating_sd,
    preseason_rating_sd,
    results_cutoff,
    update_ratings_from_results,
)
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import (
    N_SIMS,
    PlayoffSimResult,
    completed_standings_games,
    count_wins_from_completed,
    run_play_in_simulation,
    run_playoff_simulation,
    run_regular_season_simulation,
)
from nba_wins_pool.services.nba_simulator.data import (
    detect_season_phase,
    get_nba_schedule,
    get_play_in_results,
    get_playoff_bracket_state,
)
from nba_wins_pool.services.nba_vegas_projections_service import NBAVegasProjectionsService
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.nba_game_type import NBAGameType
from nba_wins_pool.utils.projections import fanduel_blend_weight
from nba_wins_pool.utils.time import utc_now

logger = logging.getLogger(__name__)

ESPN_PROJECTION_MAX_AGE = timedelta(hours=36)
PLAYOFF_FUTURES_MAX_AGE = timedelta(hours=36)


@dataclass
class RawSimArrays:
    """Per-team simulation arrays plus calibration context.

    Always-present fields hold the Monte Carlo arrays needed for pool-outcome
    computation.  Optional fields are populated only in the play-in / playoffs
    phases (calibration runs there).
    """

    rs_wins_sim: np.ndarray  # (n_teams, n_sims) float32 — regular-season wins
    po_wins_sim: np.ndarray
    all_tricodes: list[str]  # ordered tricodes matching axis 0 of the arrays
    current_wins: dict[str, float] = field(default_factory=dict)
    # Calibration context — set only in play-in / playoffs phases
    po_raw: dict | None = None
    play_in_results: dict[str, ConferencePlayInResults] | None = None
    bracket_state: PlayoffBracketState | None = None
    calibrated_ratings: dict[str, float] | None = None
    vegas_odds_fetched_at: datetime | None = None
    preseason_rating_sd: dict[str, float] = field(default_factory=dict)
    ratings_through: datetime | None = None


@dataclass
class SimulationOutput:
    """Top-level result of :func:`simulate_nba_season`."""

    phase: NBAGameType
    win_stats: pd.DataFrame  # tricode, mean_wins (projected RS wins)
    seeding: pd.DataFrame  # per-team seed probabilities by conference
    play_in_results: dict[str, ConferencePlayInResults] | None
    playoff_summary: pd.DataFrame | None  # tricode, conference, seed, champ_pct, ...
    raw_sim: RawSimArrays


async def _load_warm_start_ratings(
    sim_repo: SimulationResultsRepository | None,
    team_repo: TeamRepository | None,
    season: str,
) -> tuple[dict[str, float] | None, datetime | None]:
    """Return (ratings, vegas_fetched_at) from the most recent stored sim, or (None, None)."""
    if sim_repo is None or team_repo is None:
        return None, None
    stored = await sim_repo.get_latest_team_results(season)
    if not stored:
        return None, None
    teams = await team_repo.get_all_by_league_slug(LeagueSlug.NBA)
    team_id_to_tricode = {t.id: t.abbreviation for t in teams}
    ratings = {team_id_to_tricode[r.team_id]: r.power_rating for r in stored if r.team_id in team_id_to_tricode}
    logger.info("Loaded %d stored power ratings for warm-start calibration", len(ratings))
    return ratings, stored[0].vegas_odds_fetched_at


@dataclass
class _StoredTeamState:
    """Regular-season values carried from the last stored run (see :func:`_load_stored_state`)."""

    preseason_sd: dict[str, float] = field(default_factory=dict)
    playoff_adjustments: dict[str, float] = field(default_factory=dict)
    ratings_through: datetime | None = None


async def _load_stored_state(
    sim_repo: SimulationResultsRepository | None,
    team_repo: TeamRepository | None,
    season: str,
) -> _StoredTeamState:
    """τ₀, δ and the ratings' results cutoff from the most recent stored sim this season.

    Empty when nothing is stored, or the latest run is from a later phase (those don't
    store them: past the regular season the values are locked, not refit).
    """
    if sim_repo is None or team_repo is None:
        return _StoredTeamState()
    try:
        stored = await sim_repo.get_latest_team_results(season)
        if not stored:
            return _StoredTeamState()
        teams = await team_repo.get_all_by_league_slug(LeagueSlug.NBA)
    except Exception:
        logger.warning("Loading the stored simulation state failed", exc_info=True)
        return _StoredTeamState()
    team_id_to_tricode = {t.id: t.abbreviation for t in teams}
    rows = [(team_id_to_tricode[r.team_id], r) for r in stored if r.team_id in team_id_to_tricode]
    return _StoredTeamState(
        preseason_sd={tc: r.preseason_rating_sd for tc, r in rows if r.preseason_rating_sd is not None},
        playoff_adjustments={tc: r.playoff_adjustment for tc, r in rows if r.playoff_adjustment is not None},
        ratings_through=next((r.ratings_through for _, r in rows if r.ratings_through is not None), None),
    )


def _align_po_to_rs(
    po_wins_sim: np.ndarray,
    po_tricodes: list[str],
    rs_wins_sim: np.ndarray,
    all_tricodes: list[str],
) -> np.ndarray:
    """Reorder ``po_wins_sim`` rows to match ``all_tricodes`` ordering."""
    if po_tricodes == all_tricodes or len(po_wins_sim) == 0:
        return po_wins_sim
    po_idx = {tc: i for i, tc in enumerate(po_tricodes)}
    aligned = np.zeros_like(rs_wins_sim)
    for i, tc in enumerate(all_tricodes):
        j = po_idx.get(tc)
        if j is not None:
            aligned[i] = po_wins_sim[j]
    return aligned


async def simulate_nba_season(
    nba_service: NbaDataService,
    projections_repo: NBAProjectionsRepository | None = None,
    *,
    fanduel_futures: dict | None = None,
    power_ratings: dict | None = None,
    sim_repo: SimulationResultsRepository | None = None,
    team_repo: TeamRepository | None = None,
    calibrate: bool = True,
) -> SimulationOutput:
    """Run the NBA season simulation appropriate for the current phase.

    Fetches the schedule once, detects the season phase from unfinished
    (upcoming or in-progress) games, and dispatches to the right simulators:

    - **Regular season** — Power ratings are fit to current FanDuel win totals
      (starting from *power_ratings*: the last stored ratings, else ESPN BPI).
      Monte Carlo projection of remaining regular-season games (FanDuel
      moneylines where listed, otherwise ratings + home court + rest), including
      NBA Cup games whose matchups aren't set yet.  Each simulation's seeds then
      feed our own play-in and playoff brackets (NBA.com brackets aren't used yet).
    - **Play-in** — Actual regular-season standings used as the starting point.
      Remaining play-in games are simulated; the resulting seed-7/8 uncertainty
      propagates into the full playoff bracket simulation.
    - **Playoffs** — All regular-season and play-in results are locked in.
      Known series results and FanDuel odds for in-progress series are loaded
      from the NBA bracket API and used to constrain the playoff simulation.

    For play-in and playoffs phases, power ratings are always calibrated
    against FanDuel implied championship / conference-win probabilities fetched
    from the database.  When *sim_repo* and *team_repo* are both provided, the
    most recently stored per-team power ratings are loaded from the database as
    a starting point.
    Falls back to ESPN BPI (cold start) when none exist.

    Returns:
        :class:`SimulationOutput` bundling the detected phase, per-team
        win/seeding DataFrames, play-in results, playoff summary, and the raw
        Monte Carlo arrays in :class:`RawSimArrays`.
    """
    schedule = get_nba_schedule(nba_service)
    phase = detect_season_phase(schedule)

    if phase == NBAGameType.REGULAR_SEASON:
        playoff_market = await _load_playoff_market(projections_repo, nba_service.get_current_season(), fanduel_futures)
        stored = await _load_stored_state(sim_repo, team_repo, nba_service.get_current_season())
        fit = await _regular_season_ratings(
            schedule,
            nba_service=nba_service,
            projections_repo=projections_repo,
            prior=power_ratings or {},
            calibrate=calibrate,
            stored=stored,
        )
        return _simulate_regular_season_phase(
            schedule,
            phase,
            ratings=fit.ratings,
            rating_sd=fit.rating_sd,
            preseason_sd=fit.preseason_sd,
            vegas_odds_fetched_at=fit.fetched_at,
            playoff_market=playoff_market,
            stored_playoff_adjustments=stored.playoff_adjustments,
            ratings_through=fit.ratings_through,
        )

    return await _simulate_postseason_phase(
        schedule,
        phase,
        nba_service=nba_service,
        projections_repo=projections_repo,
        fanduel_futures=fanduel_futures,
        power_ratings=power_ratings,
        sim_repo=sim_repo,
        team_repo=team_repo,
        calibrate=calibrate,
    )


def _win_targets(
    fanduel: dict[str, dict], espn: dict[str, dict], now: datetime
) -> tuple[dict[str, WinTotal], dict[str, float], datetime | None]:
    """Per-team targets for the regular-season ratings fit.

    - A current FanDuel line (full blend weight, see :func:`fanduel_blend_weight`) with
      an over price: fit its over probability.
    - Otherwise, the blended projection the auction uses: FanDuel's line weighted by
      its age, plus ESPN BPI projected wins for the rest, fit as mean wins. ESPN rows
      older than :data:`ESPN_PROJECTION_MAX_AGE` aren't used.
    - Neither: no target (the team stays at its prior).

    Args:
        fanduel: ``get_latest_win_totals(season, "fanduel")`` rows by tricode.
        espn: ``get_latest_win_totals(season, "espn_bpi")`` rows by tricode.
        now: Current UTC time (naive, like the stored ``fetched_at``).

    Returns:
        ``(win_totals, projected_wins, fetched_at)``, where *fetched_at* is the newest
        ``fetched_at`` among the rows used.
    """
    today = now.date()
    win_totals: dict[str, WinTotal] = {}
    projected_wins: dict[str, float] = {}
    used: list[datetime] = []
    for tc in sorted(set(fanduel) | set(espn)):
        fd, es = fanduel.get(tc), espn.get(tc)
        fd_weight = fanduel_blend_weight(fd["projection_date"], today) if fd else 0.0
        if fd and fd_weight == 1.0 and fd["over_prob"] is not None:
            win_totals[tc] = WinTotal(line=fd["wins"], over_prob=fd["over_prob"])
            used.append(fd["fetched_at"])
            continue
        if es and es["fetched_at"] < now - ESPN_PROJECTION_MAX_AGE:
            es = None
        if es:
            fd_wins = fd["wins"] if fd else 0.0
            projected_wins[tc] = fd_weight * fd_wins + (1.0 - fd_weight) * es["wins"]
            used.append(es["fetched_at"])
        elif fd and fd_weight > 0:
            projected_wins[tc] = fd["wins"]
        else:
            continue
        if fd and fd_weight > 0:
            used.append(fd["fetched_at"])
    return win_totals, projected_wins, max(used, default=None)


async def _load_playoff_market(
    projections_repo: NBAProjectionsRepository | None, season: str, fanduel_futures: dict | None
) -> dict | None:
    """This season's FanDuel futures for the playoff adjustments, without rows older than
    :data:`PLAYOFF_FUTURES_MAX_AGE`; None when there are none (the series then use the
    regular-season ratings)."""
    rows = fanduel_futures
    if rows is None and projections_repo is not None:
        try:
            rows = await projections_repo.get_latest_fanduel_futures(season)
        except Exception:
            logger.warning("Loading FanDuel futures failed; no playoff adjustments", exc_info=True)
            return None
    if not rows:
        return None
    cutoff = utc_now() - PLAYOFF_FUTURES_MAX_AGE
    fresh = {tc: row for tc, row in rows.items() if row.get("fetched_at") is None or row["fetched_at"] >= cutoff}
    return fresh or None


async def _load_win_ladders(projections_repo: NBAProjectionsRepository | None, season: str) -> dict[str, WinLadder]:
    """Latest FanDuel X+ wins ladder per team; empty when unavailable."""
    if projections_repo is None:
        return {}
    try:
        rows = await projections_repo.get_latest_win_threshold_probs(season)
    except Exception:
        logger.warning("Loading FanDuel win ladders failed; using the default rating uncertainty", exc_info=True)
        return {}
    return {tc: WinLadder(probs=row["probs"], as_of=row["fetched_at"]) for tc, row in rows.items()}


def _rating_sd(
    schedule: pd.DataFrame,
    ratings: dict[str, float],
    ladders: dict[str, WinLadder],
    stored: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """``(current, preseason)`` rating uncertainty per team (points), from the latest ladders.

    See :mod:`.core.rating_uncertainty`. A team without a ladder keeps its *stored* τ₀,
    else ``DEFAULT_PRESEASON_RATING_SD``; either way it shrinks with games played.
    """
    preseason = preseason_rating_sd(schedule, ladders, ratings, stored=stored)
    return current_rating_sd(schedule, preseason), preseason


@dataclass
class _RegularSeasonRatings:
    """Output of :func:`_regular_season_ratings`."""

    ratings: dict[str, float]
    rating_sd: dict[str, float]
    preseason_sd: dict[str, float]
    fetched_at: datetime | None
    ratings_through: datetime | None


async def _regular_season_ratings(
    schedule: pd.DataFrame,
    *,
    nba_service: NbaDataService,
    projections_repo: NBAProjectionsRepository | None,
    prior: dict[str, float],
    calibrate: bool,
    stored: _StoredTeamState | None = None,
) -> _RegularSeasonRatings:
    """Power ratings and their uncertainty for the regular season.

    Ratings are fit to FanDuel win totals and ESPN BPI projected wins. Targets come from
    :func:`_win_targets`: FanDuel's over probability while its line is current, then (as
    FanDuel pulls lines later in the season) the FanDuel/ESPN blend. *prior* (the last
    stored ratings, else ESPN playoff BPI) is the starting point and holds teams without a
    target. Falls back to *prior* when calibration is skipped (games in progress) or the
    fit fails.

    *prior* first learns from the games finished since the last run (*stored*
    ``ratings_through``; :func:`.core.rating_uncertainty.update_ratings_from_results`), so a
    team no market prices (FanDuel's line pulled, ESPN stale) still tracks its results
    instead of freezing at its last fit. Teams the market prices are refit on top.

    The uncertainty (:func:`_rating_sd`, from FanDuel's X+ wins ladder) is the same the
    simulation samples rating offsets with, so the fit models win distributions as wide as
    the simulation's. It depends mildly on the ratings, so it's redone at the fitted ones
    and the ratings refit once.

    Returns:
        :class:`_RegularSeasonRatings`.
    """
    stored = stored or _StoredTeamState()
    season = nba_service.get_current_season()
    ladders = await _load_win_ladders(projections_repo, season)
    rating_sd, preseason_sd = _rating_sd(schedule, prior, ladders, stored.preseason_sd)
    through = results_cutoff(schedule) or stored.ratings_through
    if stored.ratings_through is not None and through is not None and through > stored.ratings_through:
        prior = update_ratings_from_results(schedule, prior, preseason_sd, stored.ratings_through, through)
    if not calibrate or projections_repo is None:
        return _RegularSeasonRatings(prior, rating_sd, preseason_sd, None, through)
    try:
        fanduel = await projections_repo.get_latest_win_totals(season, "fanduel")
        espn = await projections_repo.get_latest_win_totals(season, "espn_bpi")
        win_totals, projected_wins, fetched_at = _win_targets(fanduel, espn, utc_now())
        calibration = fit_ratings_to_win_totals(
            schedule, win_totals, prior=prior, projected_wins=projected_wins, rating_sd=rating_sd
        )
        rating_sd, preseason_sd = _rating_sd(schedule, calibration.ratings, ladders, stored.preseason_sd)
        calibration = fit_ratings_to_win_totals(
            schedule, win_totals, prior=prior, projected_wins=projected_wins, rating_sd=rating_sd
        )
    except Exception:
        logger.warning("Win-total calibration failed; using prior ratings", exc_info=True)
        return _RegularSeasonRatings(prior, rating_sd, preseason_sd, None, through)
    logger.info(
        "Regular-season ratings fit to %d FanDuel win totals (max over-prob error %.4f) and "
        "%d blended FanDuel/ESPN projections (max error %.2f wins); rating sd median %.2f",
        calibration.n_market_teams,
        calibration.max_abs_error,
        calibration.n_projected_teams,
        calibration.max_abs_wins_error,
        float(np.median(list(rating_sd.values()))) if rating_sd else 0.0,
    )
    return _RegularSeasonRatings(calibration.ratings, rating_sd, preseason_sd, fetched_at, through)


def _simulate_regular_season_phase(
    schedule: pd.DataFrame,
    phase: NBAGameType,
    ratings: dict[str, float] | None = None,
    vegas_odds_fetched_at: datetime | None = None,
    rating_sd: dict[str, float] | None = None,
    playoff_market: dict | None = None,
    preseason_sd: dict[str, float] | None = None,
    stored_playoff_adjustments: dict[str, float] | None = None,
    ratings_through: datetime | None = None,
) -> SimulationOutput:
    game_df = game_probabilities(schedule, ratings or {})
    result = run_regular_season_simulation(
        schedule,
        game_df,
        ratings=ratings,
        rating_sd=rating_sd,
        playoff_market=playoff_market,
        stored_playoff_adjustments=stored_playoff_adjustments,
    )
    completed = schedule[schedule["status"] == NBAGameStatus.FINAL]
    raw_sim = RawSimArrays(
        rs_wins_sim=result.rs_wins_sim,
        po_wins_sim=result.po_wins_sim,
        all_tricodes=result.all_tricodes,
        current_wins=count_wins_from_completed(completed).to_dict(),
        calibrated_ratings=ratings or None,
        vegas_odds_fetched_at=vegas_odds_fetched_at,
        preseason_rating_sd=preseason_sd or {},
        ratings_through=ratings_through,
    )
    return SimulationOutput(
        phase=phase,
        win_stats=result.win_stats,
        seeding=result.seeding,
        play_in_results=None,
        playoff_summary=result.playoff_summary,
        raw_sim=raw_sim,
    )


async def _simulate_postseason_phase(
    schedule: pd.DataFrame,
    phase: NBAGameType,
    *,
    nba_service: NbaDataService,
    projections_repo: NBAProjectionsRepository | None,
    fanduel_futures: dict | None,
    power_ratings: dict | None,
    sim_repo: SimulationResultsRepository | None,
    team_repo: TeamRepository | None,
    calibrate: bool,
) -> SimulationOutput:
    play_in_results = get_play_in_results(schedule, nba_service)
    win_stats, seeding, rs_wins_sim, all_tricodes = run_play_in_simulation(
        schedule, play_in_results, power_ratings=power_ratings
    )

    bracket_state = get_playoff_bracket_state(schedule, nba_service) if phase == NBAGameType.PLAYOFFS else None

    rs_completed = completed_standings_games(schedule)
    calib_raw = compute_raw_seedings(rs_completed, pd.DataFrame(), np.empty((0, 1), dtype=np.float32))

    season = nba_service.get_current_season()
    initial_ratings, stored_vegas_fetched_at = await _load_warm_start_ratings(sim_repo, team_repo, season)

    calibrated_ratings: dict[str, float] = {}
    vegas_odds_fetched_at: datetime | None = None
    if calibrate and calib_raw is not None:
        try:
            if projections_repo is not None:
                vegas_odds_fetched_at = await projections_repo.get_latest_futures_fetched_at()
            if fanduel_futures is None or power_ratings is None:
                if projections_repo is None:
                    raise ValueError("projections_repo is required when fanduel_futures or power_ratings is missing")
                if fanduel_futures is None:
                    fanduel_futures = await projections_repo.get_latest_fanduel_futures()
                if power_ratings is None:
                    power_ratings = await projections_repo.get_latest_playoff_bpi()
            cal: CalibrationResult = calibrate_ratings(
                fanduel_futures,
                power_ratings,
                calib_raw,
                play_in_results=play_in_results,
                bracket_state=bracket_state,
                initial_ratings=initial_ratings,
            )
            calibrated_ratings = cal.ratings
            logger.info(
                "Calibration complete: loss %.5f → %.5f (%d evals, converged=%s)",
                cal.loss_start,
                cal.loss_final,
                cal.n_evals,
                cal.converged,
            )
        except Exception:
            logger.warning("Calibration failed; using uncalibrated power ratings for playoff simulation", exc_info=True)
            calibrated_ratings = dict(power_ratings) if power_ratings else {}
            vegas_odds_fetched_at = None
    elif initial_ratings:
        calibrated_ratings = initial_ratings
        vegas_odds_fetched_at = stored_vegas_fetched_at
        logger.info(
            "Calibration skipped; reusing %d stored power ratings for playoff simulation",
            len(calibrated_ratings),
        )
    else:
        calibrated_ratings = dict(power_ratings) if power_ratings else {}
        logger.info("Calibration skipped; no stored ratings found, using uncalibrated power ratings")

    po_result: PlayoffSimResult = run_playoff_simulation(
        schedule,
        play_in_results=play_in_results,
        bracket_state=bracket_state,
        calibrated_ratings=calibrated_ratings or None,
        power_ratings=power_ratings,
    )
    po_wins_sim = _align_po_to_rs(po_result.po_wins_sim, po_result.all_tricodes, rs_wins_sim, all_tricodes)

    all_completed = schedule[schedule["status"] == NBAGameStatus.FINAL]
    raw_sim = RawSimArrays(
        rs_wins_sim=rs_wins_sim,
        po_wins_sim=po_wins_sim,
        all_tricodes=all_tricodes,
        current_wins=count_wins_from_completed(all_completed).to_dict(),
        po_raw=po_result.raw,
        play_in_results=play_in_results,
        bracket_state=bracket_state,
        calibrated_ratings=calibrated_ratings or None,
        vegas_odds_fetched_at=vegas_odds_fetched_at,
    )
    return SimulationOutput(
        phase=phase,
        win_stats=win_stats,
        seeding=seeding,
        play_in_results=play_in_results,
        playoff_summary=po_result.summary,
        raw_sim=raw_sim,
    )


async def _resolve_power_ratings(
    raw_sim: RawSimArrays,
    nba_teams: list[Team],
    sim_repo: SimulationResultsRepository,
    power_ratings: dict[str, float],
    season: str,
) -> dict[str, float]:
    """Compose final power ratings: input ratings → stored ratings → calibrated ratings (highest priority)."""
    resolved: dict[str, float] = dict(power_ratings)
    if raw_sim.calibrated_ratings:
        resolved.update(raw_sim.calibrated_ratings)
        return resolved

    # Calibration was skipped — try to reuse the most recently stored ratings.
    team_id_to_tricode = {t.id: t.abbreviation for t in nba_teams}
    stored = await sim_repo.get_latest_team_results(season)
    if stored:
        stored_ratings = {
            team_id_to_tricode[r.team_id]: r.power_rating for r in stored if r.team_id in team_id_to_tricode
        }
        resolved.update(stored_ratings)
        logger.info("Calibration skipped; reused %d stored power ratings", len(stored_ratings))
    return resolved


def _build_team_records(
    raw_sim: RawSimArrays,
    win_stats: pd.DataFrame,
    playoff_summary: pd.DataFrame | None,
    power_ratings: dict[str, float],
    tricode_to_team: dict[str, Team],
    *,
    season: str,
    phase_str: str,
    n_sims: int,
    simulated_at: datetime,
) -> list[SimulationTeamResult]:
    rs_means = dict(zip(win_stats["tricode"], win_stats["mean_wins"]))
    po_means: dict[str, float] = {}
    deltas: dict[str, float] = {}
    if playoff_summary is not None and not playoff_summary.empty:
        po_means = dict(zip(playoff_summary["tricode"], playoff_summary["mean_po_wins"]))
        if "playoff_adjustment" in playoff_summary:
            deltas = dict(zip(playoff_summary["tricode"], playoff_summary["playoff_adjustment"].astype(float)))

    records: list[SimulationTeamResult] = []
    for tricode, team in tricode_to_team.items():
        if tricode not in rs_means:
            continue
        records.append(
            SimulationTeamResult(
                season=season,
                phase=phase_str,
                n_sims=n_sims,
                simulated_at=simulated_at,
                team_id=team.id,
                power_rating=power_ratings.get(tricode, 0.0),
                current_wins=raw_sim.current_wins.get(tricode, 0.0),
                projected_wins=rs_means[tricode] + po_means.get(tricode, 0.0),
                preseason_rating_sd=raw_sim.preseason_rating_sd.get(tricode),
                playoff_adjustment=deltas.get(tricode),
                ratings_through=raw_sim.ratings_through,
                vegas_odds_fetched_at=raw_sim.vegas_odds_fetched_at,
            )
        )
    return records


async def _build_roster_records(
    raw_sim: RawSimArrays,
    team_id_to_tricode: dict[uuid.UUID, str],
    roster_repo: RosterRepository,
    roster_slot_repo: RosterSlotRepository,
    *,
    season: str,
    phase_str: str,
    n_sims: int,
    simulated_at: datetime,
) -> list[SimulationRosterResult]:
    rosters = await roster_repo.get_all(season=season)
    if not rosters:
        return []

    slots = await roster_slot_repo.get_all_by_roster_id_in([r.id for r in rosters])
    roster_by_id = {r.id: r for r in rosters}

    rosters_by_pool: dict[uuid.UUID, list] = {}
    for r in rosters:
        rosters_by_pool.setdefault(r.pool_id, []).append(r)

    slots_by_pool: dict[uuid.UUID, list] = {}
    for slot in slots:
        roster = roster_by_id.get(slot.roster_id)
        if roster is not None:
            slots_by_pool.setdefault(roster.pool_id, []).append(slot)

    total_wins_sim = raw_sim.rs_wins_sim + raw_sim.po_wins_sim

    records: list[SimulationRosterResult] = []
    for pool_id, pool_rosters in rosters_by_pool.items():
        pool_slots = slots_by_pool.get(pool_id, [])
        if not pool_slots:
            continue

        tricode_to_roster_name: dict[str, str] = {}
        for slot in pool_slots:
            tc = team_id_to_tricode.get(slot.team_id)
            roster = roster_by_id.get(slot.roster_id)
            if tc is not None and roster is not None:
                tricode_to_roster_name[tc] = roster.name
        if not tricode_to_roster_name:
            continue

        outcomes = compute_pool_outcomes(total_wins_sim, tricode_to_roster_name, raw_sim.all_tricodes)
        roster_name_to_id = {r.name: r.id for r in pool_rosters}

        for _, row in outcomes.iterrows():
            roster_id = roster_name_to_id.get(row["roster"])
            if roster_id is None:
                continue
            records.append(
                SimulationRosterResult(
                    season=season,
                    phase=phase_str,
                    n_sims=n_sims,
                    simulated_at=simulated_at,
                    roster_id=roster_id,
                    pool_id=pool_id,
                    win_pct=float(row["win_pct"]),
                )
            )
    return records


async def save_simulation_results(
    phase: NBAGameType,
    win_stats: pd.DataFrame,
    playoff_summary: pd.DataFrame | None,
    raw_sim: RawSimArrays,
    season: str,
    team_repo: TeamRepository,
    roster_repo: RosterRepository,
    roster_slot_repo: RosterSlotRepository,
    sim_repo: SimulationResultsRepository,
    power_ratings: dict[str, float],
    n_sims: int = N_SIMS,
) -> None:
    """Persist simulation results to the database.

    Writes one ``SimulationTeamResult`` per team and one
    ``SimulationRosterResult`` per roster (across all pools for the season),
    all sharing the same ``simulated_at`` timestamp.
    """
    simulated_at = utc_now()
    phase_str = phase.value

    nba_teams = await team_repo.get_all_by_league_slug(LeagueSlug.NBA)
    tricode_to_team = {t.abbreviation: t for t in nba_teams}
    team_id_to_tricode = {t.id: t.abbreviation for t in nba_teams}

    resolved_ratings = await _resolve_power_ratings(raw_sim, nba_teams, sim_repo, power_ratings, season)

    team_records = _build_team_records(
        raw_sim,
        win_stats,
        playoff_summary,
        resolved_ratings,
        tricode_to_team,
        season=season,
        phase_str=phase_str,
        n_sims=n_sims,
        simulated_at=simulated_at,
    )
    await sim_repo.save_all_team_results(team_records)
    logger.info("Saved %d SimulationTeamResult records for season %s", len(team_records), season)

    roster_records = await _build_roster_records(
        raw_sim,
        team_id_to_tricode,
        roster_repo,
        roster_slot_repo,
        season=season,
        phase_str=phase_str,
        n_sims=n_sims,
        simulated_at=simulated_at,
    )
    await sim_repo.save_all_roster_results(roster_records)
    logger.info("Saved %d SimulationRosterResult records for season %s", len(roster_records), season)


async def run_and_save_simulation(db_session: AsyncSession, *, calibrate: bool = True) -> None:
    """Run the NBA season simulation for the current phase and persist results.

    1. Determines the current season string from the NBA schedule API.
    2. Calls :func:`simulate_nba_season` (warm-starts calibration from stored ratings).
    3. Calls :func:`save_simulation_results` to persist team and roster results.
    """
    nba_service = NbaDataService(
        db_session=db_session,
        external_data_repository=ExternalDataRepository(db_session),
    )
    season = nba_service.get_current_season()

    projections_repo = NBAProjectionsRepository(db_session)
    sim_repo = SimulationResultsRepository(db_session)
    team_repo = TeamRepository(db_session)

    # Use stored calibrated power ratings if available; fall back to ESPN BPI.
    warm_start_ratings, _ = await _load_warm_start_ratings(sim_repo, team_repo, season)
    if warm_start_ratings:
        logger.info("Using %d stored power ratings", len(warm_start_ratings))
        power_ratings = warm_start_ratings
    else:
        logger.info("No stored ratings found; using ESPN playoff BPI as power ratings")
        power_ratings = await projections_repo.get_latest_playoff_bpi()

    output = await simulate_nba_season(
        nba_service,
        projections_repo=projections_repo,
        power_ratings=power_ratings,
        sim_repo=sim_repo,
        team_repo=team_repo,
        calibrate=calibrate,
    )

    await save_simulation_results(
        phase=output.phase,
        win_stats=output.win_stats,
        playoff_summary=output.playoff_summary,
        raw_sim=output.raw_sim,
        season=season,
        team_repo=team_repo,
        roster_repo=RosterRepository(db_session),
        roster_slot_repo=RosterSlotRepository(db_session),
        sim_repo=sim_repo,
        power_ratings=power_ratings,
    )

    logger.info("Simulation completed for season %s phase %s", season, output.phase)


async def fetch_projections(db_session: AsyncSession) -> bool:
    """Fetch fresh FanDuel + ESPN projections and persist them, skipping the simulation.

    If games are currently in progress, skips the fetch entirely to avoid writing
    incomplete futures odds.

    Returns:
        True if the fetch ran (games weren't in progress), False if it was skipped.
    """
    nba_service = NbaDataService(db_session=db_session, external_data_repository=ExternalDataRepository(db_session))
    schedule = get_nba_schedule(nba_service)

    if (schedule["status"] == NBAGameStatus.INGAME).any():
        logger.info("Games in progress — skipping FanDuel/ESPN projections fetch.")
        return False

    team_repo = TeamRepository(db_session)
    projections_repo = NBAProjectionsRepository(db_session)

    vegas_count = await NBAVegasProjectionsService(
        db_session=db_session,
        team_repository=team_repo,
        nba_projections_repository=projections_repo,
    ).write_projections()
    espn_count = await NBAEspnProjectionsService(
        db_session=db_session,
        team_repository=team_repo,
        nba_projections_repository=projections_repo,
    ).write_projections()

    logger.info("FanDuel projections fetch completed. Successfully wrote %d records.", vegas_count)
    logger.info("ESPN BPI projections fetch completed. Successfully wrote %d records.", espn_count)
    return True


async def run_projections_and_simulation(db_session: AsyncSession) -> None:
    """Fetch fresh projections, then run the simulation.

    If games are currently in progress, skips the FanDuel fetch to avoid incomplete
    futures odds and runs without calibration using the most recently stored power
    ratings instead.
    """
    if not await fetch_projections(db_session):
        await run_and_save_simulation(db_session, calibrate=False)
        return

    db_session.expire_all()

    logger.info("Running calibrated simulation with fresh projections...")
    await run_and_save_simulation(db_session, calibrate=True)


async def compare_simulated_vs_market(
    playoff_summary: pd.DataFrame,
    repo: NBAProjectionsRepository,
) -> pd.DataFrame:
    """Compare simulated playoff probabilities against the latest market (FanDuel) odds.

    Returns:
        DataFrame with one row per team that appears in either the simulation
        or the market data, with columns: tricode, conference, seed,
        sim_champ_pct, market_champ_pct, champ_pct_diff, sim_conf_champ_pct,
        market_conf_champ_pct, conf_champ_pct_diff.  Sorted by conference, seed.
    """
    market = await repo.get_latest_fanduel_futures()

    market_df = pd.DataFrame(
        [
            {
                "tricode": tc,
                "market_champ_pct": probs.get("win_finals_prob"),
                "market_conf_champ_pct": probs.get("win_conference_prob"),
            }
            for tc, probs in market.items()
        ]
    )

    if playoff_summary is None or playoff_summary.empty:
        sim_df = pd.DataFrame(columns=["tricode", "conference", "seed", "sim_champ_pct", "sim_conf_champ_pct"])
    else:
        sim_df = playoff_summary[["tricode", "conference", "seed", "champ_pct", "conf_champ_pct"]].rename(
            columns={"champ_pct": "sim_champ_pct", "conf_champ_pct": "sim_conf_champ_pct"}
        )

    merged = sim_df.merge(market_df, on="tricode", how="outer")
    merged["champ_pct_diff"] = merged["sim_champ_pct"] - merged["market_champ_pct"]
    merged["conf_champ_pct_diff"] = merged["sim_conf_champ_pct"] - merged["market_conf_champ_pct"]
    merged = merged.sort_values(["conference", "seed"], na_position="last").reset_index(drop=True)

    return merged[
        [
            "tricode",
            "conference",
            "seed",
            "sim_champ_pct",
            "market_champ_pct",
            "champ_pct_diff",
            "sim_conf_champ_pct",
            "market_conf_champ_pct",
            "conf_champ_pct_diff",
        ]
    ]
