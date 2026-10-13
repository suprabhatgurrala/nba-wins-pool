"""Tests for core/game_probability.py: ratings + home court + rest."""

import numpy as np
import pandas as pd
import pytest
from nba_schedule_snapshots import load_snapshot, sample_ratings

from nba_wins_pool.services.nba_simulator.core.constants import (
    REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS,
    REST_DAY_ADVANTAGE_POINTS_PER_DAY,
    SPREAD_TO_WIN_PROB_K,
)
from nba_wins_pool.services.nba_simulator.core.game_probability import (
    game_probabilities,
    home_win_probability,
    rest_days,
)
from nba_wins_pool.services.nba_simulator.core.schedule import CupRound
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.nba_game_type import NBAGameType


def _sigmoid(points: float) -> float:
    return 1.0 / (1.0 + np.exp(-SPREAD_TO_WIN_PROB_K * points))


def _game(game_id: str, when: str, home: str, away: str, **kw) -> dict:
    return {
        "game_id": game_id,
        "game_code": f"{when[:10].replace('-', '')}/{away}{home}",
        "date_time": pd.Timestamp(when, tz="UTC"),
        "home_tricode": home,
        "away_tricode": away,
        "home_score": None,
        "away_score": None,
        "status": NBAGameStatus.PREGAME,
        "game_type": NBAGameType.REGULAR_SEASON,
        "is_neutral": False,
        **kw,
    }


class TestHomeWinProbability:
    def test_ratings_and_rest_add_in_points(self):
        p = home_win_probability(3.0, 1.0, home_court=2.0, rest_adjustment=-1.0)
        assert p == pytest.approx(_sigmoid(3.0 - 1.0 + 2.0 - 1.0))


class TestRestDays:
    def test_back_to_back_cap_and_first_game(self):
        schedule = pd.DataFrame(
            [
                _game("1", "2025-11-03T00:00:00Z", "AAA", "BBB"),
                _game("2", "2025-11-04T00:30:00Z", "AAA", "CCC"),
                _game("3", "2025-11-10T00:00:00Z", "BBB", "AAA"),
            ]
        )
        rest = rest_days(schedule)
        assert rest.loc[0].isna().all()
        assert rest.loc[1, "home_rest"] == 0
        assert np.isnan(rest.loc[1, "away_rest"])
        assert rest.loc[2, "home_rest"] == 2
        assert rest.loc[2, "away_rest"] == 2

    def test_uses_eastern_dates(self):
        schedule = pd.DataFrame(
            [
                _game("1", "2025-11-03T00:30:00Z", "AAA", "BBB"),
                _game("2", "2025-11-04T03:00:00Z", "CCC", "AAA"),
            ]
        )
        assert rest_days(schedule).loc[1, "away_rest"] == 0

    def test_tbd_rows_ignored(self):
        schedule = pd.DataFrame(
            [_game("1", "2025-11-03T00:00:00Z", "AAA", "BBB"), _game("2", "2025-11-04T00:00:00Z", "", "")]
        )
        assert rest_days(schedule).loc[1].isna().all()


class TestGameProbabilities:
    def test_rest_neutral_market_and_exclusions(self):
        ratings = {"AAA": 1.0, "BBB": 0.0, "CCC": -1.0}
        schedule = pd.DataFrame(
            [
                _game("0022500001", "2025-11-02T00:00:00Z", "BBB", "AAA", status=NBAGameStatus.FINAL),
                _game("0022500002", "2025-11-03T00:00:00Z", "AAA", "CCC"),
                _game("0022500003", "2025-11-05T00:00:00Z", "BBB", "CCC", is_neutral=True),
                _game("0022500004", "2025-11-08T00:00:00Z", "CCC", "AAA", home_win_prob=0.42),
                _game("0062500001", "2025-11-09T00:00:00Z", "AAA", "BBB", cup_round=CupRound.CHAMPIONSHIP),
                _game("0052500101", "2025-11-10T00:00:00Z", "AAA", "BBB", game_type=NBAGameType.PLAY_IN),
            ]
        )
        df = game_probabilities(schedule, ratings).set_index("game_id")

        assert list(df.index) == ["0022500002", "0022500003", "0022500004"]
        assert df.loc["0022500002", "home_win_prob"] == pytest.approx(
            _sigmoid(1.0 - (-1.0) + REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS - 2 * REST_DAY_ADVANTAGE_POINTS_PER_DAY)
        )
        assert df.loc["0022500003", "home_win_prob"] == pytest.approx(
            _sigmoid(0.0 - (-1.0) + REST_DAY_ADVANTAGE_POINTS_PER_DAY)
        )
        assert df.loc["0022500003", "prob_source"] == "ratings"
        assert df.loc["0022500004", "home_win_prob"] == pytest.approx(0.42)
        assert df.loc["0022500004", "prob_source"] == "market"

    def test_in_progress_games_are_included(self):
        ratings = {"AAA": 3.0, "BBB": 0.0}
        schedule = pd.DataFrame(
            [
                _game(
                    "0022500001", "2025-11-03T00:00:00Z", "AAA", "BBB", status=NBAGameStatus.INGAME, home_win_prob=0.93
                ),
                _game("0022500002", "2025-11-03T00:00:00Z", "CCC", "DDD", status=NBAGameStatus.INGAME),
            ]
        )
        df = game_probabilities(schedule, ratings).set_index("game_id")
        assert df.loc["0022500001", "home_win_prob"] == pytest.approx(0.93)
        assert df.loc["0022500001", "prob_source"] == "market"
        assert df.loc["0022500002", "home_win_prob"] == pytest.approx(
            _sigmoid(REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS)
        )
        assert df.loc["0022500002", "prob_source"] == "ratings"

    def test_season_openers_are_rested(self):
        schedule = pd.DataFrame([_game("0022500001", "2025-10-22T00:00:00Z", "AAA", "BBB")])
        df = game_probabilities(schedule, {"AAA": 0.0, "BBB": 0.0})
        assert df.loc[0, "home_win_prob"] == pytest.approx(_sigmoid(REGULAR_SEASON_HOME_COURT_ADVANTAGE_POINTS))

    def test_requires_ratings(self):
        schedule = pd.DataFrame([_game("0022500002", "2025-11-03T00:00:00Z", "AAA", "CCC")])
        with pytest.raises(ValueError, match="Power ratings are required"):
            game_probabilities(schedule, {})

    def test_snapshot(self):
        schedule = load_snapshot("2025-26-20251107")
        df = game_probabilities(schedule, sample_ratings())
        upcoming = schedule[
            (schedule["status"] != NBAGameStatus.FINAL)
            & (schedule["game_code"] != "")
            & schedule["game_id"].str.startswith("002")
        ]
        assert len(df) == len(upcoming)
        assert df["home_win_prob"].between(0, 1).all()
