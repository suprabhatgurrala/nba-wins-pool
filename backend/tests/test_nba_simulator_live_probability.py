"""Live scores for unpriced games and stored playoff adjustments."""

import numpy as np
import pandas as pd
import pytest
from nba_schedule_snapshots import game_df_from_ratings, load_snapshot, sample_ratings

from nba_wins_pool.services.nba_simulator.core.game_probability import (
    game_probabilities,
    home_win_probability,
    live_home_win_probability,
)
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import (
    run_regular_season_simulation,
)
from nba_wins_pool.services.nba_simulator.core.schedule import GameStatus

_MIDSEASON = "2025-26-20251231"


@pytest.fixture(scope="module")
def midseason():
    return load_snapshot(_MIDSEASON)


class TestLiveProbability:
    def test_tipoff_is_the_pregame_probability(self):
        assert live_home_win_probability(0, 1.0, 4.0) == pytest.approx(home_win_probability(4.0, 0.0, home_court=0.0))

    def test_late_lead_is_nearly_decisive(self):
        assert live_home_win_probability(10, 1 / 48) > 0.99
        assert live_home_win_probability(-10, 1 / 48, 8.0) < 0.01
        assert live_home_win_probability(0, 1 / 2880, 6.0) == pytest.approx(0.5, abs=0.01)

    def test_unpriced_game_in_progress_uses_the_score(self, midseason):
        schedule = midseason.copy()
        upcoming = schedule.index[(schedule["status"] != GameStatus.FINAL) & schedule["home_tricode"].astype(bool)][0]
        schedule.loc[upcoming, ["status", "home_score", "away_score", "period", "game_clock"]] = [
            GameStatus.INGAME,
            98,
            90,
            4,
            "PT03M00.00S",
        ]
        df = game_probabilities(schedule, sample_ratings()).set_index("game_id")
        row = df.loc[schedule.at[upcoming, "game_id"]]
        assert row["prob_source"] == "live"
        assert np.isnan(row["rating_margin"])
        assert row["home_win_prob"] > 0.9
        schedule.loc[upcoming, "home_win_prob"] = 0.7
        row = game_probabilities(schedule, sample_ratings()).set_index("game_id").loc[schedule.at[upcoming, "game_id"]]
        assert (row["prob_source"], row["home_win_prob"]) == ("market", 0.7)


def test_stored_playoff_adjustments_without_a_market():
    schedule = load_snapshot("2025-26-20251004")
    ratings = sample_ratings()
    game_df = game_df_from_ratings(schedule, ratings)
    stored = {"OKC": -1.2, "GSW": 2.0}
    result = run_regular_season_simulation(
        schedule, game_df, n_sims=2000, seed=3, ratings=ratings, stored_playoff_adjustments=stored
    )
    delta = result.playoff_summary.set_index("tricode")["playoff_adjustment"]
    assert delta["OKC"] == -1.2 and delta["GSW"] == 2.0 and delta["BOS"] == 0.0


def test_stored_playoff_adjustments_when_the_market_has_no_semis_prices():
    schedule = load_snapshot("2025-26-20251004")
    ratings = sample_ratings()
    market = {t: {"win_finals_prob": 0.05, "win_conference_prob": 0.1} for t in ratings}
    result = run_regular_season_simulation(
        schedule,
        game_df_from_ratings(schedule, ratings),
        n_sims=2000,
        seed=3,
        ratings=ratings,
        playoff_market=market,
        stored_playoff_adjustments={"OKC": -1.2},
    )
    assert result.playoff_summary.set_index("tricode").loc["OKC", "playoff_adjustment"] == -1.2


def test_unpriced_playoff_game_in_progress_gets_a_live_probability():
    from nba_wins_pool.services.nba_simulator.data import _live_postseason_probabilities
    from nba_wins_pool.types.nba_game_type import NBAGameType

    schedule = pd.DataFrame(
        {
            "status": [GameStatus.INGAME, GameStatus.INGAME, GameStatus.INGAME],
            "game_type": [NBAGameType.PLAYOFFS, NBAGameType.PLAYOFFS, NBAGameType.REGULAR_SEASON],
            "home_score": [101, 88, 101],
            "away_score": [95, 88, 95],
            "period": [4, 4, 4],
            "game_clock": ["PT01M30.00S", "PT01M30.00S", "PT01M30.00S"],
            "home_win_prob": [np.nan, 0.62, np.nan],
            "away_win_prob": [np.nan, 0.38, np.nan],
        }
    )
    _live_postseason_probabilities(schedule)
    assert schedule.at[0, "home_win_prob"] > 0.9
    assert schedule.at[0, "home_win_prob"] + schedule.at[0, "away_win_prob"] == pytest.approx(1.0)
    assert schedule.at[1, "home_win_prob"] == 0.62
    assert np.isnan(schedule.at[2, "home_win_prob"])
