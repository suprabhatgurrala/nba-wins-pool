"""NBA tiebreaker rules (core/playoff_seeding.py) on hand-built ties, one criterion at a time.

Real seasons only reach some criteria (see test_final_standings_match_nba_seeds, 2021-22
through 2025-26: head-to-head, division winner, division and conference win pct, record vs
own-conference playoff teams). These cover the rest, plus the multi-team restarts.

Every scenario starts from records that are level on every criterion, then changes exactly
the one meant to decide.
"""

import numpy as np

from nba_wins_pool.services.nba_simulator.core.playoff_seeding import (
    _playoff_eligible_mask,
    _resolve_tie_group,
    _TieContext,
)

N = 6
DIVISIONS = np.array(["A", "A", "A", "B", "B", "B"])


def _metrics() -> dict:
    """Level records: 2 games between every pair, split 1-1; equal division/conference
    records and point differential."""
    h2h_games = np.full((N, N), 2, dtype=np.int32)
    np.fill_diagonal(h2h_games, 0)
    h2h_wins = np.ones((N, N, 1), dtype=np.int8)
    for t in range(N):
        h2h_wins[t, t] = 0
    return {
        "total_wins": np.full((N, 1), 41.0, dtype=np.float32),
        "div_wins": np.full((N, 1), 8.0, dtype=np.float32),
        "div_games": np.full(N, 16, dtype=np.int32),
        "conf_wins": np.full((N, 1), 26.0, dtype=np.float32),
        "conf_games": np.full(N, 52, dtype=np.int32),
        "h2h_wins": h2h_wins,
        "h2h_games": h2h_games,
        "pt_diff": np.zeros(N, dtype=np.float32),
    }


def _beat(m: dict, winner: int, loser: int, times: int = 1) -> None:
    """Move *times* of the pair's meetings to *winner* (games unchanged)."""
    m["h2h_wins"][winner, loser, 0] += times
    m["h2h_wins"][loser, winner, 0] -= times


def _resolve(
    teams: list[int],
    m: dict,
    *,
    div_winners: set[int] = frozenset(),
    own_elig: set[int] = frozenset(range(N)),
    other_elig: set[int] = frozenset(),
    is_div_tiebreak: bool = False,
    seed: int = 0,
) -> tuple[list[int], dict]:
    stats: dict = {}
    ctx = _TieContext(
        0,
        m,
        DIVISIONS,
        set(div_winners),
        set(own_elig),
        set(other_elig),
        is_div_tiebreak,
        np.random.default_rng(seed),
        stats,
    )
    return _resolve_tie_group(list(teams), ctx), stats


def _decided_by(stats: dict) -> set[str]:
    return set(stats) - {"ties_encountered"}


class TestTwoTeams:
    def test_head_to_head(self):
        m = _metrics()
        _beat(m, 1, 0)
        order, stats = _resolve([0, 1], m)
        assert order == [1, 0] and _decided_by(stats) == {"h2h"}

    def test_division_winner_beats_non_winner_across_divisions(self):
        order, stats = _resolve([0, 3], _metrics(), div_winners={3})
        assert order == [3, 0] and _decided_by(stats) == {"div_leader"}

    def test_division_winner_skipped_when_deciding_the_division(self):
        m = _metrics()
        m["div_wins"][1] = 9
        order, stats = _resolve([0, 1], m, div_winners={0}, is_div_tiebreak=True)
        assert order == [1, 0] and _decided_by(stats) == {"div_win_pct"}

    def test_division_record_only_within_a_division(self):
        m = _metrics()
        m["div_wins"][3] = 12
        m["conf_wins"][0] = 27
        order, stats = _resolve([0, 3], m)
        assert order == [0, 3] and _decided_by(stats) == {"conf_win_pct"}

    def test_conference_record(self):
        m = _metrics()
        m["conf_wins"][3] = 30
        order, stats = _resolve([0, 3], m)
        assert order == [3, 0] and _decided_by(stats) == {"conf_win_pct"}

    def test_record_vs_own_conference_playoff_teams(self):
        m = _metrics()
        _beat(m, 0, 2)
        _beat(m, 1, 5)
        _beat(m, 0, 5, -1)
        _beat(m, 1, 2, -1)
        order, stats = _resolve([0, 1], m, own_elig={0, 1, 2, 4})
        assert order == [0, 1] and _decided_by(stats) == {"vs_own_playoff"}

    def test_record_vs_other_conference_playoff_teams(self):
        m = _metrics()
        _beat(m, 1, 4)
        _beat(m, 0, 4, -1)
        order, stats = _resolve([0, 1], m, own_elig={0, 1, 2, 3}, other_elig={4})
        assert order == [1, 0] and _decided_by(stats) == {"vs_other_playoff"}

    def test_point_differential(self):
        m = _metrics()
        m["pt_diff"][:] = [10, 25, 0, 0, 0, 0]
        order, stats = _resolve([0, 1], m)
        assert order == [1, 0] and _decided_by(stats) == {"pt_diff"}

    def test_random_drawing_when_level_on_everything(self):
        orders = {tuple(_resolve([0, 1], _metrics(), seed=s)[0]) for s in range(20)}
        assert orders == {(0, 1), (1, 0)}
        assert _decided_by(_resolve([0, 1], _metrics())[1]) == {"random"}


class TestMultiTeam:
    def test_division_winner_first_then_each_side_restarts(self):
        m = _metrics()
        _beat(m, 1, 0)
        order, stats = _resolve([0, 1, 3], m, div_winners={3})
        assert order == [3, 1, 0]
        assert stats["div_leader"] == 1 and stats["h2h"] == 1

    def test_head_to_head_among_all(self):
        m = _metrics()
        _beat(m, 0, 1)
        _beat(m, 0, 2)
        _beat(m, 2, 1)
        order, stats = _resolve([0, 1, 2], m)
        assert order == [0, 2, 1] and _decided_by(stats) == {"h2h"}

    def test_separated_teams_restart_with_two_team_rules(self):
        m = _metrics()
        _beat(m, 1, 0)
        _beat(m, 0, 2)
        _beat(m, 2, 1)
        m["conf_wins"][0] = 27
        order, stats = _resolve([0, 1, 2], m)
        assert order == [0, 2, 1]
        assert stats["conf_win_pct"] == 1 and stats["h2h"] == 1

    def test_division_record_only_if_all_in_one_division(self):
        m = _metrics()
        m["div_wins"][3] = 12
        m["conf_wins"][1] = 27
        order, stats = _resolve([0, 1, 3], m)
        assert order[0] == 1 and "div_win_pct" not in stats
        assert stats["conf_win_pct"] == 1

    def test_division_record_when_all_in_one_division(self):
        m = _metrics()
        m["div_wins"][2] = 10
        order, stats = _resolve([0, 1, 2], m)
        assert order[0] == 2 and stats["div_win_pct"] == 1

    def test_point_differential_and_random(self):
        m = _metrics()
        m["pt_diff"][:] = [5, 5, 30, 0, 0, 0]
        order, stats = _resolve([0, 1, 2], m)
        assert order[0] == 2
        assert stats["pt_diff"] == 1 and stats["random"] == 1
        orders = {tuple(_resolve([0, 1, 2], m, seed=s)[0]) for s in range(20)}
        assert orders == {(2, 0, 1), (2, 1, 0)}


def test_playoff_eligible_includes_ties_for_tenth():
    """Top 10 by wins, plus anyone tied with 10th (NBA: "tied for one of the best ten records")."""
    wins = np.array([[60], [55], [50], [48], [46], [45], [44], [43], [42], [40], [40], [40], [35], [30], [20]], float)
    teams = list(range(15))
    eligible = _playoff_eligible_mask(teams, wins)[:, 0]
    assert eligible.sum() == 12
    assert not eligible[12:].any()
