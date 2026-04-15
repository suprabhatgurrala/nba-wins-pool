"""Compute NBA playoff seedings from Monte Carlo regular-season simulation results.

Implements the official NBA tiebreaker procedures to determine conference
seedings across all simulations.

Tiebreaker Basis - 2 Teams Tied:
    (1) Head-to-head record
    (2) Division leader over non-leader
    (3) Division win pct (same division only)
    (4) Conference win pct
    (5) Record vs playoff-eligible teams in own conference
    (6) Record vs playoff-eligible teams in other conference
    (7) Point differential

Tiebreaker Basis - 3+ Teams Tied:
    (1) Division leader over non-leader
    (2) Head-to-head record among all tied teams
    (3) Division win pct (all same division only)
    (4) Conference win pct
    (5) Record vs playoff-eligible teams in own conference
    (6) Point differential

Division winners are determined first (without the division-leader criterion),
then conference seedings are resolved with division leaders known.
"""

from __future__ import annotations

import json
from itertools import groupby
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Team metadata
# ---------------------------------------------------------------------------


def load_team_metadata() -> dict[str, dict[str, str]]:
    """Load team conference and division from the bundled nba_teams.json."""
    path = Path(__file__).parent.parent.parent / "scripts" / "data" / "nba_teams.json"
    return {
        t["abbreviation"]: {"conference": t["conference"], "division": t["division"]}
        for t in json.loads(path.read_text())
    }


# ---------------------------------------------------------------------------
# Pre-computation (vectorised across simulations)
# ---------------------------------------------------------------------------


def _build_metrics(
    completed_df: pd.DataFrame,
    remaining_df: pd.DataFrame,
    home_wins_sim: np.ndarray,
    team_idx: dict[str, int],
    team_conf: np.ndarray,
    team_div: np.ndarray,
    n_sims: int,
) -> dict:
    """Pre-compute all tiebreaker metrics across every simulation.

    Returns dict with:
        total_wins : (n_teams, n_sims) float32
        div_wins   : (n_teams, n_sims) float32
        div_games  : (n_teams,) int32
        conf_wins  : (n_teams, n_sims) float32
        conf_games : (n_teams,) int32
        h2h_wins   : (n_teams, n_teams, n_sims) float32
        h2h_games  : (n_teams, n_teams) int32
        pt_diff    : (n_teams,) float32  (completed games only)
    """
    n_teams = len(team_idx)

    # --- Completed-game accumulators (constant across sims) ---
    comp_wins = np.zeros(n_teams, dtype=np.float32)
    comp_div_wins = np.zeros(n_teams, dtype=np.float32)
    comp_conf_wins = np.zeros(n_teams, dtype=np.float32)
    comp_h2h = np.zeros((n_teams, n_teams), dtype=np.float32)
    h2h_games = np.zeros((n_teams, n_teams), dtype=np.int32)
    div_games = np.zeros(n_teams, dtype=np.int32)
    conf_games = np.zeros(n_teams, dtype=np.int32)
    pt_diff = np.zeros(n_teams, dtype=np.float32)

    if not completed_df.empty:
        c_home = completed_df["home_tricode"].map(team_idx).values.astype(int)
        c_away = completed_df["away_tricode"].map(team_idx).values.astype(int)
        c_home_won = (completed_df["home_score"].values > completed_df["away_score"].values).astype(np.float32)
        c_home_scores = completed_df["home_score"].values.astype(np.float64)
        c_away_scores = completed_df["away_score"].values.astype(np.float64)

        for g in range(len(completed_df)):
            hi, ai = int(c_home[g]), int(c_away[g])
            hw = c_home_won[g]

            comp_wins[hi] += hw
            comp_wins[ai] += 1.0 - hw

            comp_h2h[hi, ai] += hw
            comp_h2h[ai, hi] += 1.0 - hw
            h2h_games[hi, ai] += 1
            h2h_games[ai, hi] += 1

            if team_div[hi] == team_div[ai]:
                comp_div_wins[hi] += hw
                comp_div_wins[ai] += 1.0 - hw
                div_games[hi] += 1
                div_games[ai] += 1

            if team_conf[hi] == team_conf[ai]:
                comp_conf_wins[hi] += hw
                comp_conf_wins[ai] += 1.0 - hw
                conf_games[hi] += 1
                conf_games[ai] += 1

            pt_diff[hi] += c_home_scores[g] - c_away_scores[g]
            pt_diff[ai] += c_away_scores[g] - c_home_scores[g]

    # --- Remaining-game contributions (vary per simulation) ---
    n_rem = len(remaining_df) if not remaining_df.empty else 0

    if n_rem > 0 and home_wins_sim.size:
        r_home = remaining_df["home_tricode"].map(team_idx).values.astype(int)
        r_away = remaining_df["away_tricode"].map(team_idx).values.astype(int)

        # Indicator matrices for remaining games
        H = np.zeros((n_teams, n_rem), dtype=np.float32)
        A = np.zeros((n_teams, n_rem), dtype=np.float32)
        H[r_home, np.arange(n_rem)] = 1.0
        A[r_away, np.arange(n_rem)] = 1.0

        remaining_wins = H @ home_wins_sim + A @ (1.0 - home_wins_sim)

        # Division / conference masks for remaining games
        r_same_div = (team_div[r_home] == team_div[r_away]).astype(np.float32)
        r_same_conf = (team_conf[r_home] == team_conf[r_away]).astype(np.float32)

        remaining_div_wins = (H * r_same_div) @ home_wins_sim + (A * r_same_div) @ (1.0 - home_wins_sim)
        remaining_conf_wins = (H * r_same_conf) @ home_wins_sim + (A * r_same_conf) @ (1.0 - home_wins_sim)

        # H2H from remaining games
        remaining_h2h = np.zeros((n_teams, n_teams, n_sims), dtype=np.float32)
        for g in range(n_rem):
            hi, ai = int(r_home[g]), int(r_away[g])
            remaining_h2h[hi, ai] += home_wins_sim[g]
            remaining_h2h[ai, hi] += 1.0 - home_wins_sim[g]
            h2h_games[hi, ai] += 1
            h2h_games[ai, hi] += 1
            if team_div[hi] == team_div[ai]:
                div_games[hi] += 1
                div_games[ai] += 1
            if team_conf[hi] == team_conf[ai]:
                conf_games[hi] += 1
                conf_games[ai] += 1
    else:
        remaining_wins = np.zeros((n_teams, n_sims), dtype=np.float32)
        remaining_div_wins = np.zeros((n_teams, n_sims), dtype=np.float32)
        remaining_conf_wins = np.zeros((n_teams, n_sims), dtype=np.float32)
        remaining_h2h = np.zeros((n_teams, n_teams, n_sims), dtype=np.float32)

    return {
        "total_wins": comp_wins[:, None] + remaining_wins,
        "div_wins": comp_div_wins[:, None] + remaining_div_wins,
        "div_games": div_games,
        "conf_wins": comp_conf_wins[:, None] + remaining_conf_wins,
        "conf_games": conf_games,
        "h2h_wins": comp_h2h[:, :, None] + remaining_h2h,
        "h2h_games": h2h_games,
        "pt_diff": pt_diff,
    }


def _compute_playoff_eligible(conf_teams: list[int], total_wins: np.ndarray, n_sims: int) -> list[set[int]]:
    """For each sim, return playoff-eligible teams (top 10 by wins, ties included)."""
    if not conf_teams:
        return [set() for _ in range(n_sims)]

    conf_wins = total_wins[conf_teams]  # (n_conf, n_sims)
    n_conf = len(conf_teams)

    # Find the 10th-highest win total per simulation
    partition_idx = max(n_conf - 10, 0)
    partitioned = np.partition(conf_wins, partition_idx, axis=0)
    cutoff = partitioned[partition_idx]  # (n_sims,)

    eligible_mask = conf_wins >= cutoff[None, :]  # (n_conf, n_sims)

    return [{conf_teams[i] for i in range(n_conf) if eligible_mask[i, s]} for s in range(n_sims)]


# ---------------------------------------------------------------------------
# Tiebreaker helpers
# ---------------------------------------------------------------------------


def _win_pct(wins: float, games: int) -> float | None:
    return wins / games if games > 0 else None


def _record_vs_set(team: int, opponents: set[int], sim: int, metrics: dict) -> float | None:
    """Win pct of *team* against a set of opponents in simulation *sim*."""
    wins = sum(float(metrics["h2h_wins"][team, opp, sim]) for opp in opponents if opp != team)
    games = sum(int(metrics["h2h_games"][team, opp]) for opp in opponents if opp != team)
    return wins / games if games > 0 else None


def _partition_by_criterion(teams: list[int], values: dict[int, float | None]) -> list[list[int]]:
    """Partition teams into groups with equal criterion values, best-first.

    If any team has a ``None`` value the criterion cannot differentiate —
    returns the original group unchanged.
    """
    if any(values[t] is None for t in teams):
        return [teams]

    sorted_teams = sorted(teams, key=lambda t: -values[t])
    return [list(g) for _, g in groupby(sorted_teams, key=lambda t: values[t])]


def _try_partition(
    teams: list[int],
    values: dict[int, float | None],
    criterion: str,
    sim: int,
    metrics: dict,
    team_div: np.ndarray,
    div_winners: set[int],
    own_elig: set[int],
    other_elig: set[int],
    is_div_tiebreak: bool,
    rng: np.random.Generator,
    stats: dict,
) -> list[int] | None:
    """If *values* differentiates teams, recursively resolve sub-groups.

    Returns ``None`` when all teams share the same value.
    """
    groups = _partition_by_criterion(teams, values)
    if len(groups) <= 1:
        return None
    stats[criterion] = stats.get(criterion, 0) + 1
    result: list[int] = []
    for group in groups:
        result.extend(
            _resolve_tie_group(
                group, sim, metrics, team_div, div_winners, own_elig, other_elig, is_div_tiebreak, rng, stats
            )
        )
    return result


# ---------------------------------------------------------------------------
# Core tiebreaker dispatch
# ---------------------------------------------------------------------------


def _resolve_tie_group(
    teams: list[int],
    sim: int,
    metrics: dict,
    team_div: np.ndarray,
    div_winners: set[int],
    own_elig: set[int],
    other_elig: set[int],
    is_div_tiebreak: bool,
    rng: np.random.Generator,
    stats: dict,
) -> list[int]:
    """Resolve a group of teams with identical win totals."""
    if len(teams) <= 1:
        return list(teams)
    stats["ties_encountered"] = stats.get("ties_encountered", 0) + 1
    if len(teams) == 2:
        return _two_team_tiebreak(
            teams, sim, metrics, team_div, div_winners, own_elig, other_elig, is_div_tiebreak, rng, stats
        )
    return _multi_team_tiebreak(
        teams, sim, metrics, team_div, div_winners, own_elig, other_elig, is_div_tiebreak, rng, stats
    )


# ---------------------------------------------------------------------------
# 2-team tiebreaker
# ---------------------------------------------------------------------------


def _two_team_tiebreak(
    teams: list[int],
    sim: int,
    metrics: dict,
    team_div: np.ndarray,
    div_winners: set[int],
    own_elig: set[int],
    other_elig: set[int],
    is_div_tiebreak: bool,
    rng: np.random.Generator,
    stats: dict,
) -> list[int]:
    a, b = teams

    # (1) Head-to-head
    a_w = float(metrics["h2h_wins"][a, b, sim])
    b_w = float(metrics["h2h_wins"][b, a, sim])
    if a_w > b_w:
        stats["h2h"] = stats.get("h2h", 0) + 1
        return [a, b]
    if b_w > a_w:
        stats["h2h"] = stats.get("h2h", 0) + 1
        return [b, a]

    # (2) Division leader over non-leader
    if not is_div_tiebreak:
        a_ldr, b_ldr = a in div_winners, b in div_winners
        if a_ldr and not b_ldr:
            stats["div_leader"] = stats.get("div_leader", 0) + 1
            return [a, b]
        if b_ldr and not a_ldr:
            stats["div_leader"] = stats.get("div_leader", 0) + 1
            return [b, a]

    # (3) Division win pct (same division only)
    if team_div[a] == team_div[b]:
        a_pct = _win_pct(float(metrics["div_wins"][a, sim]), int(metrics["div_games"][a]))
        b_pct = _win_pct(float(metrics["div_wins"][b, sim]), int(metrics["div_games"][b]))
        if a_pct is not None and b_pct is not None:
            if a_pct > b_pct:
                stats["div_win_pct"] = stats.get("div_win_pct", 0) + 1
                return [a, b]
            if b_pct > a_pct:
                stats["div_win_pct"] = stats.get("div_win_pct", 0) + 1
                return [b, a]

    # (4) Conference win pct
    a_pct = _win_pct(float(metrics["conf_wins"][a, sim]), int(metrics["conf_games"][a]))
    b_pct = _win_pct(float(metrics["conf_wins"][b, sim]), int(metrics["conf_games"][b]))
    if a_pct is not None and b_pct is not None:
        if a_pct > b_pct:
            stats["conf_win_pct"] = stats.get("conf_win_pct", 0) + 1
            return [a, b]
        if b_pct > a_pct:
            stats["conf_win_pct"] = stats.get("conf_win_pct", 0) + 1
            return [b, a]

    # (5) Record vs playoff-eligible in own conference
    a_vs = _record_vs_set(a, own_elig, sim, metrics)
    b_vs = _record_vs_set(b, own_elig, sim, metrics)
    if a_vs is not None and b_vs is not None:
        if a_vs > b_vs:
            stats["vs_own_playoff"] = stats.get("vs_own_playoff", 0) + 1
            return [a, b]
        if b_vs > a_vs:
            stats["vs_own_playoff"] = stats.get("vs_own_playoff", 0) + 1
            return [b, a]

    # (6) Record vs playoff-eligible in other conference
    a_vs = _record_vs_set(a, other_elig, sim, metrics)
    b_vs = _record_vs_set(b, other_elig, sim, metrics)
    if a_vs is not None and b_vs is not None:
        if a_vs > b_vs:
            stats["vs_other_playoff"] = stats.get("vs_other_playoff", 0) + 1
            return [a, b]
        if b_vs > a_vs:
            stats["vs_other_playoff"] = stats.get("vs_other_playoff", 0) + 1
            return [b, a]

    # (7) Point differential
    a_pd = float(metrics["pt_diff"][a])
    b_pd = float(metrics["pt_diff"][b])
    if a_pd > b_pd:
        stats["pt_diff"] = stats.get("pt_diff", 0) + 1
        return [a, b]
    if b_pd > a_pd:
        stats["pt_diff"] = stats.get("pt_diff", 0) + 1
        return [b, a]

    # Random drawing
    stats["random"] = stats.get("random", 0) + 1
    return [a, b] if rng.random() < 0.5 else [b, a]


# ---------------------------------------------------------------------------
# 3+ team tiebreaker
# ---------------------------------------------------------------------------


def _multi_team_tiebreak(
    teams: list[int],
    sim: int,
    metrics: dict,
    team_div: np.ndarray,
    div_winners: set[int],
    own_elig: set[int],
    other_elig: set[int],
    is_div_tiebreak: bool,
    rng: np.random.Generator,
    stats: dict,
) -> list[int]:
    # (1) Division leader over non-leader
    if not is_div_tiebreak:
        leaders = [t for t in teams if t in div_winners]
        non_leaders = [t for t in teams if t not in div_winners]
        if leaders and non_leaders:
            stats["div_leader"] = stats.get("div_leader", 0) + 1
            resolved_leaders = _resolve_tie_group(
                leaders, sim, metrics, team_div, div_winners, own_elig, other_elig, is_div_tiebreak, rng, stats
            )
            resolved_non = _resolve_tie_group(
                non_leaders, sim, metrics, team_div, div_winners, own_elig, other_elig, is_div_tiebreak, rng, stats
            )
            return resolved_leaders + resolved_non

    # (2) H2H among all tied teams
    h2h_pct: dict[int, float | None] = {}
    for t in teams:
        wins = sum(float(metrics["h2h_wins"][t, opp, sim]) for opp in teams if opp != t)
        games = sum(int(metrics["h2h_games"][t, opp]) for opp in teams if opp != t)
        h2h_pct[t] = wins / games if games > 0 else None
    result = _try_partition(
        teams, h2h_pct, "h2h", sim, metrics, team_div, div_winners, own_elig, other_elig, is_div_tiebreak, rng, stats
    )
    if result is not None:
        return result

    # (3) Division win pct (only if ALL teams are in the same division)
    if len({team_div[t] for t in teams}) == 1:
        div_pct = {t: _win_pct(float(metrics["div_wins"][t, sim]), int(metrics["div_games"][t])) for t in teams}
        result = _try_partition(
            teams,
            div_pct,
            "div_win_pct",
            sim,
            metrics,
            team_div,
            div_winners,
            own_elig,
            other_elig,
            is_div_tiebreak,
            rng,
            stats,
        )
        if result is not None:
            return result

    # (4) Conference win pct
    conf_pct = {t: _win_pct(float(metrics["conf_wins"][t, sim]), int(metrics["conf_games"][t])) for t in teams}
    result = _try_partition(
        teams,
        conf_pct,
        "conf_win_pct",
        sim,
        metrics,
        team_div,
        div_winners,
        own_elig,
        other_elig,
        is_div_tiebreak,
        rng,
        stats,
    )
    if result is not None:
        return result

    # (5) Record vs playoff-eligible in own conference
    vs_own = {t: _record_vs_set(t, own_elig, sim, metrics) for t in teams}
    result = _try_partition(
        teams,
        vs_own,
        "vs_own_playoff",
        sim,
        metrics,
        team_div,
        div_winners,
        own_elig,
        other_elig,
        is_div_tiebreak,
        rng,
        stats,
    )
    if result is not None:
        return result

    # (6) Point differential
    pd_val: dict[int, float | None] = {t: float(metrics["pt_diff"][t]) for t in teams}
    result = _try_partition(
        teams, pd_val, "pt_diff", sim, metrics, team_div, div_winners, own_elig, other_elig, is_div_tiebreak, rng, stats
    )
    if result is not None:
        return result

    # Random drawing
    stats["random"] = stats.get("random", 0) + 1
    order = rng.permutation(len(teams)).tolist()
    return [teams[i] for i in order]


# ---------------------------------------------------------------------------
# Conference seeding
# ---------------------------------------------------------------------------


def _seed_group_by_wins(
    teams: list[int],
    sim: int,
    metrics: dict,
    team_div: np.ndarray,
    div_winners: set[int],
    own_elig: set[int],
    other_elig: set[int],
    is_div_tiebreak: bool,
    rng: np.random.Generator,
    stats: dict,
) -> list[int]:
    """Sort teams by total wins descending, resolving ties with NBA tiebreakers."""
    teams_sorted = sorted(teams, key=lambda t: -float(metrics["total_wins"][t, sim]))

    result: list[int] = []
    for _, group_iter in groupby(teams_sorted, key=lambda t: float(metrics["total_wins"][t, sim])):
        tied = list(group_iter)
        if len(tied) == 1:
            result.append(tied[0])
        else:
            result.extend(
                _resolve_tie_group(
                    tied, sim, metrics, team_div, div_winners, own_elig, other_elig, is_div_tiebreak, rng, stats
                )
            )
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_raw_seedings(
    completed_df: pd.DataFrame,
    remaining_df: pd.DataFrame,
    home_wins_sim: np.ndarray,
    team_meta: dict[str, dict[str, str]] | None = None,
    seed: int | None = None,
    tiebreaker_counts: dict | None = None,
) -> dict | None:
    """Run the seeding loop and return raw intermediate arrays.

    This is the computational core shared by ``compute_playoff_seeds`` and the
    play-in simulator.  Callers that only need the summary DataFrame should use
    ``compute_playoff_seeds`` instead.

    Args:
        completed_df: Completed games with ``home_tricode``, ``away_tricode``,
            ``home_score``, ``away_score`` columns.
        remaining_df: Remaining games with ``home_tricode``, ``away_tricode``.
        home_wins_sim: ``(n_remaining_games, n_sims)`` float32 array of
            simulated outcomes.  Pass ``np.empty((0, 1))`` when there are no
            remaining games (e.g. to get actual final standings).
        team_meta: Optional tricode → ``{conference, division}`` mapping.
        seed: RNG seed for random-drawing tiebreakers.
        tiebreaker_counts: Optional dict updated in-place with tiebreaker stats.

    Returns:
        Dict with keys ``team_idx``, ``n_teams``, ``all_tricodes``, ``seeds``
        ``(n_teams, n_sims)``, ``total_wins`` ``(n_teams, n_sims)``,
        ``is_div_winner`` ``(n_teams, n_sims)``, ``team_conf``, ``team_div``,
        ``east_teams``, ``west_teams``, ``team_meta``.
        Returns ``None`` when there is insufficient data to compute seedings.
    """
    if team_meta is None:
        team_meta = load_team_metadata()

    if home_wins_sim.ndim < 2 or home_wins_sim.shape[1] == 0:
        return None

    n_sims = home_wins_sim.shape[1]

    # Build unified team index from all games
    all_in_games: set[str] = set()
    if not completed_df.empty:
        all_in_games |= set(completed_df["home_tricode"]) | set(completed_df["away_tricode"])
    if not remaining_df.empty:
        all_in_games |= set(remaining_df["home_tricode"]) | set(remaining_df["away_tricode"])
    all_tricodes = sorted(t for t in all_in_games if t in team_meta)
    if not all_tricodes:
        return None

    team_idx = {t: i for i, t in enumerate(all_tricodes)}
    n_teams = len(all_tricodes)

    team_conf = np.array([team_meta[t]["conference"] for t in all_tricodes])
    team_div = np.array([team_meta[t]["division"] for t in all_tricodes])

    metrics = _build_metrics(completed_df, remaining_df, home_wins_sim, team_idx, team_conf, team_div, n_sims)

    east_teams = [i for i in range(n_teams) if team_conf[i] == "East"]
    west_teams = [i for i in range(n_teams) if team_conf[i] == "West"]
    east_divs = sorted({team_div[t] for t in east_teams})
    west_divs = sorted({team_div[t] for t in west_teams})

    east_eligible = _compute_playoff_eligible(east_teams, metrics["total_wins"], n_sims)
    west_eligible = _compute_playoff_eligible(west_teams, metrics["total_wins"], n_sims)

    seeds = np.zeros((n_teams, n_sims), dtype=np.int32)
    is_div_winner = np.zeros((n_teams, n_sims), dtype=np.bool_)

    rng = np.random.default_rng(seed)
    stats: dict = tiebreaker_counts if tiebreaker_counts is not None else {}

    for s in range(n_sims):
        for conf_teams, divs, own_elig_list, other_elig_list in [
            (east_teams, east_divs, east_eligible, west_eligible),
            (west_teams, west_divs, west_eligible, east_eligible),
        ]:
            own_elig = own_elig_list[s]
            other_elig = other_elig_list[s]

            # Step 1: Determine division winners (without division-leader criterion)
            div_winners: set[int] = set()
            for div in divs:
                div_team_list = [t for t in conf_teams if team_div[t] == div]
                ordered = _seed_group_by_wins(
                    div_team_list,
                    s,
                    metrics,
                    team_div,
                    div_winners=set(),
                    own_elig=own_elig,
                    other_elig=other_elig,
                    is_div_tiebreak=True,
                    rng=rng,
                    stats=stats,
                )
                div_winners.add(ordered[0])
                is_div_winner[ordered[0], s] = True

            # Step 2: Seed the full conference
            ordered = _seed_group_by_wins(
                conf_teams,
                s,
                metrics,
                team_div,
                div_winners=div_winners,
                own_elig=own_elig,
                other_elig=other_elig,
                is_div_tiebreak=False,
                rng=rng,
                stats=stats,
            )
            for rank, team_i in enumerate(ordered):
                seeds[team_i, s] = rank + 1

    return {
        "team_idx": team_idx,
        "n_teams": n_teams,
        "all_tricodes": all_tricodes,
        "seeds": seeds,
        "total_wins": metrics["total_wins"],
        "is_div_winner": is_div_winner,
        "team_conf": team_conf,
        "team_div": team_div,
        "east_teams": east_teams,
        "west_teams": west_teams,
        "team_meta": team_meta,
    }


def _build_seeding_df(raw: dict) -> pd.DataFrame:
    """Build the standard seeding summary DataFrame from raw seeding arrays."""
    all_tricodes = raw["all_tricodes"]
    seeds = raw["seeds"]
    is_div_winner = raw["is_div_winner"]
    team_meta = raw["team_meta"]
    east_teams = raw["east_teams"]
    west_teams = raw["west_teams"]

    rows = []
    for i, tricode in enumerate(all_tricodes):
        conf = team_meta[tricode]["conference"]
        n_conf = len(east_teams) if conf == "East" else len(west_teams)
        ts = seeds[i]

        row: dict = {
            "tricode": tricode,
            "conference": conf,
            "division": team_meta[tricode]["division"],
            "mean_seed": float(ts.mean()),
            "median_seed": float(np.median(ts)),
        }
        for k in range(1, n_conf + 1):
            row[f"seed_{k}_pct"] = float((ts == k).mean())
        row["playoff_pct"] = float((ts <= 6).mean())
        row["play_in_pct"] = float(((ts >= 7) & (ts <= 10)).mean())
        row["lottery_pct"] = float((ts >= 11).mean())
        row["div_winner_pct"] = float(is_div_winner[i].mean())

        rows.append(row)

    return pd.DataFrame(rows)


def compute_playoff_seeds(
    completed_df: pd.DataFrame,
    remaining_df: pd.DataFrame,
    home_wins_sim: np.ndarray,
    team_meta: dict[str, dict[str, str]] | None = None,
    seed: int | None = None,
    tiebreaker_counts: dict | None = None,
) -> pd.DataFrame:
    """Compute playoff seed probabilities for each team from simulation results.

    Args:
        completed_df: Completed games with ``home_tricode``, ``away_tricode``,
            ``home_score``, ``away_score`` columns.
        remaining_df: Remaining games with ``home_tricode``, ``away_tricode``.
        home_wins_sim: ``(n_remaining_games, n_sims)`` float32 array of
            simulated game outcomes (1.0 = home win).
        team_meta: Optional tricode → ``{conference, division}`` mapping.
            Loaded from ``nba_teams.json`` if not provided.
        seed: RNG seed for the final random-drawing tiebreaker.
        tiebreaker_counts: Optional dict that will be updated in-place with
            counts of how often each tiebreaker resolved a tie.

    Returns:
        DataFrame with columns: tricode, conference, division, mean_seed,
        median_seed, seed_<N>_pct (1–15), playoff_pct, play_in_pct,
        lottery_pct, div_winner_pct.
    """
    if team_meta is None:
        team_meta = load_team_metadata()

    if home_wins_sim.ndim < 2 or home_wins_sim.shape[1] == 0:
        return pd.DataFrame()

    raw = compute_raw_seedings(
        completed_df,
        remaining_df,
        home_wins_sim,
        team_meta=team_meta,
        seed=seed,
        tiebreaker_counts=tiebreaker_counts,
    )
    if raw is None:
        return pd.DataFrame()

    return _build_seeding_df(raw)
