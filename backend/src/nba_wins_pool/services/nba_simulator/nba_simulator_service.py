"""
Main control flow for the NBA simulator service.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

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
from nba_wins_pool.services.nba_simulator.playoff_seeding import compute_raw_seedings
from nba_wins_pool.services.nba_simulator.playoff_sim import PlayoffBracketState
from nba_wins_pool.services.nba_simulator.pool_sim import compute_pool_outcomes
from nba_wins_pool.services.nba_simulator.regular_season_sim import (
    N_SIMS,
    PlayoffSimResult,
    count_wins_from_completed,
    run_play_in_simulation,
    run_playoff_simulation,
    run_regular_season_simulation,
)
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.nba_game_type import NBAGameType
from nba_wins_pool.utils.time import utc_now

logger = logging.getLogger(__name__)


@dataclass
class RawSimArrays:
    """Per-team simulation arrays plus calibration context.

    Always-present fields hold the Monte Carlo arrays needed for pool-outcome
    computation.  Optional fields are populated only in the play-in / playoffs
    phases (calibration runs there).
    """

    rs_wins_sim: np.ndarray  # (n_teams, n_sims) float32 — regular-season wins
    po_wins_sim: np.ndarray  # (n_teams, n_sims) float32 — playoff wins (zeros in RS phase)
    all_tricodes: list[str]  # ordered tricodes matching axis 0 of the arrays
    current_wins: dict[str, float] = field(default_factory=dict)
    # Calibration context — set only in play-in / playoffs phases
    po_raw: dict | None = None
    play_in_results: dict[str, ConferencePlayInResults] | None = None
    bracket_state: PlayoffBracketState | None = None
    calibrated_ratings: dict[str, float] | None = None
    vegas_odds_fetched_at: datetime | None = None


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
    playoff_bpi: dict | None = None,
    sim_repo: SimulationResultsRepository | None = None,
    team_repo: TeamRepository | None = None,
    calibrate: bool = True,
) -> SimulationOutput:
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
        return _simulate_regular_season_phase(schedule, phase)

    return await _simulate_postseason_phase(
        schedule,
        phase,
        nba_service=nba_service,
        projections_repo=projections_repo,
        fanduel_futures=fanduel_futures,
        playoff_bpi=playoff_bpi,
        sim_repo=sim_repo,
        team_repo=team_repo,
        calibrate=calibrate,
    )


def _simulate_regular_season_phase(
    schedule: pd.DataFrame,
    phase: NBAGameType,
) -> SimulationOutput:
    win_stats, seeding, rs_wins_sim, all_tricodes = run_regular_season_simulation(schedule)
    completed = schedule[schedule["status"] == NBAGameStatus.FINAL]
    raw_sim = RawSimArrays(
        rs_wins_sim=rs_wins_sim,
        po_wins_sim=np.zeros_like(rs_wins_sim),
        all_tricodes=all_tricodes,
        current_wins=count_wins_from_completed(completed).to_dict(),
    )
    return SimulationOutput(
        phase=phase,
        win_stats=win_stats,
        seeding=seeding,
        play_in_results=None,
        playoff_summary=None,
        raw_sim=raw_sim,
    )


async def _simulate_postseason_phase(
    schedule: pd.DataFrame,
    phase: NBAGameType,
    *,
    nba_service: NbaDataService,
    projections_repo: NBAProjectionsRepository | None,
    fanduel_futures: dict | None,
    playoff_bpi: dict | None,
    sim_repo: SimulationResultsRepository | None,
    team_repo: TeamRepository | None,
    calibrate: bool,
) -> SimulationOutput:
    play_in_results = get_play_in_results(schedule, nba_service)
    win_stats, seeding, rs_wins_sim, all_tricodes = run_play_in_simulation(
        schedule, play_in_results, playoff_bpi=playoff_bpi
    )

    bracket_state = get_playoff_bracket_state(schedule, nba_service) if phase == NBAGameType.PLAYOFFS else None

    rs_completed = schedule[
        (schedule["status"] == NBAGameStatus.FINAL) & (schedule["game_type"] == NBAGameType.REGULAR_SEASON)
    ]
    calib_raw = compute_raw_seedings(rs_completed, pd.DataFrame(), np.empty((0, 1), dtype=np.float32))

    season = nba_service.get_current_season()
    initial_ratings, stored_vegas_fetched_at = await _load_warm_start_ratings(sim_repo, team_repo, season)

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
            calibrated_ratings = dict(playoff_bpi) if playoff_bpi else {}
            vegas_odds_fetched_at = None
    elif initial_ratings:
        calibrated_ratings = initial_ratings
        vegas_odds_fetched_at = stored_vegas_fetched_at
        logger.info(
            "Calibration skipped; reusing %d stored power ratings for playoff simulation",
            len(calibrated_ratings),
        )
    else:
        logger.info("Calibration skipped; no stored ratings found, falling back to raw ESPN BPI")

    po_result: PlayoffSimResult = run_playoff_simulation(
        schedule,
        play_in_results=play_in_results,
        bracket_state=bracket_state,
        ratings=calibrated_ratings or None,
        playoff_bpi=playoff_bpi,
    )
    po_wins_sim = _align_po_to_rs(po_result.po_wins_sim, po_result.all_tricodes, rs_wins_sim, all_tricodes)

    raw_sim = RawSimArrays(
        rs_wins_sim=rs_wins_sim,
        po_wins_sim=po_wins_sim,
        all_tricodes=all_tricodes,
        current_wins=dict(zip(win_stats["tricode"], win_stats["mean_wins"].astype(float))),
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
    playoff_bpi: dict[str, float],
    season: str,
) -> dict[str, float]:
    """Compose final power ratings: ESPN BPI → stored ratings → calibrated ratings (highest priority)."""
    power_ratings: dict[str, float] = dict(playoff_bpi)
    if raw_sim.calibrated_ratings:
        power_ratings.update(raw_sim.calibrated_ratings)
        return power_ratings

    # Calibration was skipped — try to reuse the most recently stored ratings.
    team_id_to_tricode = {t.id: t.abbreviation for t in nba_teams}
    stored = await sim_repo.get_latest_team_results(season)
    if stored:
        stored_ratings = {
            team_id_to_tricode[r.team_id]: r.power_rating for r in stored if r.team_id in team_id_to_tricode
        }
        power_ratings.update(stored_ratings)
        logger.info("Calibration skipped; reused %d stored power ratings", len(stored_ratings))
    return power_ratings


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
    if playoff_summary is not None and not playoff_summary.empty:
        po_means = dict(zip(playoff_summary["tricode"], playoff_summary["mean_po_wins"]))

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
    playoff_bpi: dict[str, float],
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

    power_ratings = await _resolve_power_ratings(raw_sim, nba_teams, sim_repo, playoff_bpi, season)

    team_records = _build_team_records(
        raw_sim,
        win_stats,
        playoff_summary,
        power_ratings,
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

    # Fetch ESPN playoff BPI once and reuse across calibration + result persistence.
    playoff_bpi = await projections_repo.get_latest_playoff_bpi()

    output = await simulate_nba_season(
        nba_service,
        projections_repo=projections_repo,
        playoff_bpi=playoff_bpi,
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
        playoff_bpi=playoff_bpi,
    )

    logger.info("Simulation completed for season %s phase %s", season, output.phase)


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
