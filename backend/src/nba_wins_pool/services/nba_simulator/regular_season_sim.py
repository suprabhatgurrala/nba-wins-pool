import numpy as np
import pandas as pd

from nba_wins_pool.services.nba_simulator.calibration import build_ratings_array
from nba_wins_pool.services.nba_simulator.data import get_espn_bpi_predictions
from nba_wins_pool.services.nba_simulator.play_in_tournament import ConferencePlayInResults, compute_play_in_results
from nba_wins_pool.services.nba_simulator.playoff_seeding import compute_playoff_seeds, compute_raw_seedings
from nba_wins_pool.services.nba_simulator.playoff_sim import PlayoffBracketState, simulate_playoffs
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.nba_game_type import NBAGameType

N_SIMS = 50_000


def _simulate_games(
    game_df: pd.DataFrame,
    n_sims: int = N_SIMS,
    seed: int | None = None,
) -> np.ndarray:
    """Sample game outcomes via Monte Carlo.

    Returns:
        ``(n_games, n_sims)`` float32 array — 1.0 if home team won.
    """
    probs = game_df["home_win_prob"].fillna(0.5).to_numpy(dtype=np.float32)
    rng = np.random.default_rng(seed)
    rand = rng.random((len(game_df), n_sims), dtype=np.float32)
    return (rand < probs[:, None]).astype(np.float32)


def _build_stats(
    game_df: pd.DataFrame,
    home_wins: np.ndarray,
    current_wins: pd.Series | None = None,
) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    """Aggregate per-team win statistics from game outcomes.

    Returns:
        Tuple of (df, team_sim_wins, all_tricodes) where team_sim_wins is the
        raw (n_teams, n_sims) float32 array used for pool-outcome simulation.
    """
    all_tricodes = sorted(set(game_df["home_tricode"]) | set(game_df["away_tricode"]))
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

    Uses vectorised NumPy matrix multiplication so 10 000 simulations over a
    full remaining schedule (~400 games) completes in well under a second.

    Args:
        game_df: DataFrame produced by ``get_espn_bpi_predictions()`` with at
            least columns ``home_tricode``, ``away_tricode``, ``home_win_prob``.
            Games where ``home_win_prob`` is NaN are treated as 50/50.
        current_wins: Optional Series mapping tricode -> wins already recorded
            in completed games.  Teams absent from this series are assumed to
            have 0 current wins.
        n_sims: Number of Monte Carlo trials (default 10 000).
        seed: Optional integer seed for reproducibility.

    Returns:
        DataFrame with one row per team and columns: tricode, mean_wins.
        All win figures include ``current_wins`` when provided.
    """
    if game_df.empty:
        return pd.DataFrame(columns=["tricode", "mean_wins"])

    home_wins = _simulate_games(game_df, n_sims, seed)
    df, _, _ = _build_stats(game_df, home_wins, current_wins)
    return df


def run_regular_season_simulation(
    schedule: pd.DataFrame,
    n_sims: int = N_SIMS,
    seed: int | None = None,
    tiebreaker_counts: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, list[str]]:
    """Simulate the season from a pre-fetched schedule and compute playoff seedings.

    Derives current win totals from completed games, fetches game-level win
    probabilities for upcoming games, then runs the Monte Carlo simulation and
    determines conference seedings using the official NBA tiebreaker procedures.

    Args:
        schedule: Full season schedule DataFrame from ``data.get_nba_schedule()``.
        n_sims: Number of Monte Carlo trials (default 10 000).
        seed: Optional integer seed for reproducibility.

    Returns:
        Tuple of ``(win_stats, seeding, rs_wins_sim, all_tricodes)``.

        *win_stats* — one row per team with projected win-total statistics (mean).

        *seeding* — one row per team with seed probabilities per conference.

        *rs_wins_sim* — ``(n_teams, n_sims)`` float32 array of simulated
        regular-season win totals, indexed by *all_tricodes*.

        *all_tricodes* — ordered list of tricodes corresponding to axis 0 of
        *rs_wins_sim*.
    """
    # Current wins from completed games
    completed = schedule[schedule["status"] == NBAGameStatus.FINAL]
    home_wins_count = completed[completed["home_score"] > completed["away_score"]]["home_tricode"].value_counts()
    away_wins_count = completed[completed["away_score"] > completed["home_score"]]["away_tricode"].value_counts()
    current_wins = home_wins_count.add(away_wins_count, fill_value=0).rename("wins")

    game_df = get_espn_bpi_predictions(schedule)

    if game_df.empty:
        all_tricodes = sorted(current_wins.index.tolist()) if len(current_wins) > 0 else []
        rs_wins_sim = np.array([[current_wins.get(tc, 0)] * n_sims for tc in all_tricodes], dtype=np.float32)
        stats = pd.DataFrame(columns=["tricode", "mean_wins"])
        seeding = compute_playoff_seeds(
            completed,
            game_df,
            np.empty((0, n_sims), dtype=np.float32),
            seed=seed + 1 if seed is not None else None,
            tiebreaker_counts=tiebreaker_counts,
        )
        return stats, seeding, rs_wins_sim, all_tricodes

    home_wins_sim = _simulate_games(game_df, n_sims, seed)
    stats, rs_wins_sim, all_tricodes = _build_stats(game_df, home_wins_sim, current_wins)
    seeding = compute_playoff_seeds(
        completed,
        game_df,
        home_wins_sim,
        seed=seed + 1 if seed is not None else None,
        tiebreaker_counts=tiebreaker_counts,
    )

    return stats, seeding, rs_wins_sim, list(all_tricodes)


def run_play_in_simulation(
    schedule: pd.DataFrame,
    play_in_results: dict[str, ConferencePlayInResults] | None = None,
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
        n_sims: Number of Monte Carlo trials (default 10 000).
        seed: Optional RNG seed for reproducibility.

    Returns:
        Tuple of ``(win_stats, seeding, rs_wins_sim, all_tricodes)`` matching
        the format of ``run_regular_season_simulation``.  *win_stats* contains actual win totals
        because regular season outcomes are final.  *rs_wins_sim* is a broadcast
        of the deterministic win totals across all simulations.
    """
    rs_completed = schedule[
        (schedule["status"] == NBAGameStatus.FINAL) & (schedule["game_type"] == NBAGameType.REGULAR_SEASON)
    ]

    # Actual win totals — regular season + completed play-in games
    home_w = rs_completed[rs_completed["home_score"] > rs_completed["away_score"]]["home_tricode"].value_counts()
    away_w = rs_completed[rs_completed["away_score"] > rs_completed["home_score"]]["away_tricode"].value_counts()
    actual_wins = home_w.add(away_w, fill_value=0).rename("wins")

    pi_completed = schedule[
        (schedule["status"] == NBAGameStatus.FINAL) & (schedule["game_type"] == NBAGameType.PLAY_IN)
    ]
    if not pi_completed.empty:
        pi_home_w = pi_completed[pi_completed["home_score"] > pi_completed["away_score"]]["home_tricode"].value_counts()
        pi_away_w = pi_completed[pi_completed["away_score"] > pi_completed["home_score"]]["away_tricode"].value_counts()
        actual_wins = actual_wins.add(pi_home_w, fill_value=0).add(pi_away_w, fill_value=0)

    win_stats = pd.DataFrame(
        {
            "tricode": actual_wins.index,
            "mean_wins": actual_wins.values.astype(float),
        }
    )

    # Compute actual conference seeds once (n_sims=1, no remaining regular season games)
    raw = compute_raw_seedings(
        rs_completed,
        pd.DataFrame(),
        np.empty((0, 1), dtype=np.float32),
        seed=seed,
        tiebreaker_counts=tiebreaker_counts,
    )
    if raw is None:
        return win_stats, pd.DataFrame(), np.empty((0, n_sims), dtype=np.float32), []

    # Broadcast deterministic seeds and win totals to full n_sims
    seeds = np.repeat(raw["seeds"], n_sims, axis=1)  # (n_teams, n_sims)
    total_wins = np.repeat(raw["total_wins"], n_sims, axis=1)  # (n_teams, n_sims)

    # Extract FanDuel moneyline probabilities for upcoming play-in games.
    # The schedule already has FanDuel odds merged in via get_nba_schedule().
    play_in_pregame = schedule[
        (schedule["status"] == NBAGameStatus.PREGAME) & (schedule["game_type"] == NBAGameType.PLAY_IN)
    ]
    fanduel_game_probs: dict[tuple[str, str], float] = {}
    for _, row in play_in_pregame.iterrows():
        prob = row.get("home_win_prob")
        if pd.notna(prob):
            fanduel_game_probs[(row["home_tricode"], row["away_tricode"])] = float(prob)

    # Simulate remaining play-in games
    rng = np.random.default_rng(seed + 1 if seed is not None else None)
    play_in_7, play_in_8 = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds,
        total_wins=total_wins,
        n_teams=raw["n_teams"],
        n_sims=n_sims,
        rng=rng,
        team_idx=raw["team_idx"],
        play_in_results=play_in_results,
        fanduel_game_probs=fanduel_game_probs or None,
    )

    # Build seeding DataFrame:
    #   seeds 1-6:   deterministic from actual regular season standings
    #   seeds 7-8:   probabilistic — play-in simulation outcome
    #   seeds 9-10+: deterministic from actual regular season standings
    actual_seeds = raw["seeds"]  # (n_teams, 1)
    is_div_winner = raw["is_div_winner"]  # (n_teams, 1)
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

    return win_stats, pd.DataFrame(rows), total_wins, list(raw["all_tricodes"])


def run_playoff_simulation(
    schedule: pd.DataFrame,
    play_in_results: dict[str, ConferencePlayInResults] | None = None,
    bracket_state: PlayoffBracketState | None = None,
    ratings: dict[str, float] | None = None,
    n_sims: int = N_SIMS,
    seed: int | None = None,
) -> tuple[pd.DataFrame, np.ndarray, list[str], dict]:
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
        ratings: Optional tricode → power rating dict (e.g. from
            :func:`calibrate_ratings_from_data`).  When provided, these ratings
            replace the default ESPN BPI inside ``simulate_playoffs``.
        n_sims: Number of Monte Carlo trials (default 10 000).
        seed: Optional RNG seed for reproducibility.

    Returns:
        Tuple of ``(df, po_wins_sim, all_tricodes)``.

        *df* — one row per team with columns tricode, conference, seed,
        champ_pct, conf_champ_pct, mean_po_wins.  Non-playoff teams have 0.0.

        *po_wins_sim* — ``(n_teams, n_sims)`` float32 array of simulated
        playoff wins, indexed by *all_tricodes*.

        *all_tricodes* — ordered list of tricodes corresponding to axis 0 of
        *po_wins_sim*.

        *raw* — the internal ``compute_raw_seedings()`` dict, needed by
        :func:`calibrate_ratings` to fit power ratings against market odds.
    """
    rs_completed = schedule[
        (schedule["status"] == NBAGameStatus.FINAL) & (schedule["game_type"] == NBAGameType.REGULAR_SEASON)
    ]

    raw = compute_raw_seedings(
        rs_completed,
        pd.DataFrame(),
        np.empty((0, 1), dtype=np.float32),
        seed=seed,
    )
    if raw is None:
        return pd.DataFrame(), np.empty((0, n_sims), dtype=np.float32), [], {}

    seeds = np.repeat(raw["seeds"], n_sims, axis=1)  # (n_teams, n_sims)
    total_wins = np.repeat(raw["total_wins"], n_sims, axis=1)  # (n_teams, n_sims)

    # FanDuel moneyline odds for upcoming play-in games
    play_in_pregame = schedule[
        (schedule["status"] == NBAGameStatus.PREGAME) & (schedule["game_type"] == NBAGameType.PLAY_IN)
    ]
    fanduel_game_probs: dict[tuple[str, str], float] = {}
    for _, row in play_in_pregame.iterrows():
        prob = row.get("home_win_prob")
        if pd.notna(prob):
            fanduel_game_probs[(row["home_tricode"], row["away_tricode"])] = float(prob)

    rng_playin = np.random.default_rng(seed + 1 if seed is not None else None)
    play_in_7, play_in_8 = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds,
        total_wins=total_wins,
        n_teams=raw["n_teams"],
        n_sims=n_sims,
        rng=rng_playin,
        team_idx=raw["team_idx"],
        play_in_results=play_in_results,
        fanduel_game_probs=fanduel_game_probs or None,
    )

    ratings_arr = build_ratings_array(ratings, raw["all_tricodes"]) if ratings else None

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
        po_w = playoff_wins[i]  # (n_sims,)
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

    return pd.DataFrame(rows), playoff_wins.astype(np.float32), list(raw["all_tricodes"]), raw
