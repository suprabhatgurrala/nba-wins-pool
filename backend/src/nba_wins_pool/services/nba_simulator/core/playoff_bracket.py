"""Exact playoff probabilities for seeded brackets (no series sampled).

Given each simulation's playoff seeds (and Finals home court), every team's chance
of winning each round is computed exactly, as :mod:`.playoff_sim` would estimate it
with infinitely many series draws:

- **Series**: the higher seed hosts games 1, 2, 5, 7. Who wins a best-of-7 doesn't
  change if all seven games are played, so P(higher seed wins) = P(it wins at least
  4 − its wins so far of the games left), a sum of independent games with home and
  road probabilities (:func:`series_win_probability`). Series in progress start from
  their score; a FanDuel price for the next game replaces that game's probability.
- **Bracket**: the NBA doesn't reseed, so a team's chance of winning a round is its
  chance of reaching it times the chance of beating each possible opponent, weighted
  by that opponent's chance of being there. Bracket positions have fixed seeds
  (1, 8, 4, 5, 2, 7, 3, 6), so home court below the Finals is fixed per pairing; the
  Finals go to the team with more regular-season wins (ties to the East).

Averaging over simulations (optionally weighted) gives each team's probability of
reaching the conference semis, reaching the conference finals, winning the
conference and winning the title. Fits use this instead of replaying series: it is
a smooth, noise-free function of the ratings.
"""

from __future__ import annotations

import numpy as np

from nba_wins_pool.services.nba_simulator.core.constants import PLAYOFF_HOME_COURT_ADVANTAGE_POINTS
from nba_wins_pool.services.nba_simulator.core.game_probability import home_win_probability, ratings_for
from nba_wins_pool.services.nba_simulator.core.playoff_sim import (
    _HOME_PATTERN,
    KnownSeriesResult,
    PlayoffBracketState,
    _team_at_play_in_seed,
    _team_at_seed,
)

# Seeds by bracket position: round-1 pairs (0, 1), (2, 3), (4, 5), (6, 7); positions
# 0–3 and 4–7 meet in round 2, the two halves in the conference finals
_POSITION_SEEDS = (1, 8, 4, 5, 2, 7, 3, 6)
N_ROUNDS = 4  # reach conference semis, reach conference finals, win conference, win title


def series_win_probability(
    p_home: np.ndarray,
    p_away: np.ndarray,
    known: KnownSeriesResult | None = None,
) -> np.ndarray:
    """P(the higher seed wins a best-of-7), elementwise.

    Args:
        p_home: The higher seed's win probability in its home games (1, 2, 5, 7).
        p_away: Its win probability in road games (3, 4, 6).
        known: Score so far, and optionally the market's probability for the next
            game's home team, as in :func:`.playoff_sim.simulate_best_of_7`.
    """
    p_home, p_away = np.broadcast_arrays(np.asarray(p_home, np.float64), np.asarray(p_away, np.float64))
    a, b = (known.higher_seed_wins, known.lower_seed_wins) if known else (0, 0)
    if a >= 4 or b >= 4:
        return np.full(p_home.shape, 1.0 if a >= 4 else 0.0)
    # dist[k]: P(the higher seed wins k of the remaining games counted so far)
    dist = [np.ones(p_home.shape)]
    for g in range(a + b, 7):
        p = p_home if _HOME_PATTERN[g] else p_away
        if g == a + b and known is not None and known.next_game_home_win_prob is not None:
            price = known.next_game_home_win_prob
            p = np.full(p_home.shape, price if _HOME_PATTERN[g] else 1.0 - price)
        q = 1.0 - p
        dist = [dist[0] * q] + [dist[k] * q + dist[k - 1] * p for k in range(1, len(dist))] + [dist[-1] * p]
    return sum(dist[4 - a :])


def _higher_seed_series(r_high: np.ndarray, r_low: np.ndarray, known: KnownSeriesResult | None = None) -> np.ndarray:
    """P(higher seed wins) from both teams' ratings, with the playoff home court."""
    if known is None:
        # Evenly spaced table: index directly instead of searching it
        x = (np.clip(np.asarray(r_high, np.float64) - r_low, -_TABLE_LIMIT, _TABLE_LIMIT) + _TABLE_LIMIT) / _TABLE_STEP
        i = np.minimum(x.astype(np.int64), len(_TABLE_PROB) - 2)
        return _TABLE_PROB[i] + (x - i) * _TABLE_SLOPE[i]
    hca = PLAYOFF_HOME_COURT_ADVANTAGE_POINTS
    p_home = home_win_probability(r_high, r_low, home_court=hca)
    p_away = 1.0 - home_win_probability(r_low, r_high, home_court=hca)
    return series_win_probability(p_home, p_away, known)


# An unplayed series depends only on the rating gap (higher seed minus lower): tabulated
# once on an even grid, linear interpolation error under 1e-7
_TABLE_STEP = 0.005
_TABLE_LIMIT = 80.0


def _series_table() -> np.ndarray:
    gap = np.linspace(-_TABLE_LIMIT, _TABLE_LIMIT, int(round(2 * _TABLE_LIMIT / _TABLE_STEP)) + 1)
    hca = PLAYOFF_HOME_COURT_ADVANTAGE_POINTS
    p_home = home_win_probability(gap, 0.0, home_court=hca)
    p_away = 1.0 - home_win_probability(0.0, gap, home_court=hca)
    return series_win_probability(p_home, p_away)


_TABLE_PROB = _series_table()
_TABLE_SLOPE = np.diff(_TABLE_PROB)


class _Known:
    """Known series by (conference, round), as (high-seed team index, result) pairs."""

    def __init__(self, bracket_state: PlayoffBracketState | None, team_idx: dict[str, int] | None):
        self.by_round: dict[tuple[str, int], list[tuple[int, KnownSeriesResult]]] = {}
        if bracket_state is None or not team_idx:
            return
        for (conf, rnd, high), result in bracket_state.series_results.items():
            if high in team_idx:
                self.by_round.setdefault((conf, rnd), []).append((team_idx[high], result))

    def series(self, conf: str, rnd: int, high: np.ndarray, r_high: np.ndarray, r_low: np.ndarray) -> np.ndarray:
        """P(higher seed wins), using the known state wherever *high* is a known series' host."""
        prob = _higher_seed_series(r_high, r_low)
        for team, result in self.by_round.get((conf, rnd), ()):
            here = high == team
            if here.any():
                prob = np.where(here, _higher_seed_series(r_high, r_low, result), prob)
        return prob


def _round(
    reach: np.ndarray,
    teams: np.ndarray,
    rating: np.ndarray,
    left: list[int],
    right: list[int],
    host_left,
    known: _Known,
    conf: str,
    rnd: int,
) -> np.ndarray:
    """Each position's chance of winning a round where *left* positions face *right* ones.

    Args:
        reach: ``(n_positions, n_sims)`` chance each position's team is in this round.
        teams / rating: ``(n_positions, n_sims)`` team indices and ratings.
        host_left: ``host_left[a][b]`` is True (a bool, or a per-simulation bool array)
            where ``left[a]`` has home court against ``right[b]``.
    """
    won = np.zeros_like(reach)
    for a, i in enumerate(left):
        for b, j in enumerate(right):
            host = host_left[a][b]
            if isinstance(host, (bool, np.bool_)):
                hi, lo = (i, j) if host else (j, i)
                p_high = known.series(conf, rnd, teams[hi], rating[hi], rating[lo])
                p_i = p_high if host else 1.0 - p_high
            else:
                high = np.where(host, teams[i], teams[j])
                r_i, r_j = rating[i], rating[j]
                p_high = known.series(conf, rnd, high, np.where(host, r_i, r_j), np.where(host, r_j, r_i))
                p_i = np.where(host, p_high, 1.0 - p_high)
            meet = reach[i] * reach[j]
            won[i] += meet * p_i
            won[j] += meet * (1.0 - p_i)
    return won


def _higher_seed_hosts(left: list[int], right: list[int]) -> list[list[bool]]:
    return [[_POSITION_SEEDS[i] < _POSITION_SEEDS[j] for j in right] for i in left]


class Bracket:
    """A set of seeded brackets (one per simulation), evaluated exactly for any ratings.

    Build once per fit (who holds each bracket position, Finals home court, known
    series); :meth:`probabilities` then only depends on the ratings.

    Args:
        east_teams / west_teams: Global indices of each conference's teams.
        seeds: ``(n_teams, n_sims)`` regular-season conference seeds.
        total_wins: ``(n_teams, n_sims)`` regular-season wins (Finals home court).
        n_teams: Total number of teams.
        play_in_7 / play_in_8: Optional ``(n_teams, n_sims)`` play-in winners, as for
            :func:`.playoff_sim.simulate_playoffs`.
        weights: ``(n_sims,)`` simulation weights (summing to 1); equal when omitted.
        bracket_state / team_idx: Known series (keyed by tricode) and the tricode → index map.
    """

    def __init__(
        self,
        east_teams: list[int],
        west_teams: list[int],
        seeds: np.ndarray,
        total_wins: np.ndarray,
        n_teams: int,
        *,
        play_in_7: np.ndarray | None = None,
        play_in_8: np.ndarray | None = None,
        weights: np.ndarray | None = None,
        bracket_state: PlayoffBracketState | None = None,
        team_idx: dict[str, int] | None = None,
    ):
        n_sims = seeds.shape[1]
        self.n_teams = n_teams
        self.weights = np.full(n_sims, 1.0 / n_sims) if weights is None else np.asarray(weights, np.float64)
        self.known = _Known(bracket_state, team_idx)

        def team_at(conf_arr: np.ndarray, seed: int) -> np.ndarray:
            if seed == 7 and play_in_7 is not None:
                return _team_at_play_in_seed(conf_arr, play_in_7)
            if seed == 8 and play_in_8 is not None:
                return _team_at_play_in_seed(conf_arr, play_in_8)
            return _team_at_seed(conf_arr, seeds, seed)

        # (8, n_sims) team at each bracket position, East then West
        self.teams = {
            conf: np.stack([team_at(np.asarray(arr, dtype=np.int32), s) for s in _POSITION_SEEDS])
            for conf, arr in (("East", east_teams), ("West", west_teams))
        }
        # Finals: the team with more regular-season wins hosts (ties to the East)
        sims = np.arange(n_sims)
        e_wins = total_wins[self.teams["East"], sims]
        w_wins = total_wins[self.teams["West"], sims]
        self.finals_east_hosts = e_wins[:, None, :] >= w_wins[None, :, :]  # (8, 8, n_sims)

    def probabilities(self, ratings: np.ndarray) -> np.ndarray:
        """``(N_ROUNDS, n_teams)``: P(reach conference semis), P(reach conference finals),
        P(win conference), P(win title), averaged over simulations.

        Args:
            ratings: ``(n_teams,)`` or ``(n_teams, n_sims)`` playoff ratings.
        """
        n_t, w, known = self.n_teams, self.weights, self.known
        out = np.zeros((N_ROUNDS, n_t))
        finalists = {}
        for conf, teams in self.teams.items():
            rating = np.stack([ratings_for(ratings, t) for t in teams]).astype(np.float64)
            # Round 1: fixed pairs, the better seed hosts
            r1 = np.zeros(teams.shape)
            ones = np.ones(teams.shape)
            for i in range(0, 8, 2):
                r1 += _round(ones, teams, rating, [i], [i + 1], [[True]], known, conf, 1)
            # Round 2: positions 0–1 vs 2–3, and 4–5 vs 6–7
            r2 = _round(r1, teams, rating, [0, 1], [2, 3], _higher_seed_hosts([0, 1], [2, 3]), known, conf, 2)
            r2 += _round(r1, teams, rating, [4, 5], [6, 7], _higher_seed_hosts([4, 5], [6, 7]), known, conf, 2)
            # Conference finals: 0–3 vs 4–7
            half_a, half_b = [0, 1, 2, 3], [4, 5, 6, 7]
            r3 = _round(r2, teams, rating, half_a, half_b, _higher_seed_hosts(half_a, half_b), known, conf, 3)
            for k, won in enumerate((r1, r2, r3)):
                out[k] += np.bincount(teams.ravel(), weights=(won * w).ravel(), minlength=n_t)
            finalists[conf] = (teams, rating, r3)

        # Finals: every East position against every West position
        teams = np.concatenate([finalists["East"][0], finalists["West"][0]])
        rating = np.concatenate([finalists["East"][1], finalists["West"][1]])
        reach = np.concatenate([finalists["East"][2], finalists["West"][2]])
        title = _round(
            reach, teams, rating, list(range(8)), list(range(8, 16)), self.finals_east_hosts, known, "Finals", 4
        )
        out[3] = np.bincount(teams.ravel(), weights=(title * w).ravel(), minlength=n_t)
        return out


def bracket_probabilities(
    east_teams: list[int],
    west_teams: list[int],
    seeds: np.ndarray,
    total_wins: np.ndarray,
    n_teams: int,
    ratings: np.ndarray,
    **kwargs,
) -> np.ndarray:
    """Exact ``(N_ROUNDS, n_teams)`` playoff probabilities (see :class:`Bracket`)."""
    return Bracket(east_teams, west_teams, seeds, total_wins, n_teams, **kwargs).probabilities(ratings)
