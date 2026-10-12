"""Play-in / playoff phases: play-in wins (played or simulated) count toward pool projections."""

import numpy as np
import pytest
from nba_schedule_snapshots import load_snapshot, sample_ratings

from nba_wins_pool.services.nba_simulator.core.play_in_tournament import ConferencePlayInResults
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import (
    completed_standings_games,
    count_wins_from_completed,
    run_play_in_simulation,
    run_playoff_simulation,
)
from nba_wins_pool.types.nba_game_status import NBAGameStatus

_N_SIMS = 300

# 2024 play-in: West 7v8 NOP-LAL (LAL won), 9v10 SAC-GSW (SAC won), final game NOP-SAC (NOP won);
# East 7v8 PHI-MIA (PHI won), 9v10 CHI-ATL (CHI won), final game MIA-CHI (MIA won).
_PLAY_IN_2024 = {
    "West": ConferencePlayInResults(game_a_winner="LAL", game_b_winner="SAC", game_c_winner="NOP"),
    "East": ConferencePlayInResults(game_a_winner="PHI", game_b_winner="CHI", game_c_winner="MIA"),
}
# Snapshot 2024-04-17: only the West's first two play-in games had been played
_PLAY_IN_2024_04_17 = {
    "West": ConferencePlayInResults(game_a_winner="LAL", game_b_winner="SAC"),
    "East": ConferencePlayInResults(),
}


def _postseason(name: str, play_in_results):
    schedule = load_snapshot(name)
    ratings = sample_ratings()
    win_stats, _, rs_wins_sim, all_tricodes = run_play_in_simulation(
        schedule, play_in_results, power_ratings=ratings, n_sims=_N_SIMS, seed=1
    )
    po = run_playoff_simulation(
        schedule, play_in_results, calibrated_ratings=ratings, power_ratings=ratings, n_sims=_N_SIMS, seed=1
    )
    po_wins = {tc: po.po_wins_sim[i] for i, tc in enumerate(po.all_tricodes)}
    return schedule, win_stats, po, po_wins


def test_played_play_in_wins_count_in_every_sim():
    _, _, _, po_wins = _postseason("2023-24-20240524", _PLAY_IN_2024)

    # Won the 9v10 game, lost the final play-in game: exactly one postseason win
    assert (po_wins["CHI"] == 1).all()
    assert (po_wins["SAC"] == 1).all()
    # Lost the 9v10 game
    assert (po_wins["ATL"] == 0).all()
    assert (po_wins["GSW"] == 0).all()
    # Won a play-in game and made the playoffs
    for team in ("LAL", "PHI", "NOP", "MIA"):
        assert (po_wins[team] >= 1).all()


def test_pending_play_in_wins_are_simulated():
    _, _, _, po_wins = _postseason("2023-24-20240417", _PLAY_IN_2024_04_17)

    assert (po_wins["GSW"] == 0).all()  # already eliminated
    assert (po_wins["LAL"] >= 1).all()  # already won the 7v8 game
    assert (po_wins["SAC"] >= 1).all()  # already won the 9v10 game
    # East 9/10 (CHI, ATL) haven't played: the 9v10 winner gets a win in every sim
    assert ((po_wins["CHI"] >= 1) | (po_wins["ATL"] >= 1)).all()
    assert 0 < (po_wins["CHI"] >= 1).mean() < 1


def test_play_in_wins_are_not_double_counted():
    schedule, win_stats, po, _ = _postseason("2023-24-20240524", _PLAY_IN_2024)

    # win_stats is regular season (+ Cup final) only; play-in wins live in the postseason wins
    rs_wins = count_wins_from_completed(completed_standings_games(schedule))
    stats = dict(zip(win_stats["tricode"], win_stats["mean_wins"]))
    assert stats["CHI"] == rs_wins["CHI"]
    assert stats["SAC"] == rs_wins["SAC"]

    summary = po.summary.set_index("tricode")
    i = po.all_tricodes.index("CHI")
    assert summary.loc["CHI", "mean_po_wins"] == pytest.approx(po.po_wins_sim[i].mean())
    assert summary.loc["CHI", "mean_po_wins"] == pytest.approx(1)
    assert np.isfinite(po.po_wins_sim).all()


def test_live_play_in_game_c_uses_market_odds():
    """A Game C in progress (West: NOP hosts SAC) uses its live FanDuel probability."""
    schedule = load_snapshot("2023-24-20240417")
    game_c = schedule["game_id"] == "0052300211"
    schedule.loc[game_c, "status"] = NBAGameStatus.INGAME
    schedule.loc[game_c, "home_win_prob"] = 1.0  # NOP has it locked up
    _, seeding, _, _ = run_play_in_simulation(
        schedule, _PLAY_IN_2024_04_17, power_ratings=sample_ratings(), n_sims=_N_SIMS, seed=1
    )
    seed_8 = seeding.set_index("tricode")["seed_8_pct"]
    assert seed_8["NOP"] == pytest.approx(1.0)
    assert seed_8["SAC"] == pytest.approx(0.0)
