"""Playoff-phase calibration (core/calibration.calibrate_ratings): which teams get fit."""

import numpy as np
import pandas as pd
import pytest
from nba_schedule_snapshots import load_snapshot, sample_ratings

from nba_wins_pool.services.nba_simulator.core.calibration import build_ratings_array, calibrate_ratings
from nba_wins_pool.services.nba_simulator.core.play_in_tournament import (
    ConferencePlayInResults,
    compute_play_in_results,
)
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import compute_raw_seedings
from nba_wins_pool.services.nba_simulator.core.playoff_sim import (
    KnownSeriesResult,
    PlayoffBracketState,
    simulate_playoffs,
)
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import completed_standings_games


@pytest.fixture(scope="module")
def final_standings():
    schedule = load_snapshot("2025-26-20260525")
    raw = compute_raw_seedings(completed_standings_games(schedule), pd.DataFrame(), np.empty((0, 1), dtype=np.float32))
    by_seed = {
        conf: {int(raw["seeds"][i, 0]): raw["all_tricodes"][i] for i in teams}
        for conf, teams in (("East", raw["east_teams"]), ("West", raw["west_teams"]))
    }
    return raw, by_seed


def test_eliminated_teams_keep_their_ratings_and_play_in_winners_are_fit(final_standings):
    raw, seed = final_standings
    east, west = seed["East"], seed["West"]
    # East: the 9 seed wins the play-in (as the 8th seed) and is swept by the 1 seed.
    # West: the 9 seed wins the play-in and is still playing.
    play_in = {
        "East": ConferencePlayInResults(game_a_winner=east[7], game_b_winner=east[9], game_c_winner=east[9]),
        "West": ConferencePlayInResults(game_a_winner=west[7], game_b_winner=west[9], game_c_winner=west[9]),
    }
    bracket = PlayoffBracketState(
        {
            ("East", 1, east[1]): KnownSeriesResult(higher_seed_wins=4, lower_seed_wins=0),
            ("West", 1, west[1]): KnownSeriesResult(higher_seed_wins=1, lower_seed_wins=1),
        }
    )
    power = sample_ratings()
    start = dict(power)
    start[east[10]] = 2101.8  # a drifted rating from earlier runs: must stay put, not wander further
    rng = np.random.default_rng(0)
    market = {}
    for tc in raw["all_tricodes"]:
        title = float(rng.uniform(0.01, 0.2))
        market[tc] = {"win_finals_prob": title, "win_conference_prob": min(1.0, 2 * title)}

    result = calibrate_ratings(
        market, power, raw, play_in_results=play_in, bracket_state=bracket, n_sims=500, initial_ratings=start
    )

    out = {east[8], east[9], east[10], west[8], west[10]}  # play-in losers + East's swept 9 seed
    for tc in out:
        assert result.ratings[tc] == pytest.approx(start[tc]), tc
    assert result.ratings[east[10]] == pytest.approx(2101.8)
    # The West 9 seed came through the play-in and is still alive: it's fit like everyone else
    assert west[9] in result.ratings
    alive = [west[9], west[1], east[1], east[2], west[2]]
    assert any(result.ratings[tc] != pytest.approx(start[tc]) for tc in alive)


def test_recovers_market_priced_from_known_ratings(final_standings):
    """Mid round 1 (series finished, in progress and with a next-game price): a market
    priced by the Monte Carlo bracket from known ratings is reproduced from a different start."""
    raw, seed = final_standings
    east, west = seed["East"], seed["West"]
    play_in = {
        "East": ConferencePlayInResults(game_a_winner=east[7], game_b_winner=east[9], game_c_winner=east[9]),
        "West": ConferencePlayInResults(game_a_winner=west[7], game_b_winner=west[10], game_c_winner=west[8]),
    }
    bracket = PlayoffBracketState(
        {
            ("East", 1, east[1]): KnownSeriesResult(higher_seed_wins=3, lower_seed_wins=1),
            ("East", 1, east[2]): KnownSeriesResult(2, 2, next_game_home_win_prob=0.6),
            ("West", 1, west[1]): KnownSeriesResult(higher_seed_wins=4, lower_seed_wins=0),
        }
    )
    power = sample_ratings()
    tricodes = raw["all_tricodes"]
    truth = {tc: power[tc] + (i % 5 - 2) * 1.5 for i, tc in enumerate(tricodes)}
    n, n_t = 200_000, raw["n_teams"]
    seeds = np.repeat(raw["seeds"], n, axis=1)
    p7, p8 = compute_play_in_results(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds,
        n_teams=n_t,
        n_sims=n,
        rng=np.random.default_rng(1),
        power_ratings=power,
        team_idx=raw["team_idx"],
        play_in_results=play_in,
    )
    po_wins, champ, east_champ, west_champ = simulate_playoffs(
        east_teams=raw["east_teams"],
        west_teams=raw["west_teams"],
        seeds=seeds,
        total_wins=np.repeat(raw["total_wins"], n, axis=1),
        n_teams=n_t,
        n_sims=n,
        rng=np.random.default_rng(2),
        ratings=build_ratings_array(truth, tricodes),
        bracket_state=bracket,
        team_idx=raw["team_idx"],
        play_in_7=p7,
        play_in_8=p8,
    )
    market = {
        tc: {
            "reach_conf_semis_prob": float((po_wins[i] >= 4).mean()),
            "reach_conf_finals_prob": float((po_wins[i] >= 8).mean()),
            "win_conference_prob": float((east_champ == i).mean() + (west_champ == i).mean()),
            "win_finals_prob": float((champ == i).mean()),
        }
        for i, tc in enumerate(tricodes)
    }

    result = calibrate_ratings(market, power, raw, play_in_results=play_in, bracket_state=bracket)

    assert result.converged
    assert result.loss_final < 2e-4  # ~ the market's own sampling noise
    # Teams whose series are over keep their start
    assert result.ratings[west[8]] == pytest.approx(power[west[8]])
