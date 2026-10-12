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
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Team metadata
# ---------------------------------------------------------------------------


def load_team_metadata() -> dict[str, dict[str, str]]:
    """Load team conference and division from the core's bundled nba_teams.json."""
    return json.loads((Path(__file__).parent / "nba_teams.json").read_text())


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
        h2h_wins   : (n_teams, n_teams, n_sims) int8 (at most 4-5 meetings per pair)
        h2h_games  : (n_teams, n_teams) int32
        pt_diff    : (n_teams,) float32  (completed games only)
    """
    n_teams = len(team_idx)

    # --- Completed-game accumulators (constant across sims) ---
    comp_wins = np.zeros(n_teams, dtype=np.float32)
    comp_div_wins = np.zeros(n_teams, dtype=np.float32)
    comp_conf_wins = np.zeros(n_teams, dtype=np.float32)
    comp_h2h = np.zeros((n_teams, n_teams), dtype=np.int8)
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

            comp_h2h[hi, ai] += int(hw)
            comp_h2h[ai, hi] += 1 - int(hw)
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
        remaining_h2h = np.zeros((n_teams, n_teams, n_sims), dtype=np.int8)
        for g in range(n_rem):
            hi, ai = int(r_home[g]), int(r_away[g])
            home_won = home_wins_sim[g] > 0.5
            remaining_h2h[hi, ai] += home_won
            remaining_h2h[ai, hi] += ~home_won
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
        remaining_h2h = np.zeros((n_teams, n_teams, n_sims), dtype=np.int8)

    return {
        "total_wins": comp_wins[:, None] + remaining_wins,
        "div_wins": comp_div_wins[:, None] + remaining_div_wins,
        "div_games": div_games,
        "conf_wins": comp_conf_wins[:, None] + remaining_conf_wins,
        "conf_games": conf_games,
        "h2h_wins": remaining_h2h + comp_h2h[:, :, None],
        "h2h_games": h2h_games,
        "pt_diff": pt_diff,
    }


def _playoff_eligible_mask(conf_teams: list[int], total_wins: np.ndarray) -> np.ndarray:
    """``(n_conf, n_sims)`` bool: the conference's playoff-eligible teams per sim (top 10 by
    wins, ties with 10th included)."""
    conf_wins = total_wins[conf_teams]
    partition_idx = max(len(conf_teams) - 10, 0)
    cutoff = np.partition(conf_wins, partition_idx, axis=0)[partition_idx]
    return conf_wins >= cutoff[None, :]


@dataclass
class _TieContext:
    """Everything one simulation's tiebreakers read, for one conference."""

    sim: int
    metrics: dict
    team_div: np.ndarray
    div_winners: set[int]
    own_elig: set[int]
    other_elig: set[int]
    is_div_tiebreak: bool
    rng: np.random.Generator
    stats: dict

    def count(self, criterion: str) -> None:
        self.stats[criterion] = self.stats.get(criterion, 0) + 1

    def wins(self, key: str, team: int) -> float:
        return float(self.metrics[key][team, self.sim])

    def win_pct(self, wins_key: str, games_key: str, team: int) -> float | None:
        games = int(self.metrics[games_key][team])
        return self.wins(wins_key, team) / games if games > 0 else None

    def record_vs(self, team: int, opponents) -> float | None:
        """Win pct of *team* against *opponents* (itself excluded)."""
        opps = [o for o in opponents if o != team]
        wins = sum(float(self.metrics["h2h_wins"][team, o, self.sim]) for o in opps)
        games = sum(int(self.metrics["h2h_games"][team, o]) for o in opps)
        return wins / games if games > 0 else None


def _pick(a: int, b: int, a_value: float | None, b_value: float | None) -> list[int] | None:
    """``[better, worse]`` when the values differ (and both exist), else None."""
    if a_value is None or b_value is None or a_value == b_value:
        return None
    return [a, b] if a_value > b_value else [b, a]


def _partition_by_criterion(teams: list[int], values: dict[int, float | None]) -> list[list[int]]:
    """Partition teams into groups with equal criterion values, best-first.

    If any team has a ``None`` value the criterion cannot differentiate —
    returns the original group unchanged.
    """
    if any(values[t] is None for t in teams):
        return [teams]

    sorted_teams = sorted(teams, key=lambda t: -values[t])
    return [list(g) for _, g in groupby(sorted_teams, key=lambda t: values[t])]


def _try_partition(teams: list[int], values: dict[int, float | None], criterion: str, ctx: _TieContext):
    """If *values* separates the teams, resolve each remaining tied subgroup from the top
    (two-team or multi-team procedure, as the NBA rules say). None when all are equal."""
    groups = _partition_by_criterion(teams, values)
    if len(groups) <= 1:
        return None
    ctx.count(criterion)
    return [t for group in groups for t in _resolve_tie_group(group, ctx)]


def _resolve_tie_group(teams: list[int], ctx: _TieContext) -> list[int]:
    """Order a group of teams with identical win totals, best first."""
    if len(teams) <= 1:
        return list(teams)
    ctx.count("ties_encountered")
    if len(teams) == 2:
        return _two_team_tiebreak(teams, ctx)
    return _multi_team_tiebreak(teams, ctx)


def _two_team_tiebreak(teams: list[int], ctx: _TieContext) -> list[int]:
    a, b = teams
    leaders = ctx.div_winners
    same_div = ctx.team_div[a] == ctx.team_div[b]
    criteria = (
        ("h2h", lambda t, o: float(ctx.metrics["h2h_wins"][t, o, ctx.sim]), True),
        ("div_leader", lambda t, o: float(t in leaders), not ctx.is_div_tiebreak),
        ("div_win_pct", lambda t, o: ctx.win_pct("div_wins", "div_games", t), same_div),
        ("conf_win_pct", lambda t, o: ctx.win_pct("conf_wins", "conf_games", t), True),
        ("vs_own_playoff", lambda t, o: ctx.record_vs(t, ctx.own_elig), True),
        ("vs_other_playoff", lambda t, o: ctx.record_vs(t, ctx.other_elig), True),
        ("pt_diff", lambda t, o: float(ctx.metrics["pt_diff"][t]), True),
    )
    for criterion, value, applies in criteria:
        if applies and (order := _pick(a, b, value(a, b), value(b, a))) is not None:
            ctx.count(criterion)
            return order
    # Random drawing
    ctx.count("random")
    return [a, b] if ctx.rng.random() < 0.5 else [b, a]


def _multi_team_tiebreak(teams: list[int], ctx: _TieContext) -> list[int]:
    if not ctx.is_div_tiebreak:
        leaders = [t for t in teams if t in ctx.div_winners]
        non_leaders = [t for t in teams if t not in ctx.div_winners]
        if leaders and non_leaders:
            ctx.count("div_leader")
            return _resolve_tie_group(leaders, ctx) + _resolve_tie_group(non_leaders, ctx)

    criteria = [
        ("h2h", lambda t: ctx.record_vs(t, teams)),
    ]
    if len({ctx.team_div[t] for t in teams}) == 1:
        criteria.append(("div_win_pct", lambda t: ctx.win_pct("div_wins", "div_games", t)))
    criteria += [
        ("conf_win_pct", lambda t: ctx.win_pct("conf_wins", "conf_games", t)),
        ("vs_own_playoff", lambda t: ctx.record_vs(t, ctx.own_elig)),
        ("pt_diff", lambda t: float(ctx.metrics["pt_diff"][t])),
    ]
    for criterion, value in criteria:
        if (result := _try_partition(teams, {t: value(t) for t in teams}, criterion, ctx)) is not None:
            return result

    # Random drawing
    ctx.count("random")
    order = ctx.rng.permutation(len(teams)).tolist()
    return [teams[i] for i in order]


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
    extra_wins: dict[str, np.ndarray] | None = None,
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
        extra_wins: Optional tricode → ``(n_sims,)`` wins from games outside
            *remaining_df* whose opponents vary by simulation (NBA Cup knockouts
            and the games they decide). Added to total wins only, not to the
            head-to-head, division or conference records: those games are 2 of 82 and
            only simulated while their matchups are TBD, when the season's uncertainty
            dwarfs them. Once on the schedule they're ordinary games with full records.

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
    for tc, wins in (extra_wins or {}).items():
        if tc in team_idx:
            metrics["total_wins"][team_idx[tc]] += wins

    east_teams = [i for i in range(n_teams) if team_conf[i] == "East"]
    west_teams = [i for i in range(n_teams) if team_conf[i] == "West"]
    east_divs = sorted({team_div[t] for t in east_teams})
    west_divs = sorted({team_div[t] for t in west_teams})

    eligible = {
        "East": (np.array(east_teams, dtype=np.int64), _playoff_eligible_mask(east_teams, metrics["total_wins"])),
        "West": (np.array(west_teams, dtype=np.int64), _playoff_eligible_mask(west_teams, metrics["total_wins"])),
    }

    def eligible_set(conf: str, sim: int) -> set[int]:
        members, mask = eligible[conf]
        return set(members[mask[:, sim]].tolist())

    seeds = np.zeros((n_teams, n_sims), dtype=np.int32)
    is_div_winner = np.zeros((n_teams, n_sims), dtype=np.bool_)
    sims = np.arange(n_sims)

    rng = np.random.default_rng(seed)
    stats: dict = tiebreaker_counts if tiebreaker_counts is not None else {}

    for conf, other, divs in (("East", "West", east_divs), ("West", "East", west_divs)):
        members = eligible[conf][0]
        wins = metrics["total_wins"][members]

        div_winners = []
        for div in divs:
            div_members = members[team_div[members] == div]
            div_wins = metrics["total_wins"][div_members]
            at_top = div_wins == div_wins.max(axis=0)
            winner = div_members[np.argmax(div_wins, axis=0)]
            for s_ in np.nonzero(at_top.sum(axis=0) > 1)[0]:
                ctx = _TieContext(
                    s_, metrics, team_div, set(), eligible_set(conf, s_), eligible_set(other, s_), True, rng, stats
                )
                ordered = _resolve_tie_group(div_members[at_top[:, s_]].tolist(), ctx)
                winner[s_] = ordered[0]
            is_div_winner[winner, sims] = True
            div_winners.append(winner)
        div_winners_arr = np.stack(div_winners)

        order = np.argsort(-wins + rng.random(wins.shape) * 0.5, axis=0)
        ordered_teams = members[order]
        sorted_wins = np.take_along_axis(wins, order, axis=0)
        n_conf = len(members)
        top = min(10, n_conf - 1)
        for s_ in np.nonzero((sorted_wins[:-1][:top] == sorted_wins[1:][:top]).any(axis=0))[0]:
            col = sorted_wins[:, s_]
            p = 0
            while p < top:
                q = p
                while q + 1 < n_conf and col[q + 1] == col[p]:
                    q += 1
                if q > p:
                    ctx = _TieContext(
                        s_,
                        metrics,
                        team_div,
                        set(div_winners_arr[:, s_].tolist()),
                        eligible_set(conf, s_),
                        eligible_set(other, s_),
                        False,
                        rng,
                        stats,
                    )
                    ordered_teams[p : q + 1, s_] = _resolve_tie_group(ordered_teams[p : q + 1, s_].tolist(), ctx)
                p = q + 1
        seeds[ordered_teams, sims] = np.arange(1, n_conf + 1)[:, None]

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


def build_seeding_df(raw: dict) -> pd.DataFrame:
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
    extra_wins: dict[str, np.ndarray] | None = None,
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
        extra_wins: Optional tricode → ``(n_sims,)`` wins added to total wins
            (see :func:`compute_raw_seedings`).

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
        extra_wins=extra_wins,
    )
    if raw is None:
        return pd.DataFrame()

    return build_seeding_df(raw)
