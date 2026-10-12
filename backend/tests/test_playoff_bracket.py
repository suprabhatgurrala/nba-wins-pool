"""Exact playoff probabilities (core/playoff_bracket.py) against the Monte Carlo bracket."""

import math

import numpy as np
import pandas as pd
import pytest
from nba_schedule_snapshots import game_df_from_ratings, load_snapshot, sample_ratings

from nba_wins_pool.services.nba_simulator.core.calibration import build_ratings_array
from nba_wins_pool.services.nba_simulator.core.constants import PLAYOFF_HOME_COURT_ADVANTAGE_POINTS
from nba_wins_pool.services.nba_simulator.core.play_in_tournament import (
    ConferencePlayInResults,
    compute_play_in_results,
)
from nba_wins_pool.services.nba_simulator.core.playoff_bracket import (
    Bracket,
    _higher_seed_series,
    series_win_probability,
)
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import compute_raw_seedings
from nba_wins_pool.services.nba_simulator.core.playoff_sim import (
    KnownSeriesResult,
    PlayoffBracketState,
    simulate_best_of_7,
    simulate_playoffs,
)
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import _simulate_games, completed_standings_games

_HCA = PLAYOFF_HOME_COURT_ADVANTAGE_POINTS


def _mc_rounds(playoff_wins, champion, east, west, n_teams):
    n = playoff_wins.shape[1]
    conf = (np.bincount(east, minlength=n_teams) + np.bincount(west, minlength=n_teams)) / n
    return np.stack(
        [(playoff_wins >= 4).mean(1), (playoff_wins >= 8).mean(1), conf, np.bincount(champion, minlength=n_teams) / n]
    )


def _within_noise(exact, mc, n, z=4.5):
    se = np.sqrt(exact * (1 - exact) / n) + 1e-6
    assert np.abs(mc - exact).max() < 0.01
    assert (np.abs(mc - exact) / se).max() < z


class TestSeries:
    def test_even_teams_favor_the_host(self):
        p = series_win_probability(0.6, 0.4)
        assert 0.5 < p < 0.6

    def test_matches_closed_form(self):
        # All seven games "played": P(4+ of 4 home games at p_h and 3 road games at p_a)
        p_h, p_a = 0.7, 0.45
        exact = sum(
            math.comb(4, x) * p_h**x * (1 - p_h) ** (4 - x) * math.comb(3, y) * p_a**y * (1 - p_a) ** (3 - y)
            for x in range(5)
            for y in range(4)
            if x + y >= 4
        )
        assert series_win_probability(p_h, p_a) == pytest.approx(exact)

    @pytest.mark.parametrize(
        "known",
        [
            None,
            KnownSeriesResult(2, 1),
            KnownSeriesResult(0, 3),
            KnownSeriesResult(3, 3),
            KnownSeriesResult(1, 1, next_game_home_win_prob=0.3),
        ],
    )
    @pytest.mark.parametrize("gap", [-6.0, 0.0, 4.0])
    def test_matches_simulated_series(self, known, gap):
        n = 200_000
        ratings = np.array([gap, 0.0], dtype=np.float32)
        _, _, won = simulate_best_of_7(
            np.zeros(n, np.int32), np.ones(n, np.int32), np.random.default_rng(0), n, ratings, known=known
        )
        exact = float(_higher_seed_series(np.float64(gap), np.float64(0.0), known))
        _within_noise(np.array([exact]), np.array([won.mean()]), n)

    def test_finished_series(self):
        assert series_win_probability(0.1, 0.1, KnownSeriesResult(4, 2)) == 1.0
        assert series_win_probability(0.9, 0.9, KnownSeriesResult(3, 4)) == 0.0


def test_preseason_brackets_match_monte_carlo():
    """Seeds, play-in and rating offsets vary by simulation; Finals home court by wins."""
    schedule = load_snapshot("2025-26-20251004")
    ratings = sample_ratings()
    game_df = game_df_from_ratings(schedule, ratings)
    game_df = game_df[game_df["game_id"].isin(schedule.loc[schedule["game_type"] == "Regular Season", "game_id"])]
    game_df = game_df.reset_index(drop=True)
    n = 60_000
    home_wins, _ = _simulate_games(game_df, n, seed=1)
    raw = compute_raw_seedings(completed_standings_games(schedule), game_df, home_wins, seed=2)
    n_t = raw["n_teams"]
    base = build_ratings_array(ratings, raw["all_tricodes"])
    offsets = np.random.default_rng(5).normal(0, 3, (n_t, n)).astype(np.float32)
    per_sim = base[:, None] + offsets
    p7, p8 = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=raw["seeds"],
        n_teams=n_t,
        n_sims=n,
        rng=np.random.default_rng(3),
        power_ratings=ratings,
        team_idx=raw["team_idx"],
        rating_offsets=offsets,
    )
    kw = dict(east_teams=raw["east_teams"], west_teams=raw["west_teams"], seeds=raw["seeds"])
    kw |= dict(total_wins=raw["total_wins"], n_teams=n_t, play_in_7=p7, play_in_8=p8)
    exact = Bracket(**kw).probabilities(per_sim)
    np.testing.assert_allclose(exact.sum(axis=1), [8, 4, 2, 1])
    mc = _mc_rounds(*simulate_playoffs(n_sims=n, rng=np.random.default_rng(9), ratings=per_sim, **kw), n_t)
    _within_noise(exact, mc, n)


def test_known_series_and_weights_match_monte_carlo():
    """Playoff phase: series finished, in progress (with a next-game price) and unplayed,
    over the play-in's distinct outcomes as weighted columns."""
    schedule = load_snapshot("2025-26-20260525")
    raw = compute_raw_seedings(completed_standings_games(schedule), pd.DataFrame(), np.empty((0, 1), np.float32))
    by_seed = {
        conf: {int(raw["seeds"][i, 0]): raw["all_tricodes"][i] for i in teams}
        for conf, teams in (("East", raw["east_teams"]), ("West", raw["west_teams"]))
    }
    east, west = by_seed["East"], by_seed["West"]
    play_in = {"East": ConferencePlayInResults(east[7], east[9], east[9]), "West": ConferencePlayInResults(west[7])}
    bracket = PlayoffBracketState(
        {
            ("East", 1, east[1]): KnownSeriesResult(4, 1),
            ("East", 1, east[2]): KnownSeriesResult(2, 2, next_game_home_win_prob=0.7),
            ("West", 1, west[1]): KnownSeriesResult(1, 1),
            ("East", 2, east[1]): KnownSeriesResult(1, 0),
        }
    )
    ratings = sample_ratings()
    n, n_t = 100_000, raw["n_teams"]
    seeds = np.repeat(raw["seeds"], n, axis=1)
    total_wins = np.repeat(raw["total_wins"], n, axis=1)
    p7, p8 = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds,
        n_teams=n_t,
        n_sims=n,
        rng=np.random.default_rng(3),
        power_ratings=ratings,
        team_idx=raw["team_idx"],
        play_in_results=play_in,
    )
    r = build_ratings_array(ratings, raw["all_tricodes"])
    kw = dict(east_teams=raw["east_teams"], west_teams=raw["west_teams"], n_teams=n_t)
    known = dict(bracket_state=bracket, team_idx=raw["team_idx"])
    mc = _mc_rounds(
        *simulate_playoffs(
            seeds=seeds,
            total_wins=total_wins,
            n_sims=n,
            rng=np.random.default_rng(9),
            ratings=r,
            play_in_7=p7,
            play_in_8=p8,
            **kw,
            **known,
        ),
        n_t,
    )
    # The same play-in draws, collapsed to distinct outcomes
    outcomes, first, counts = np.unique(np.concatenate([p7, p8]).T, axis=0, return_index=True, return_counts=True)
    m = len(outcomes)
    exact = Bracket(
        seeds=np.repeat(raw["seeds"], m, axis=1),
        total_wins=np.repeat(raw["total_wins"], m, axis=1),
        play_in_7=p7[:, first],
        play_in_8=p8[:, first],
        weights=counts / n,
        **kw,
        **known,
    ).probabilities(r)
    _within_noise(exact, mc, n)
    i = raw["team_idx"]
    assert exact[0, i[east[1]]] == 1.0 and exact[0, i[east[8]]] == 0.0  # the finished series
    assert exact[0, i[east[10]]] == 0.0  # lost the play-in
