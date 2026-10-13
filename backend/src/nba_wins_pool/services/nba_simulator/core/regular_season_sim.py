import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from nba_wins_pool.services.nba_simulator.core.calibration import build_ratings_array, fit_playoff_adjustments
from nba_wins_pool.services.nba_simulator.core.game_probability import (
    RatingOffsets,
    per_sim_home_prob,
    per_sim_ratings,
)
from nba_wins_pool.services.nba_simulator.core.nba_cup import is_cup_championship, simulate_cup
from nba_wins_pool.services.nba_simulator.core.play_in_tournament import (
    ConferencePlayInResults,
    compute_play_in_results,
)
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import build_seeding_df, compute_raw_seedings
from nba_wins_pool.services.nba_simulator.core.playoff_sim import PlayoffBracketState, simulate_playoffs
from nba_wins_pool.services.nba_simulator.core.schedule import GameStatus, GameType

logger = logging.getLogger(__name__)

N_SIMS = 100_000


@dataclass
class PlayoffSimResult:
    """Output of :func:`run_playoff_simulation`."""

    summary: pd.DataFrame
    po_wins_sim: np.ndarray
    all_tricodes: list[str]
    raw: dict


def count_wins_from_completed(completed: pd.DataFrame) -> pd.Series:
    """Count wins per tricode from a DataFrame of FINAL games.

    Returns a Series indexed by tricode named ``"wins"``. Empty when the input
    has no rows.
    """
    home = completed[completed["home_score"] > completed["away_score"]]["home_tricode"].value_counts()
    away = completed[completed["away_score"] > completed["home_score"]]["away_tricode"].value_counts()
    return home.add(away, fill_value=0).rename("wins")


def completed_standings_games(schedule: pd.DataFrame) -> pd.DataFrame:
    """FINAL regular-season games that count in the standings (excludes the NBA Cup Championship)."""
    return schedule[
        (schedule["status"] == GameStatus.FINAL)
        & (schedule["game_type"] == GameType.REGULAR_SEASON)
        & ~is_cup_championship(schedule)
    ]


def extract_fanduel_game_probs(
    schedule: pd.DataFrame,
    game_type: GameType,
) -> dict[tuple[str, str], float]:
    """Build (home_tricode, away_tricode) → home_win_prob map for unfinished games of a given type.

    Includes games in progress, whose market probability is the live one.
    """
    unfinished = schedule[(schedule["status"] != GameStatus.FINAL) & (schedule["game_type"] == game_type)]
    probs: dict[tuple[str, str], float] = {}
    for _, row in unfinished.iterrows():
        prob = row.get("home_win_prob")
        if pd.notna(prob):
            probs[(row["home_tricode"], row["away_tricode"])] = float(prob)
    return probs


_GAME_CHUNK = 128


def _simulate_games(
    game_df: pd.DataFrame,
    n_sims: int = N_SIMS,
    seed: int | None = None,
    rating_offsets: RatingOffsets | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample game outcomes via Monte Carlo.

    With *rating_offsets*, ratings-based games (non-NaN ``rating_margin``) use each simulation's
    shifted ratings; market-priced games keep their probability.

    Returns:
        Tuple of ``(home_wins, uniforms)``, both ``(n_games, n_sims)`` float32.
        *home_wins* is 1.0 if the home team won; *uniforms* are the random numbers that
        decided each outcome (``uniforms < home_win_prob``, per simulation with *rating_offsets*).
    """
    missing = game_df["home_win_prob"].isna()
    if missing.any():
        missing_games = game_df.loc[missing, ["game_code", "home_tricode", "away_tricode"]].to_dict("records")
        raise ValueError(f"Win probabilities missing for {len(missing_games)} game(s): {missing_games}")
    probs = game_df["home_win_prob"].to_numpy(dtype=np.float32)
    rng = np.random.default_rng(seed)
    rand = rng.random((len(game_df), n_sims), dtype=np.float32)
    home_wins = (rand < probs[:, None]).astype(np.float32)
    if rating_offsets is not None and "rating_margin" in game_df:
        rating_rows = np.nonzero(game_df["rating_margin"].notna().to_numpy())[0]
        for start in range(0, len(rating_rows), _GAME_CHUNK):
            rows = rating_rows[start : start + _GAME_CHUNK]
            home_wins[rows] = rand[rows] < per_sim_home_prob(game_df, rows, rating_offsets)
    return home_wins, rand


def _teams_in(*games: pd.DataFrame) -> list[str]:
    """Sorted tricodes playing in any of *games*."""
    teams: set[str] = set()
    for df in games:
        teams |= set(df["home_tricode"]) | set(df["away_tricode"])
    return sorted(teams)


def _build_stats(
    game_df: pd.DataFrame,
    home_wins: np.ndarray,
    current_wins: pd.Series | None = None,
    extra_wins: dict[str, np.ndarray] | None = None,
    teams: list[str] | None = None,
) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    """Aggregate per-team win statistics from game outcomes.

    *extra_wins* (tricode → ``(n_sims,)``) adds wins from games outside *game_df*,
    e.g. NBA Cup games without scheduled matchups. *teams* adds teams with no
    games in *game_df* (e.g. finished their season while others haven't).

    Returns:
        Tuple of (df, team_sim_wins, all_tricodes) where team_sim_wins is the
        raw (n_teams, n_sims) float32 array used for pool-outcome simulation.
    """
    all_tricodes = sorted(set(_teams_in(game_df)) | set(teams or []))
    team_idx = {t: i for i, t in enumerate(all_tricodes)}
    n_teams = len(all_tricodes)
    n_games = len(game_df)

    home_idx = game_df["home_tricode"].map(team_idx).to_numpy()
    away_idx = game_df["away_tricode"].map(team_idx).to_numpy()

    H = np.zeros((n_teams, n_games), dtype=np.float32)
    A = np.zeros((n_teams, n_games), dtype=np.float32)
    H[home_idx, np.arange(n_games)] = 1.0
    A[away_idx, np.arange(n_games)] = 1.0

    team_sim_wins = H @ home_wins + A @ (1.0 - home_wins)

    if current_wins is not None:
        base = np.array([current_wins.get(t, 0) for t in all_tricodes], dtype=np.float32)
        team_sim_wins += base[:, None]

    for tc, wins in (extra_wins or {}).items():
        if tc in team_idx:
            team_sim_wins[team_idx[tc]] += wins

    df = pd.DataFrame(
        {
            "tricode": all_tricodes,
            "mean_wins": team_sim_wins.mean(axis=1),
        }
    )
    return df, team_sim_wins, all_tricodes


def simulate_season(
    game_df: pd.DataFrame,
    current_wins: pd.Series | None = None,
    n_sims: int = N_SIMS,
    seed: int | None = None,
) -> pd.DataFrame:
    """Run a Monte Carlo simulation of remaining NBA regular-season games.

    Uses vectorised NumPy matrix multiplication so thousands of simulations over a
    full remaining schedule (~400 games) completes in well under a second.

    Args:
        game_df: DataFrame produced by :func:`.game_probability.game_probabilities` with at
            least columns ``home_tricode``, ``away_tricode``, ``home_win_prob`` (no NaNs).
        current_wins: Optional Series mapping tricode -> wins already recorded
            in completed games.  Teams absent from this series are assumed to
            have 0 current wins.
        n_sims: Number of Monte Carlo trials.
        seed: Optional integer seed for reproducibility.

    Returns:
        DataFrame with one row per team and columns: tricode, mean_wins.
        All win figures include ``current_wins`` when provided.
    """
    if game_df.empty:
        return pd.DataFrame(columns=["tricode", "mean_wins"])

    home_wins, _ = _simulate_games(game_df, n_sims, seed)
    df, _, _ = _build_stats(game_df, home_wins, current_wins)
    return df


@dataclass
class RegularSeasonSimResult:
    """Output of :func:`run_regular_season_simulation`. Arrays are indexed by *all_tricodes*."""

    win_stats: pd.DataFrame
    seeding: pd.DataFrame
    rs_wins_sim: np.ndarray
    po_wins_sim: np.ndarray
    all_tricodes: list[str]
    playoff_summary: pd.DataFrame


def _align_rows(arr: np.ndarray, from_tricodes: list[str], to_tricodes: list[str]) -> np.ndarray:
    """Reorder rows of a ``(n_teams, n_sims)`` array; teams missing from *from_tricodes* get zeros."""
    if from_tricodes == to_tricodes:
        return arr
    idx = {tc: i for i, tc in enumerate(from_tricodes)}
    out = np.zeros((len(to_tricodes), arr.shape[1]), dtype=arr.dtype)
    for i, tc in enumerate(to_tricodes):
        if tc in idx:
            out[i] = arr[idx[tc]]
    return out


def _simulate_postseason_from_seeds(
    raw: dict,
    ratings: dict[str, float] | None,
    n_sims: int,
    seed: int | None,
    rating_offsets: RatingOffsets | None = None,
    playoff_adjustments: dict[str, float] | None = None,
) -> tuple[np.ndarray, pd.DataFrame]:
    """Build the play-in and playoff brackets from each simulation's seeds and play them out.

    The play-in uses *ratings*; the playoff series use *ratings* plus *playoff_adjustments*
    (see :func:`.calibration.fit_playoff_adjustments`), with the same per-simulation offsets.

    Nothing is known about the postseason yet, so every play-in game and series
    is simulated (no NBA.com bracket state).

    Returns:
        ``(po_wins, summary)``: play-in + playoff wins ``(n_teams, n_sims)`` indexed by
        ``raw["all_tricodes"]``, and a per-team summary DataFrame.
    """
    if not ratings:
        raise ValueError("Power ratings are required to simulate the play-in and playoffs.")
    n_teams = raw["n_teams"]
    play_in_wins = np.zeros((n_teams, n_sims), dtype=np.float32)
    offsets = rating_offsets.for_tricodes(raw["all_tricodes"]) if rating_offsets is not None else None
    play_in_7, play_in_8 = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=raw["seeds"],
        n_teams=n_teams,
        n_sims=n_sims,
        rng=np.random.default_rng(seed),
        power_ratings=ratings,
        team_idx=raw["team_idx"],
        wins_out=play_in_wins,
        rating_offsets=offsets,
    )
    playoff_wins, champion, east_champion, west_champion = simulate_playoffs(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=raw["seeds"],
        total_wins=raw["total_wins"],
        n_teams=n_teams,
        n_sims=n_sims,
        rng=np.random.default_rng(seed + 1 if seed is not None else None),
        ratings=per_sim_ratings(
            build_ratings_array(ratings, raw["all_tricodes"])
            + build_ratings_array(playoff_adjustments or {}, raw["all_tricodes"]),
            raw["all_tricodes"],
            rating_offsets,
        ),
        team_idx=raw["team_idx"],
        play_in_7=play_in_7,
        play_in_8=play_in_8,
    )
    po_wins = (playoff_wins + play_in_wins).astype(np.float32)

    champ_pct = np.bincount(champion, minlength=n_teams) / n_sims
    conf_champ_pct = (
        np.bincount(east_champion, minlength=n_teams) + np.bincount(west_champion, minlength=n_teams)
    ) / n_sims
    summary = pd.DataFrame(
        {
            "tricode": raw["all_tricodes"],
            "conference": [raw["team_meta"][tc]["conference"] for tc in raw["all_tricodes"]],
            "seed": np.median(raw["seeds"], axis=1).astype(int),
            "champ_pct": champ_pct,
            "conf_champ_pct": conf_champ_pct,
            "mean_po_wins": po_wins.mean(axis=1),
            "playoff_adjustment": [float((playoff_adjustments or {}).get(tc, 0.0)) for tc in raw["all_tricodes"]],
        }
    )
    return po_wins, summary


def run_regular_season_simulation(
    schedule: pd.DataFrame,
    game_df: pd.DataFrame,
    n_sims: int = N_SIMS,
    seed: int | None = None,
    tiebreaker_counts: dict | None = None,
    ratings: dict[str, float] | None = None,
    rating_sd: dict[str, float] | None = None,
    playoff_market: dict | None = None,
    stored_playoff_adjustments: dict[str, float] | None = None,
) -> RegularSeasonSimResult:
    """Simulate the rest of the season from the regular season through the Finals.

    Derives current win totals from completed games, samples the unfinished
    (upcoming or in-progress) games in *game_df*, and determines conference
    seedings using the official NBA tiebreaker procedures. Each simulation's seeds then feed our own
    play-in and playoff brackets (NBA.com brackets are only used once the
    play-in / playoff phase starts; see :func:`run_play_in_simulation`).

    NBA Cup games without scheduled matchups (knockouts and the games they
    decide) are simulated by :func:`nba_cup.simulate_cup`. Their wins count
    toward *rs_wins_sim*; all but the Championship also count toward seeding.

    Args:
        schedule: Full season schedule (see :mod:`core.schedule` for columns).
        game_df: Upcoming regular-season games to sample, with ``game_id``,
            ``game_code``, ``home_tricode``, ``away_tricode`` and ``home_win_prob``
            (no NaNs). An NBA Cup Championship row is ignored; it's simulated
            with the Cup.
        n_sims: Number of Monte Carlo trials.
        seed: Optional integer seed for reproducibility.
        ratings: Tricode → power rating, used for NBA Cup games without
            scheduled matchups and for the play-in and playoffs.
        rating_sd: Tricode → rating uncertainty in points (see
            :mod:`.rating_uncertainty`). Each simulation shifts every team's rating
            once, ``rating + N(0, sd²)``, for all of its ratings-based games:
            regular season (needs *game_df*'s ``rating_margin``), NBA Cup, play-in and
            playoffs. ``None`` uses the ratings as-is.
        playoff_market: FanDuel futures by tricode (``get_latest_fanduel_futures()``). When
            given, our playoff series use each team's rating plus a playoff adjustment fit
            to its championship and conference prices
            (:func:`.calibration.fit_playoff_adjustments`); otherwise the ratings as-is.
        stored_playoff_adjustments: The last run's adjustments by tricode, used as they are
            when there's no *playoff_market* (stale or missing futures) or its fit fails, so
            playoff odds don't jump back to the regular-season ratings.

    Returns:
        :class:`RegularSeasonSimResult`. Pool wins per simulation are
        ``rs_wins_sim + po_wins_sim``.
    """
    completed = schedule[schedule["status"] == GameStatus.FINAL]
    current_wins = count_wins_from_completed(completed)
    standings_completed = completed[~is_cup_championship(completed)]

    rs_game_ids = schedule.loc[
        (schedule["game_type"] == GameType.REGULAR_SEASON) & ~is_cup_championship(schedule), "game_id"
    ]
    game_df = game_df[game_df["game_id"].isin(rs_game_ids)].reset_index(drop=True)

    rating_offsets = None
    if rating_sd and any(sd > 0 for sd in rating_sd.values()):
        rating_offsets = RatingOffsets.sample(
            rating_sd,
            n_sims,
            np.random.default_rng(seed + 5 if seed is not None else None),
        )

    teams = _teams_in(standings_completed, game_df)

    if game_df.empty:
        all_tricodes = teams
        rs_wins_sim = np.array([[current_wins.get(tc, 0)] * n_sims for tc in all_tricodes], dtype=np.float32)
        stats = pd.DataFrame(
            {
                "tricode": all_tricodes,
                "mean_wins": [float(current_wins.get(tc, 0)) for tc in all_tricodes],
            }
        )
        home_wins_sim = np.empty((0, n_sims), dtype=np.float32)
        standings_extra_wins = None
    else:
        home_wins_sim, uniforms = _simulate_games(game_df, n_sims, seed, rating_offsets=rating_offsets)
        cup = simulate_cup(
            schedule,
            game_df,
            home_wins_sim,
            uniforms,
            ratings,
            n_sims,
            seed=seed + 2 if seed is not None else None,
            rating_offsets=rating_offsets,
        )
        stats, rs_wins_sim, all_tricodes = _build_stats(
            game_df,
            home_wins_sim,
            current_wins,
            extra_wins=cup.pool_wins_by_tricode() if cup else None,
            teams=teams,
        )
        all_tricodes = list(all_tricodes)
        standings_extra_wins = cup.standings_wins_by_tricode() if cup else None

    raw = compute_raw_seedings(
        standings_completed,
        game_df,
        home_wins_sim,
        seed=seed + 1 if seed is not None else None,
        tiebreaker_counts=tiebreaker_counts,
        extra_wins=standings_extra_wins,
    )
    if raw is None:
        empty = np.zeros_like(rs_wins_sim)
        return RegularSeasonSimResult(stats, pd.DataFrame(), rs_wins_sim, empty, all_tricodes, pd.DataFrame())

    playoff_adjustments = None
    if playoff_market and ratings:
        offsets = rating_offsets.for_tricodes(raw["all_tricodes"]) if rating_offsets is not None else None
        try:
            playoff_adjustments = fit_playoff_adjustments(
                raw, ratings, playoff_market, rating_offsets=offsets
            ).adjustments
        except Exception:
            logger.warning("Playoff adjustment fit failed; using the last stored adjustments", exc_info=True)
    if not playoff_adjustments and stored_playoff_adjustments:
        playoff_adjustments = dict(stored_playoff_adjustments)
        logger.info("No current FanDuel futures: reusing %d stored playoff adjustments", len(playoff_adjustments))
    po_wins, playoff_summary = _simulate_postseason_from_seeds(
        raw,
        ratings,
        n_sims,
        seed=seed + 3 if seed is not None else None,
        rating_offsets=rating_offsets,
        playoff_adjustments=playoff_adjustments,
    )
    return RegularSeasonSimResult(
        win_stats=stats,
        seeding=build_seeding_df(raw),
        rs_wins_sim=rs_wins_sim,
        po_wins_sim=_align_rows(po_wins, list(raw["all_tricodes"]), all_tricodes),
        all_tricodes=all_tricodes,
        playoff_summary=playoff_summary,
    )


def run_play_in_simulation(
    schedule: pd.DataFrame,
    play_in_results: dict[str, ConferencePlayInResults] | None = None,
    power_ratings: dict[str, float] | None = None,
    n_sims: int = N_SIMS,
    seed: int | None = None,
    tiebreaker_counts: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, list[str]]:
    """Simulate the play-in tournament from finalized regular season standings.

    The regular season is over, so actual win totals and conference seeds are
    derived deterministically from completed regular-season games and broadcast
    across all simulations.  Only the remaining play-in games — those whose
    winner is ``None`` in *play_in_results* — are sampled via Monte Carlo.

    This function is also used for the playoffs phase, where all play-in games
    are already complete and every seed is deterministic.

    Args:
        schedule: Full season schedule from ``data.get_nba_schedule()``.
        play_in_results: Known play-in outcomes from ``data.get_play_in_results()``.
            ``None`` entries in each ``ConferencePlayInResults`` are simulated.
            Pass ``None`` to simulate all play-in games.
        power_ratings: Tricode → power rating for play-in games without market odds.
        n_sims: Number of Monte Carlo trials.
        seed: Optional RNG seed for reproducibility.

    Returns:
        Tuple of ``(win_stats, seeding, rs_wins_sim, all_tricodes)`` matching
        the format of ``run_regular_season_simulation``.  *win_stats* contains actual
        regular-season win totals (plus the Cup Championship) because those outcomes
        are final.  *rs_wins_sim* is a broadcast of those totals across all simulations.
        Play-in wins (played or not) are counted by :func:`run_playoff_simulation`
        in its postseason wins, not here.
    """
    rs_completed = completed_standings_games(schedule)
    cup_final_wins = count_wins_from_completed(
        schedule[(schedule["status"] == GameStatus.FINAL) & is_cup_championship(schedule)]
    )

    actual_wins = count_wins_from_completed(rs_completed).add(cup_final_wins, fill_value=0)

    win_stats = pd.DataFrame(
        {
            "tricode": actual_wins.index,
            "mean_wins": actual_wins.values.astype(float),
        }
    )

    raw = compute_raw_seedings(
        rs_completed,
        pd.DataFrame(),
        np.empty((0, 1), dtype=np.float32),
        seed=seed,
        tiebreaker_counts=tiebreaker_counts,
    )
    if raw is None:
        return win_stats, pd.DataFrame(), np.empty((0, n_sims), dtype=np.float32), []

    seeds = np.repeat(raw["seeds"], n_sims, axis=1)
    total_wins = np.repeat(raw["total_wins"], n_sims, axis=1)
    pool_wins = (
        total_wins + np.array([cup_final_wins.get(tc, 0) for tc in raw["all_tricodes"]], dtype=np.float32)[:, None]
    )

    fanduel_game_probs = extract_fanduel_game_probs(schedule, GameType.PLAY_IN)

    rng = np.random.default_rng(seed + 1 if seed is not None else None)
    play_in_7, play_in_8 = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds,
        n_teams=raw["n_teams"],
        n_sims=n_sims,
        rng=rng,
        power_ratings=power_ratings or {},
        team_idx=raw["team_idx"],
        play_in_results=play_in_results,
        fanduel_game_probs=fanduel_game_probs or None,
    )

    actual_seeds = raw["seeds"]
    is_div_winner = raw["is_div_winner"]
    team_meta = raw["team_meta"]

    rows = []
    for i, tricode in enumerate(raw["all_tricodes"]):
        conf = team_meta[tricode]["conference"]
        n_conf = len(raw["east_teams"]) if conf == "East" else len(raw["west_teams"])
        actual_seed = int(actual_seeds[i, 0])

        row: dict = {
            "tricode": tricode,
            "conference": conf,
            "division": team_meta[tricode]["division"],
            "mean_seed": float(actual_seed),
            "median_seed": float(actual_seed),
        }
        for k in range(1, n_conf + 1):
            if k == 7:
                row[f"seed_{k}_pct"] = float(play_in_7[i].mean())
            elif k == 8:
                row[f"seed_{k}_pct"] = float(play_in_8[i].mean())
            else:
                row[f"seed_{k}_pct"] = 1.0 if actual_seed == k else 0.0

        if actual_seed <= 6:
            row["playoff_pct"] = 1.0
        elif actual_seed <= 10:
            row["playoff_pct"] = float(play_in_7[i].mean() + play_in_8[i].mean())
        else:
            row["playoff_pct"] = 0.0
        row["play_in_pct"] = 1.0 if 7 <= actual_seed <= 10 else 0.0
        row["lottery_pct"] = 1.0 if actual_seed >= 11 else 0.0
        row["div_winner_pct"] = float(is_div_winner[i, 0])

        rows.append(row)

    return win_stats, pd.DataFrame(rows), pool_wins, list(raw["all_tricodes"])


def run_playoff_simulation(
    schedule: pd.DataFrame,
    play_in_results: dict[str, ConferencePlayInResults] | None = None,
    bracket_state: PlayoffBracketState | None = None,
    calibrated_ratings: dict[str, float] | None = None,
    power_ratings: dict[str, float] | None = None,
    n_sims: int = N_SIMS,
    seed: int | None = None,
) -> PlayoffSimResult:
    """Simulate the full playoff bracket from finalized regular-season standings.

    Builds on ``run_play_in_simulation`` by also simulating each best-of-7 series
    through the NBA Finals.  Play-in uncertainty (unplayed games whose winner is
    ``None`` in *play_in_results*) propagates into the bracket so that seed-7/8
    variance is reflected in the playoff outcomes.

    Win thresholds used for round-probability columns:

    - **champ_pct** — won the championship (= 16 playoff wins).

    Args:
        schedule: Full season schedule from ``data.get_nba_schedule()``.
        play_in_results: Known play-in outcomes.  ``None`` entries are simulated.
        bracket_state: Optional ``PlayoffBracketState`` with known series results
            and FanDuel odds for in-progress series.  ``None`` means every series
            is simulated from scratch.
        calibrated_ratings: Tricode → power rating for the playoff series (e.g. from
            :func:`.calibration.calibrate_ratings`, fit to FanDuel futures). Required.
        power_ratings: Tricode → power rating for play-in games without market odds.
        n_sims: Number of Monte Carlo trials.
        seed: Optional RNG seed for reproducibility.

    Returns:
        :class:`PlayoffSimResult` with the per-team summary DataFrame, the raw
        ``(n_teams, n_sims)`` postseason-wins array (play-in games, played or
        simulated, plus playoff games), ordered tricodes, and the
        internal ``compute_raw_seedings()`` dict (needed by
        :func:`calibrate_ratings` to fit power ratings against market odds).
    """
    rs_completed = completed_standings_games(schedule)

    raw = compute_raw_seedings(
        rs_completed,
        pd.DataFrame(),
        np.empty((0, 1), dtype=np.float32),
        seed=seed,
    )
    if raw is None:
        return PlayoffSimResult(pd.DataFrame(), np.empty((0, n_sims), dtype=np.float32), [], {})

    seeds = np.repeat(raw["seeds"], n_sims, axis=1)
    total_wins = np.repeat(raw["total_wins"], n_sims, axis=1)

    fanduel_game_probs = extract_fanduel_game_probs(schedule, GameType.PLAY_IN)

    rng_playin = np.random.default_rng(seed + 1 if seed is not None else None)
    play_in_wins = np.zeros((raw["n_teams"], n_sims), dtype=np.float32)
    play_in_7, play_in_8 = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds,
        n_teams=raw["n_teams"],
        n_sims=n_sims,
        rng=rng_playin,
        power_ratings=power_ratings or {},
        team_idx=raw["team_idx"],
        play_in_results=play_in_results,
        fanduel_game_probs=fanduel_game_probs or None,
        wins_out=play_in_wins,
    )

    if not calibrated_ratings:
        raise ValueError("Power ratings are required for playoff simulation but were not provided.")
    ratings_arr = build_ratings_array(calibrated_ratings, raw["all_tricodes"])

    rng_playoff = np.random.default_rng(seed + 2 if seed is not None else None)
    playoff_wins, champion, east_champion, west_champion = simulate_playoffs(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds,
        total_wins=total_wins,
        n_teams=raw["n_teams"],
        n_sims=n_sims,
        rng=rng_playoff,
        ratings=ratings_arr,
        bracket_state=bracket_state,
        team_idx=raw["team_idx"],
        play_in_7=play_in_7,
        play_in_8=play_in_8,
    )

    n_teams = raw["n_teams"]
    champ_pct = np.bincount(champion, minlength=n_teams).astype(np.float64) / n_sims
    east_conf_pct = np.bincount(east_champion, minlength=n_teams).astype(np.float64) / n_sims
    west_conf_pct = np.bincount(west_champion, minlength=n_teams).astype(np.float64) / n_sims
    conf_champ_pct = east_conf_pct + west_conf_pct

    rows = []
    for i, tricode in enumerate(raw["all_tricodes"]):
        conf = raw["team_meta"][tricode]["conference"]
        actual_seed = int(raw["seeds"][i, 0])
        po_w = playoff_wins[i] + play_in_wins[i]
        rows.append(
            {
                "tricode": tricode,
                "conference": conf,
                "seed": actual_seed,
                "champ_pct": float(champ_pct[i]),
                "conf_champ_pct": float(conf_champ_pct[i]),
                "mean_po_wins": float(po_w.mean()),
            }
        )

    return PlayoffSimResult(
        summary=pd.DataFrame(rows),
        po_wins_sim=(playoff_wins + play_in_wins).astype(np.float32),
        all_tricodes=list(raw["all_tricodes"]),
        raw=raw,
    )
