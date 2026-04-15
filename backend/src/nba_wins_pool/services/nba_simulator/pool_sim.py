"""Compute per-roster pool-outcome probabilities from a playoff simulation.

Given a completed Monte Carlo run (regular-season + playoff wins per team per
simulation) and a mapping from team tricode to pool-roster name, this module
aggregates wins to roster level and answers two questions:

1. **Average wins** — expected total wins (regular season + playoffs) for each
   roster over the simulation ensemble.
2. **Pool-win probability** — fraction of simulations in which each roster
   finishes with the highest win total.  Ties are split evenly (each tied
   roster receives ``1 / n_tied`` credit for that simulation).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_pool_outcomes(
    total_wins_sim: np.ndarray,
    tricode_to_roster: dict[str, str],
    all_tricodes: list[str],
) -> pd.DataFrame:
    """Compute pool-win probability and mean total wins per roster.

    Args:
        total_wins_sim: ``(n_teams, n_sims)`` array of total wins (regular
            season + playoffs) per team per simulation.  Teams are ordered the
            same way as *all_tricodes*.
        tricode_to_roster: Mapping from team tricode to the roster name that
            owns it.  Teams absent from this dict (e.g. undrafted) are ignored.
        all_tricodes: Ordered list of tricodes corresponding to axis 0 of
            *total_wins_sim* (i.e. ``raw["all_tricodes"]``).

    Returns:
        DataFrame with one row per roster and columns:

        - *roster* — roster name
        - *mean_wins* — mean total wins across all simulations
        - *win_pct* — probability of finishing with the most wins (ties split)
        - *p10_wins*, *p25_wins*, *p50_wins*, *p75_wins*, *p90_wins* —
          percentiles of the total-win distribution
    """
    rosters = sorted(set(tricode_to_roster.values()))
    n_rosters = len(rosters)
    n_sims = total_wins_sim.shape[1]
    roster_idx = {r: i for i, r in enumerate(rosters)}

    tc_to_global = {tc: i for i, tc in enumerate(all_tricodes)}

    # Accumulate wins per roster across teams
    roster_wins = np.zeros((n_rosters, n_sims), dtype=np.float64)
    for tc, roster in tricode_to_roster.items():
        gi = tc_to_global.get(tc)
        ri = roster_idx.get(roster)
        if gi is not None and ri is not None:
            roster_wins[ri] += total_wins_sim[gi].astype(np.float64)

    # Pool-win probability: max wins per sim; split ties fractionally
    max_wins = roster_wins.max(axis=0)  # (n_sims,)
    is_winner = roster_wins == max_wins[None, :]  # (n_rosters, n_sims)
    n_winners = is_winner.sum(axis=0).clip(min=1)  # (n_sims,)
    win_share = is_winner / n_winners[None, :]  # fractional credit

    return (
        pd.DataFrame(
            {
                "roster": rosters,
                "mean_wins": roster_wins.mean(axis=1),
                "win_pct": win_share.mean(axis=1),
                "min_wins": np.min(roster_wins, axis=1),
                "p10_wins": np.percentile(roster_wins, 10, axis=1),
                "p25_wins": np.percentile(roster_wins, 25, axis=1),
                "p50_wins": np.percentile(roster_wins, 50, axis=1),
                "p75_wins": np.percentile(roster_wins, 75, axis=1),
                "p90_wins": np.percentile(roster_wins, 90, axis=1),
                "max_wins": np.max(roster_wins, axis=1),
            }
        )
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )
