"""
Main control flow for the NBA simulator service.
"""

import logging
import uuid
from datetime import datetime
from typing import TypedDict

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.simulation_results import SimulationRosterResult, SimulationTeamResult
from nba_wins_pool.models.team import LeagueSlug
from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.repositories.roster_repository import RosterRepository
from nba_wins_pool.repositories.roster_slot_repository import RosterSlotRepository
from nba_wins_pool.repositories.simulation_results_repository import SimulationResultsRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_simulator.calibration import (
    CalibrationResult,
    calibrate_ratings,
)
from nba_wins_pool.services.nba_simulator.data import (
    detect_season_phase,
    get_nba_schedule,
    get_play_in_results,
    get_playoff_bracket_state,
)
from nba_wins_pool.services.nba_simulator.play_in_tournament import ConferencePlayInResults
from nba_wins_pool.services.nba_simulator.playoff_sim import PlayoffBracketState
from nba_wins_pool.services.nba_simulator.pool_sim import compute_pool_outcomes
from nba_wins_pool.services.nba_simulator.regular_season_sim import (
    N_SIMS,
    run_play_in_simulation,
    run_playoff_simulation,
    run_regular_season_simulation,
)
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.nba_game_type import NBAGameType
from nba_wins_pool.utils.time import utc_now

logger = logging.getLogger(__name__)


class RawSimArrays(TypedDict, total=False):
    """Raw per-team simulation arrays and calibration context."""

    rs_wins_sim: np.ndarray  # (n_teams, n_sims) float32 — regular-season wins
    po_wins_sim: np.ndarray  # (n_teams, n_sims) float32 — playoff wins (zeros in RS phase)
    all_tricodes: list[str]  # ordered tricodes matching axis 0 of the arrays
    # Calibration context — present only in play-in / playoffs phases
    po_raw: dict  # compute_raw_seedings() dict required by calibrate_ratings()
    play_in_results: dict[str, ConferencePlayInResults] | None
    bracket_state: PlayoffBracketState | None
    calibrated_ratings: dict[str, float]  # tricode → calibrated power rating (post-optimizer)
    vegas_odds_fetched_at: datetime | None  # fetched_at of the Vegas odds used for calibration


async def simulate_nba_season(
    projections_repo: NBAProjectionsRepository | None = None,
    *,
    fanduel_futures: dict | None = None,
    playoff_bpi: dict | None = None,
    sim_repo: SimulationResultsRepository | None = None,
    team_repo: TeamRepository | None = None,
    calibrate: bool = True,
) -> tuple[
    NBAGameType,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, ConferencePlayInResults] | None,
    pd.DataFrame | None,
    RawSimArrays,
]:
    """Run the NBA season simulation appropriate for the current phase.

    Fetches the schedule once, detects the season phase from upcoming (PREGAME)
    games, and dispatches to the right simulators:

    - **Regular season** — Monte Carlo projection of remaining regular-season
      games.  No playoff simulation is run.
    - **Play-in** — Actual regular-season standings used as the starting point.
      Remaining play-in games are simulated; the resulting seed-7/8 uncertainty
      propagates into the full playoff bracket simulation.
    - **Playoffs** — All regular-season and play-in results are locked in.
      Known series results and FanDuel odds for in-progress series are loaded
      from the NBA bracket API and used to constrain the playoff simulation.

    For play-in and playoffs phases, the Nelder-Mead optimizer always runs to
    calibrate per-team power ratings against FanDuel implied championship /
    conference-win probabilities fetched from the database.  The calibrated
    ratings are used inside ``simulate_playoffs`` and stored in ``raw_sim``
    under the ``calibrated_ratings`` key.

    When *sim_repo* and *team_repo* are both provided, the most recently stored
    per-team power ratings are loaded from the database to warm-start the
    Nelder-Mead calibration optimiser.  Falls back to ESPN BPI (cold start)
    when they are ``None`` or no stored results exist.

    Args:
        projections_repo: Repository for fetching FanDuel futures and ESPN
            playoff BPI from the database.  May be ``None`` when pre-fetched
            *fanduel_futures* and *playoff_bpi* are supplied directly.
        fanduel_futures: Pre-fetched FanDuel futures dict (tricode → probs).
            When provided together with *playoff_bpi*, *projections_repo* is
            not required and no DB fetch occurs during calibration.
        playoff_bpi: Pre-fetched ESPN playoff BPI dict (tricode → rating).
            When provided together with *fanduel_futures*, *projections_repo*
            is not required.
        sim_repo: Repository for loading the most recent stored simulation
            results.  Used to warm-start the Nelder-Mead calibration optimiser.
        team_repo: Repository for loading NBA teams (needed to map team IDs to
            tricodes when building warm-start ratings).
        calibrate: When ``True`` (default), runs the Nelder-Mead optimiser to
            calibrate per-team power ratings against FanDuel market odds before
            the playoff simulation.  Set to ``False`` to skip calibration and
            use raw ESPN BPI ratings instead (faster, useful for development).

    Returns:
        6-tuple of ``(phase, win_stats, seeding, play_in_results, playoff_summary, raw_sim)``.

        *phase* — the detected ``NBAGameType``.

        *win_stats* — one row per team with columns tricode, mean_wins
        (projected regular-season wins).

        *seeding* — one row per team with seed probabilities per conference
        (mean_seed, seed_N_pct, playoff_pct, etc.).

        *play_in_results* — dict mapping ``"East"`` / ``"West"`` to
        ``ConferencePlayInResults`` with completed game winners filled in,
        or ``None`` when not in the play-in / playoffs phase.

        *playoff_summary* — DataFrame with one row per team and columns
        tricode, conference, seed, champ_pct, conf_champ_pct, mean_po_wins.
        ``None`` during the regular-season phase.

        *raw_sim* — raw per-team simulation arrays for pool-outcome computation.
        Includes ``calibrated_ratings`` when calibration converged.
    """
    schedule = get_nba_schedule()
    phase = detect_season_phase(schedule)

    play_in_results: dict[str, ConferencePlayInResults] | None = None
    bracket_state: PlayoffBracketState | None = None
    playoff_summary: pd.DataFrame | None = None

    if phase == NBAGameType.REGULAR_SEASON:
        win_stats, seeding, rs_wins_sim, all_tricodes = run_regular_season_simulation(schedule)
        po_wins_sim = np.zeros_like(rs_wins_sim)
        completed = schedule[schedule["status"] == NBAGameStatus.FINAL]
        home_w = completed[completed["home_score"] > completed["away_score"]]["home_tricode"].value_counts()
        away_w = completed[completed["away_score"] > completed["home_score"]]["away_tricode"].value_counts()
        current_wins_map: dict[str, float] = home_w.add(away_w, fill_value=0).to_dict()
        raw_sim: RawSimArrays = {
            "rs_wins_sim": rs_wins_sim,
            "po_wins_sim": po_wins_sim,
            "all_tricodes": all_tricodes,
            "current_wins": current_wins_map,
        }
    else:
        play_in_results = get_play_in_results(schedule)
        win_stats, seeding, rs_wins_sim, all_tricodes = run_play_in_simulation(schedule, play_in_results)

        if phase == NBAGameType.PLAYOFFS:
            bracket_state = get_playoff_bracket_state(schedule)

        # Compute raw seedings for the calibration optimizer.
        from nba_wins_pool.services.nba_simulator.playoff_seeding import compute_raw_seedings

        rs_completed = schedule[
            (schedule["status"] == NBAGameStatus.FINAL) & (schedule["game_type"] == NBAGameType.REGULAR_SEASON)
        ]
        calib_raw = compute_raw_seedings(
            rs_completed,
            pd.DataFrame(),
            np.empty((0, 1), dtype=np.float32),
        )

        # Warm-start the calibration optimiser from the most recently stored
        # power ratings; fall back to ESPN BPI (cold start) when none exist.
        initial_ratings: dict[str, float] | None = None
        stored_vegas_fetched_at: datetime | None = None
        stored_team_results = []
        if sim_repo is not None and team_repo is not None:
            from nba_wins_pool.services.nba_simulator.data import _make_service

            season: str = _make_service().get_current_season()
            stored_team_results = await sim_repo.get_latest_team_results(season)
            if stored_team_results:
                nba_teams = await team_repo.get_all_by_league_slug(LeagueSlug.NBA)
                team_id_to_tricode = {t.id: t.abbreviation for t in nba_teams}
                initial_ratings = {
                    team_id_to_tricode[r.team_id]: r.power_rating
                    for r in stored_team_results
                    if r.team_id in team_id_to_tricode
                }
                stored_vegas_fetched_at = stored_team_results[0].vegas_odds_fetched_at
                logger.info("Loaded %d stored power ratings for warm-start calibration", len(initial_ratings))

        calibrated_ratings: dict[str, float] = {}
        vegas_odds_fetched_at: datetime | None = None
        if calibrate and calib_raw is not None:
            try:
                if projections_repo is not None:
                    vegas_odds_fetched_at = await projections_repo.get_latest_futures_fetched_at()
                cal: CalibrationResult = await calibrate_ratings(
                    repo=projections_repo,
                    raw=calib_raw,
                    play_in_results=play_in_results,
                    bracket_state=bracket_state,
                    fanduel_futures=fanduel_futures,
                    playoff_bpi=playoff_bpi,
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
                logger.warning("Calibration failed; using raw ESPN BPI for playoff simulation", exc_info=True)
                vegas_odds_fetched_at = None
        elif not calibrate:
            if initial_ratings:
                calibrated_ratings = initial_ratings
                vegas_odds_fetched_at = stored_vegas_fetched_at
                logger.info(
                    "Calibration skipped; reusing %d stored power ratings for playoff simulation",
                    len(calibrated_ratings),
                )
            else:
                logger.info("Calibration skipped; no stored ratings found, falling back to raw ESPN BPI")

        playoff_summary, po_wins_sim, po_tricodes, po_raw = run_playoff_simulation(
            schedule,
            play_in_results=play_in_results,
            bracket_state=bracket_state,
            ratings=calibrated_ratings or None,
        )

        # Align po_wins_sim to all_tricodes from the RS simulation
        if po_tricodes != all_tricodes and len(po_wins_sim) > 0:
            po_idx = {tc: i for i, tc in enumerate(po_tricodes)}
            aligned = np.zeros_like(rs_wins_sim)
            for i, tc in enumerate(all_tricodes):
                j = po_idx.get(tc)
                if j is not None:
                    aligned[i] = po_wins_sim[j]
            po_wins_sim = aligned

        raw_sim = {
            "rs_wins_sim": rs_wins_sim,
            "po_wins_sim": po_wins_sim,
            "all_tricodes": all_tricodes,
            "po_raw": po_raw,
            "play_in_results": play_in_results,
            "bracket_state": bracket_state,
            "current_wins": dict(zip(win_stats["tricode"], win_stats["mean_wins"].astype(float))),
        }
        if calibrated_ratings:
            raw_sim["calibrated_ratings"] = calibrated_ratings
        if vegas_odds_fetched_at is not None:
            raw_sim["vegas_odds_fetched_at"] = vegas_odds_fetched_at

    return phase, win_stats, seeding, play_in_results, playoff_summary, raw_sim


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
    projections_repo: NBAProjectionsRepository,
    n_sims: int = N_SIMS,
) -> None:
    """Persist simulation results to the database.

    Writes one ``SimulationTeamResult`` per team and one
    ``SimulationRosterResult`` per roster (across all pools for the season),
    all sharing the same ``simulated_at`` timestamp.

    Args:
        phase: Detected season phase from ``simulate_nba_season()``.
        win_stats: Per-team regular-season win projections (tricode, mean_wins).
        playoff_summary: Per-team playoff projections, or ``None`` in the
            regular-season phase.
        raw_sim: Raw simulation arrays returned by ``simulate_nba_season()``.
        season: Season string in format YYYY-YY (e.g. ``"2024-25"``).
        team_repo: Repository for team lookups.
        roster_repo: Repository for roster lookups.
        roster_slot_repo: Repository for roster slot lookups.
        sim_repo: Repository for writing simulation results.
        projections_repo: Repository for fetching ESPN BPI power ratings.
        n_sims: Number of Monte Carlo trials used in this run.
    """
    simulated_at: datetime = utc_now()
    phase_str = phase.value  # e.g. "Regular Season", "Playoffs"

    # --- Team results -----------------------------------------------------------

    nba_teams = await team_repo.get_all_by_league_slug(LeagueSlug.NBA)
    tricode_to_team = {t.abbreviation: t for t in nba_teams}

    # Power rating priority: calibrated from this run → stored calibrated from DB → raw ESPN BPI.
    bpi_ratings: dict[str, float] = await projections_repo.get_latest_playoff_bpi()
    power_ratings: dict[str, float] = dict(bpi_ratings)
    calibrated = raw_sim.get("calibrated_ratings")
    if calibrated:
        power_ratings.update(calibrated)
    else:
        # Calibration was skipped — reuse the most recently stored ratings from a prior run.
        team_id_to_tricode_pre = {t.id: t.abbreviation for t in nba_teams}
        stored = await sim_repo.get_latest_team_results(season)
        if stored:
            stored_ratings = {
                team_id_to_tricode_pre[r.team_id]: r.power_rating for r in stored if r.team_id in team_id_to_tricode_pre
            }
            power_ratings.update(stored_ratings)
            logger.info("Calibration skipped; reused %d stored power ratings", len(stored_ratings))

    po_means: dict[str, float] = {}
    if playoff_summary is not None and not playoff_summary.empty:
        po_means = dict(zip(playoff_summary["tricode"], playoff_summary["mean_po_wins"]))

    rs_means: dict[str, float] = dict(zip(win_stats["tricode"], win_stats["mean_wins"]))
    current_wins_map: dict[str, float] = raw_sim.get("current_wins", {})
    vegas_odds_fetched_at: datetime | None = raw_sim.get("vegas_odds_fetched_at")

    team_records: list[SimulationTeamResult] = []
    for tricode, team in tricode_to_team.items():
        if tricode not in rs_means:
            continue
        team_records.append(
            SimulationTeamResult(
                season=season,
                phase=phase_str,
                n_sims=n_sims,
                simulated_at=simulated_at,
                team_id=team.id,
                power_rating=power_ratings.get(tricode, 0.0),
                current_wins=current_wins_map.get(tricode, 0.0),
                projected_wins=rs_means[tricode] + po_means.get(tricode, 0.0),
                vegas_odds_fetched_at=vegas_odds_fetched_at,
            )
        )

    await sim_repo.save_all_team_results(team_records)
    logger.info("Saved %d SimulationTeamResult records for season %s", len(team_records), season)

    # --- Roster results ---------------------------------------------------------

    rosters = await roster_repo.get_all(season=season)
    if not rosters:
        return

    roster_ids = [r.id for r in rosters]
    slots = await roster_slot_repo.get_all_by_roster_id_in(roster_ids)

    # Build lookup maps
    team_id_to_tricode: dict[uuid.UUID, str] = {t.id: t.abbreviation for t in nba_teams}
    roster_by_id = {r.id: r for r in rosters}

    # Group rosters by pool_id
    rosters_by_pool: dict[uuid.UUID, list] = {}
    for r in rosters:
        rosters_by_pool.setdefault(r.pool_id, []).append(r)

    # Build tricode → roster.name mapping per pool (a team can only be in one roster per pool)
    slots_by_pool: dict[uuid.UUID, list] = {}
    for slot in slots:
        roster = roster_by_id.get(slot.roster_id)
        if roster is not None:
            slots_by_pool.setdefault(roster.pool_id, []).append(slot)

    # Pre-build tricode-indexed mean wins for roster aggregation
    all_tricodes = raw_sim["all_tricodes"]
    rs_wins_sim = raw_sim["rs_wins_sim"]
    po_wins_sim = raw_sim["po_wins_sim"]
    total_wins_sim = rs_wins_sim + po_wins_sim

    roster_records: list[SimulationRosterResult] = []

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

        pool_outcomes = compute_pool_outcomes(total_wins_sim, tricode_to_roster_name, all_tricodes)

        roster_name_to_id = {r.name: r.id for r in pool_rosters}

        for _, row in pool_outcomes.iterrows():
            name = row["roster"]
            roster_id = roster_name_to_id.get(name)
            if roster_id is None:
                continue
            roster_records.append(
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

    await sim_repo.save_all_roster_results(roster_records)
    logger.info("Saved %d SimulationRosterResult records for season %s", len(roster_records), season)


async def run_and_save_simulation(db_session: AsyncSession, *, calibrate: bool = True) -> None:
    """Run the NBA season simulation for the current phase and persist results.

    Orchestrates the full simulation pipeline in one call:

    1. Determines the current season string from the NBA schedule API.
    2. Calls :func:`simulate_nba_season` to run the Monte Carlo simulation
       (warm-starts the Nelder-Mead calibration optimiser from stored ratings).
    3. Calls :func:`save_simulation_results` to persist team and roster results.

    Args:
        db_session: Active async database session used for all repository calls.
        calibrate: When ``True`` (default), runs the Nelder-Mead optimiser to
            calibrate per-team power ratings against FanDuel market odds.
            Set to ``False`` to reuse the last stored power ratings instead
            (faster; useful when odds haven't changed).
    """
    from nba_wins_pool.services.nba_simulator.data import _make_service

    season: str = _make_service().get_current_season()

    projections_repo = NBAProjectionsRepository(db_session)
    sim_repo = SimulationResultsRepository(db_session)
    team_repo = TeamRepository(db_session)

    phase, win_stats, _seeding, _play_in, playoff_summary, raw_sim = await simulate_nba_season(
        projections_repo=projections_repo,
        sim_repo=sim_repo,
        team_repo=team_repo,
        calibrate=calibrate,
    )

    await save_simulation_results(
        phase=phase,
        win_stats=win_stats,
        playoff_summary=playoff_summary,
        raw_sim=raw_sim,
        season=season,
        team_repo=team_repo,
        roster_repo=RosterRepository(db_session),
        roster_slot_repo=RosterSlotRepository(db_session),
        sim_repo=sim_repo,
        projections_repo=projections_repo,
    )

    logger.info("Simulation completed for season %s phase %s", season, phase)


async def compare_simulated_vs_market(
    playoff_summary: pd.DataFrame,
    repo: NBAProjectionsRepository,
) -> pd.DataFrame:
    """Compare simulated playoff probabilities against the latest market (FanDuel) odds.

    Fetches the most recent FanDuel ``win_finals_prob`` (title) and
    ``win_conference_prob`` (conference champion) for every team from the
    database, then joins them against the simulation output so that each row
    shows both the simulated estimate and the implied market probability with
    their difference.

    Args:
        playoff_summary: DataFrame returned by ``simulate_nba_season()`` (the
            fifth element of the tuple).  Expected columns: ``tricode``,
            ``conference``, ``seed``, ``champ_pct``, ``conf_champ_pct``.
            Pass an empty DataFrame (or ``None``) when the simulation was run
            in the regular-season phase and no playoff summary is available.
        repo: ``NBAProjectionsRepository`` instance for DB access.

    Returns:
        DataFrame with one row per team that appears in either the simulation
        or the market data, with columns:

        - *tricode*
        - *conference*
        - *seed* — regular-season conference seed (NaN for non-playoff teams)
        - *sim_champ_pct* — simulated championship probability
        - *market_champ_pct* — FanDuel implied title probability
        - *champ_pct_diff* — ``sim_champ_pct - market_champ_pct``
        - *sim_conf_champ_pct* — simulated conference champion probability
        - *market_conf_champ_pct* — FanDuel implied conference-win probability
        - *conf_champ_pct_diff* — ``sim_conf_champ_pct - market_conf_champ_pct``

        Rows are sorted by *conference* then *seed*.  Teams with no market
        data will have ``NaN`` in the market and diff columns; teams with no
        simulation data (e.g. regular-season phase) will have ``NaN`` in the
        sim columns.
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
