import numpy as np
import pandas as pd

from nba_wins_pool.services.nba_simulator.data import get_espn_bpi_predictions, get_nba_schedule
from nba_wins_pool.types.nba_game_status import NBAGameStatus

N_SIMS = 10_000


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
        DataFrame with one row per team and columns:
            tricode, mean_wins, std_wins, p10, p25, p50, p75, p90.
        All win figures include ``current_wins`` when provided.
    """
    if game_df.empty:
        return pd.DataFrame(columns=["tricode", "mean_wins", "std_wins", "p10", "p25", "p50", "p75", "p90"])

    # Fill missing win probabilities with coin-flip
    probs = game_df["home_win_prob"].fillna(0.5).to_numpy(dtype=np.float32)

    # Build a stable team index from all tricodes that appear in this schedule
    all_tricodes = sorted(set(game_df["home_tricode"]) | set(game_df["away_tricode"]))
    team_idx = {t: i for i, t in enumerate(all_tricodes)}
    n_teams = len(all_tricodes)
    n_games = len(game_df)

    home_idx = game_df["home_tricode"].map(team_idx).to_numpy()
    away_idx = game_df["away_tricode"].map(team_idx).to_numpy()

    # Indicator matrices: H[t, g] = 1 when team t is the home side of game g
    H = np.zeros((n_teams, n_games), dtype=np.float32)
    A = np.zeros((n_teams, n_games), dtype=np.float32)
    H[home_idx, np.arange(n_games)] = 1.0
    A[away_idx, np.arange(n_games)] = 1.0

    # Sample all games × simulations in one call — shape (n_games, n_sims)
    rng = np.random.default_rng(seed)
    rand = rng.random((n_games, n_sims), dtype=np.float32)
    home_wins = (rand < probs[:, None]).astype(np.float32)

    # Matrix multiply: (n_teams × n_games) @ (n_games × n_sims) → (n_teams × n_sims)
    team_sim_wins = H @ home_wins + A @ (1.0 - home_wins)

    # Layer in already-recorded wins
    if current_wins is not None:
        base = np.array([current_wins.get(t, 0) for t in all_tricodes], dtype=np.float32)
        team_sim_wins += base[:, None]

    return pd.DataFrame(
        {
            "tricode": all_tricodes,
            "mean_wins": team_sim_wins.mean(axis=1),
            "std_wins": team_sim_wins.std(axis=1),
            "p10": np.percentile(team_sim_wins, 10, axis=1),
            "p25": np.percentile(team_sim_wins, 25, axis=1),
            "p50": np.percentile(team_sim_wins, 50, axis=1),
            "p75": np.percentile(team_sim_wins, 75, axis=1),
            "p90": np.percentile(team_sim_wins, 90, axis=1),
        }
    )


def run_simulation(n_sims: int = N_SIMS, seed: int | None = None) -> pd.DataFrame:
    """Convenience entry-point: fetch live data and run the season simulation.

    Pulls the full NBA schedule, derives current win totals from completed
    games, fetches game-level win probabilities for upcoming games, then
    runs ``simulate_season``.

    Args:
        n_sims: Number of Monte Carlo trials (default 10 000).
        seed: Optional integer seed for reproducibility.

    Returns:
        DataFrame from ``simulate_season`` — one row per team with projected
        win-total statistics (mean, std, percentiles).
    """
    schedule = get_nba_schedule()

    # Current wins from completed games
    completed = schedule[schedule["status"] == NBAGameStatus.FINAL]
    home_wins = completed[completed["home_score"] > completed["away_score"]]["home_tricode"].value_counts()
    away_wins = completed[completed["away_score"] > completed["home_score"]]["away_tricode"].value_counts()
    current_wins = home_wins.add(away_wins, fill_value=0).rename("wins")

    game_df = get_espn_bpi_predictions(schedule)
    return simulate_season(game_df, current_wins=current_wins, n_sims=n_sims, seed=seed)
