"""
Main control flow for the NBA simulator service.
"""

import pandas as pd

from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.services.nba_simulator.data import (
    detect_season_phase,
    get_nba_schedule,
    get_play_in_results,
    get_playoff_bracket_state,
)
from nba_wins_pool.services.nba_simulator.play_in_tournament import ConferencePlayInResults
from nba_wins_pool.services.nba_simulator.playoff_sim import PlayoffBracketState
from nba_wins_pool.services.nba_simulator.regular_season_sim import (
    run_play_in_simulation,
    run_playoff_simulation,
    run_simulation,
)
from nba_wins_pool.types.nba_game_type import NBAGameType


def simulate_nba_season() -> (
    tuple[
        NBAGameType,
        pd.DataFrame,
        pd.DataFrame,
        dict[str, ConferencePlayInResults] | None,
        pd.DataFrame | None,
    ]
):
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

    Returns:
        5-tuple of ``(phase, win_stats, seeding, play_in_results, playoff_summary)``.

        *phase* — the detected ``NBAGameType``.

        *win_stats* — one row per team with projected win-total statistics
        (zero variance once the regular season is finished).

        *seeding* — one row per team with seed probabilities per conference
        (mean_seed, seed_N_pct, playoff_pct, etc.).

        *play_in_results* — dict mapping ``"East"`` / ``"West"`` to
        ``ConferencePlayInResults`` with completed game winners filled in,
        or ``None`` when not in the play-in / playoffs phase.

        *playoff_summary* — DataFrame with one row per team and columns
        tricode, conference, seed, rs_wins, champ_pct, finals_pct,
        conf_finals_pct, r2_pct, mean_po_wins, mean_total_wins.
        ``None`` during the regular-season phase.
    """
    schedule = get_nba_schedule()
    phase = detect_season_phase(schedule)

    play_in_results: dict[str, ConferencePlayInResults] | None = None
    bracket_state: PlayoffBracketState | None = None
    playoff_summary: pd.DataFrame | None = None

    if phase == NBAGameType.REGULAR_SEASON:
        win_stats, seeding = run_simulation(schedule)
    else:
        play_in_results = get_play_in_results(schedule)
        win_stats, seeding = run_play_in_simulation(schedule, play_in_results)

        if phase == NBAGameType.PLAYOFFS:
            bracket_state = get_playoff_bracket_state(schedule)

        playoff_summary = run_playoff_simulation(
            schedule,
            play_in_results=play_in_results,
            bracket_state=bracket_state,
        )

    return phase, win_stats, seeding, play_in_results, playoff_summary


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
