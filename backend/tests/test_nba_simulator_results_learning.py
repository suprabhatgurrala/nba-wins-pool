"""Ratings learning from results, live scores for unpriced games, and stored playoff adjustments."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from nba_schedule_snapshots import game_df_from_ratings, load_snapshot, sample_ratings

from nba_wins_pool.services.nba_simulator.core.constants import GAME_MARGIN_SD
from nba_wins_pool.services.nba_simulator.core.game_probability import (
    game_probabilities,
    home_adjustment,
    home_win_probability,
    live_home_win_probability,
)
from nba_wins_pool.services.nba_simulator.core.rating_uncertainty import (
    games_played,
    results_cutoff,
    shrink_rating_sd,
    update_ratings_from_results,
)
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import (
    completed_standings_games,
    run_regular_season_simulation,
)
from nba_wins_pool.services.nba_simulator.core.schedule import GameStatus
from nba_wins_pool.services.nba_simulator.nba_simulator_service import _regular_season_ratings, _StoredTeamState

_MIDSEASON = "2025-26-20251231"
_TAU0 = 3.0


def _tip(schedule):
    return pd.to_datetime(schedule["date_time"], utc=True).dt.tz_localize(None)


@pytest.fixture(scope="module")
def midseason():
    return load_snapshot(_MIDSEASON)


class TestUpdateFromResults:
    def test_one_game_moves_both_ratings_by_their_share_of_the_surprise(self, midseason):
        done = completed_standings_games(midseason)
        tip = _tip(done)
        alone = tip[~tip.duplicated(keep=False)].sort_values()
        game = done.loc[alone.index[100]]
        after = _tip(done.loc[[game.name]]).iloc[0] - pd.Timedelta(seconds=1)
        # Only this game in the window
        assert ((tip > after) & (tip <= after + pd.Timedelta(seconds=1))).sum() == 1
        ratings = sample_ratings()
        sd = {t: _TAU0 for t in ratings}
        new = update_ratings_from_results(
            midseason, ratings, sd, after.to_pydatetime(), (after + pd.Timedelta(seconds=1)).to_pydatetime()
        )

        home, away = game["home_tricode"], game["away_tricode"]
        played = games_played(midseason, before=(after + pd.Timedelta(seconds=1)).to_pydatetime())
        var_h, var_a = shrink_rating_sd(_TAU0, played[home]) ** 2, shrink_rating_sd(_TAU0, played[away]) ** 2
        adj = home_adjustment(midseason, done.loc[[game.name]])[0]
        surprise = float(game["home_score"] - game["away_score"]) - (ratings[home] - ratings[away] + adj)
        total = GAME_MARGIN_SD**2 + var_h + var_a
        assert new[home] == pytest.approx(ratings[home] + var_h * surprise / total)
        assert new[away] == pytest.approx(ratings[away] - var_a * surprise / total)
        assert all(new[t] == ratings[t] for t in ratings if t not in (home, away))

    def test_windows_compose(self, midseason):
        """Hourly runs each applying their own window = one run over the whole span."""
        ratings, sd = sample_ratings(), {t: _TAU0 for t in sample_ratings()}
        a, b, c = datetime(2025, 11, 15), datetime(2025, 12, 1), datetime(2025, 12, 31)
        stepwise = update_ratings_from_results(
            midseason, update_ratings_from_results(midseason, ratings, sd, a, b), sd, b, c
        )
        assert stepwise == pytest.approx(update_ratings_from_results(midseason, ratings, sd, a, c))

    def test_learns_true_strength_from_simulated_results(self, midseason):
        """Results drawn from known ratings pull stale ratings toward them."""
        rng = np.random.default_rng(0)
        start = sample_ratings()
        truth = {t: r + rng.normal(0, _TAU0) for t, r in start.items()}
        schedule = midseason.copy()
        done = completed_standings_games(schedule)
        adj = home_adjustment(schedule, done)
        expected = done["home_tricode"].map(truth).to_numpy() - done["away_tricode"].map(truth).to_numpy() + adj
        margin = np.round(expected + rng.normal(0, GAME_MARGIN_SD, len(done)))
        margin[margin == 0] = 1
        schedule.loc[done.index, "home_score"] = 100 + np.maximum(margin, 0)
        schedule.loc[done.index, "away_score"] = 100 + np.maximum(-margin, 0)

        new = update_ratings_from_results(
            schedule, start, {t: _TAU0 for t in start}, datetime(2025, 10, 1), datetime(2025, 12, 31)
        )
        before = np.mean([abs(start[t] - truth[t]) for t in truth])
        after = np.mean([abs(new[t] - truth[t]) for t in truth])
        assert after < 0.75 * before

    def test_cutoff_stops_before_a_game_in_progress(self, midseason):
        schedule = midseason.copy()
        schedule.loc[schedule["status"] == GameStatus.INGAME, "status"] = GameStatus.PREGAME
        done = completed_standings_games(schedule)
        assert results_cutoff(schedule) == _tip(done).max().to_pydatetime()
        live = _tip(done).sort_values().index[-5]
        schedule.loc[live, "status"] = GameStatus.INGAME
        assert results_cutoff(schedule) == (_tip(schedule.loc[[live]]).iloc[0] - pd.Timedelta(microseconds=1))


async def test_service_applies_results_since_the_stored_cutoff(midseason):
    """The prior learns from games after the stored cutoff, and the new cutoff is stored."""
    from test_nba_simulator_rating_calibration import _FakeNbaService, _FakeProjectionsRepo

    prior = sample_ratings()
    since = datetime(2025, 12, 1)
    fit = await _regular_season_ratings(
        midseason,
        nba_service=_FakeNbaService(),
        projections_repo=_FakeProjectionsRepo(),
        prior=prior,
        calibrate=False,
        stored=_StoredTeamState(ratings_through=since),
    )
    through = results_cutoff(midseason)
    assert fit.ratings_through == through
    assert fit.ratings == pytest.approx(update_ratings_from_results(midseason, prior, fit.preseason_sd, since, through))
    assert fit.ratings != pytest.approx(prior)
    # Nothing stored yet (first run): ratings as they are, cutoff recorded from now on
    first = await _regular_season_ratings(
        midseason, nba_service=_FakeNbaService(), projections_repo=_FakeProjectionsRepo(), prior=prior, calibrate=False
    )
    assert first.ratings == prior and first.ratings_through == through


class TestLiveProbability:
    def test_tipoff_is_the_pregame_probability(self):
        assert live_home_win_probability(0, 1.0, 4.0) == pytest.approx(home_win_probability(4.0, 0.0, home_court=0.0))

    def test_late_lead_is_nearly_decisive(self):
        assert live_home_win_probability(10, 1 / 48) > 0.99
        assert live_home_win_probability(-10, 1 / 48, 8.0) < 0.01
        assert live_home_win_probability(0, 1 / 2880, 6.0) == pytest.approx(0.5, abs=0.01)  # tied at the buzzer

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
        # A shown live price still wins
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
    assert schedule.at[0, "home_win_prob"] > 0.9  # up 6 with 90 seconds left
    assert schedule.at[0, "home_win_prob"] + schedule.at[0, "away_win_prob"] == pytest.approx(1.0)
    assert schedule.at[1, "home_win_prob"] == 0.62  # a shown price is kept
    assert np.isnan(schedule.at[2, "home_win_prob"])  # regular season: priced with ratings later
