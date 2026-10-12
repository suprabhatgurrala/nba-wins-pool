"""Tests for core/rating_calibration.py: fitting ratings to market win totals and projected wins."""

from datetime import datetime, timedelta

import numpy as np
import pytest
from nba_schedule_snapshots import game_df_from_ratings, load_snapshot, sample_ratings

from nba_wins_pool.services.nba_simulator.core.rating_calibration import (
    WinTotal,
    WinTotalModel,
    fit_ratings_to_win_totals,
)
from nba_wins_pool.services.nba_simulator.core.rating_uncertainty import DEFAULT_PRESEASON_RATING_SD, current_rating_sd
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import run_regular_season_simulation
from nba_wins_pool.services.nba_simulator.nba_simulator_service import (
    _regular_season_ratings,
    _StoredTeamState,
    _win_targets,
)
from nba_wins_pool.utils.time import utc_now

_SNAPSHOT = "2025-26-20251107"  # ~12 games in, Cup group stage underway


def _market_from(schedule, true_ratings: dict[str, float]) -> dict[str, WinTotal]:
    """Win totals a market would post if it believed *true_ratings*: half-point line near the mean."""
    model = WinTotalModel(schedule)
    r = model.ratings_array(true_ratings)
    mean, _ = model.moments(r)
    lines = np.floor(mean) + 0.5
    over = model.over_prob_exact(r, np.arange(len(model.teams)), lines)
    return {t: WinTotal(float(lines[i]), float(over[i])) for i, t in enumerate(model.teams)}


@pytest.fixture(scope="module")
def schedule():
    return load_snapshot(_SNAPSHOT)


@pytest.fixture(scope="module")
def market(schedule):
    return _market_from(schedule, sample_ratings())


def test_recovers_ratings_from_win_totals(schedule, market):
    truth = sample_ratings()
    calib = fit_ratings_to_win_totals(schedule, market, prior={})

    assert calib.n_market_teams == 30
    assert calib.max_abs_error < 0.01
    teams = sorted(truth)
    fitted = np.array([calib.ratings[t] for t in teams])
    true = np.array([truth[t] for t in teams])
    # Only rating differences matter; the level is pinned by the prior (0 here)
    np.testing.assert_allclose(fitted - fitted.mean(), true - true.mean(), atol=0.5)


def test_no_lines_returns_prior(schedule):
    prior = {"OKC": 8.0, "WAS": -9.0}
    calib = fit_ratings_to_win_totals(schedule, {}, prior=prior)
    assert calib.n_market_teams == 0
    assert calib.ratings["OKC"] == 8.0
    assert calib.ratings["WAS"] == -9.0
    assert calib.ratings["BOS"] == 0.0


def test_teams_without_a_line_stay_near_prior(schedule, market):
    prior = {t: 0.0 for t in sample_ratings()} | {"WAS": -9.0, "UTA": -7.0}
    partial = {t: w for t, w in market.items() if t not in ("WAS", "UTA")}
    calib = fit_ratings_to_win_totals(schedule, partial, prior=prior)
    assert calib.n_market_teams == 28
    assert calib.ratings["WAS"] == pytest.approx(-9.0, abs=1.0)
    assert calib.ratings["UTA"] == pytest.approx(-7.0, abs=1.0)


def test_simulation_reproduces_market_over_probabilities(schedule, market):
    """End to end: Monte Carlo with fitted ratings (incl. Cup games) matches the market's over prices."""
    calib = fit_ratings_to_win_totals(schedule, market, prior={})
    result = run_regular_season_simulation(
        schedule, game_df_from_ratings(schedule, calib.ratings), n_sims=4000, seed=2, ratings=calib.ratings
    )
    for i, tc in enumerate(result.all_tricodes):
        # rs_wins_sim includes Cup Championship wins (pool), which the line excludes: at most +1 for 2 teams
        simulated = (result.rs_wins_sim[i] > market[tc].line).mean()
        assert simulated == pytest.approx(market[tc].over_prob, abs=0.05), tc


class TestExactWinDistribution:
    def test_is_a_bounded_distribution_with_the_model_mean(self, schedule):
        model = WinTotalModel(schedule)
        r = model.ratings_array(sample_ratings())
        teams = np.arange(len(model.teams))
        pmf = model.win_distribution(r, teams)
        np.testing.assert_allclose(pmf.sum(axis=1), 1.0)
        assert (pmf >= 0).all()
        mean, _ = model.moments(r)
        # Without rating uncertainty the Poisson-binomial mean is exactly the sum of probabilities
        np.testing.assert_allclose(model._base_wins + pmf @ np.arange(pmf.shape[1]), mean, atol=1e-9)
        remaining = (model._slot_game >= 0).sum(axis=1) + model._slot_cup.sum(axis=1)
        for i in teams:
            assert pmf[i, remaining[i] + 1 :].sum() == 0  # can't win more games than are left

    def test_matches_the_simulation_late_season(self):
        """~8 games left: bounded and skewed, where the normal approximation is worst."""
        schedule = load_snapshot("2025-26-20260402")
        ratings = sample_ratings()
        sd = {t: 2.0 for t in ratings}
        model = WinTotalModel(schedule, rating_sd=sd)
        r = model.ratings_array(ratings)
        mean, _ = model.moments(r)
        lines = np.floor(mean) + 0.5
        teams = np.arange(len(model.teams))
        exact = model.over_prob_exact(r, teams, lines)
        normal = model.over_prob(r, teams, lines)
        sim = run_regular_season_simulation(
            schedule, game_df_from_ratings(schedule, ratings), n_sims=20_000, seed=4, ratings=ratings, rating_sd=sd
        )
        idx = {t: i for i, t in enumerate(sim.all_tricodes)}
        # The Cup finalists' simulated totals include the (played) Championship, which the model excludes
        keep = [i for i, t in enumerate(model.teams) if t not in ("NYK", "SAS")]
        mc = np.array([(sim.rs_wins_sim[idx[model.teams[i]]] > lines[i]).mean() for i in keep])
        assert np.abs(exact[keep] - mc).max() < 0.015
        assert np.abs(exact[keep] - mc).mean() < np.abs(normal[keep] - mc).mean()


def test_recovers_ratings_from_projected_wins(schedule):
    """Mean-wins targets (e.g. ESPN BPI) alone pin down the ratings too."""
    truth = sample_ratings()
    model = WinTotalModel(schedule)
    mean, _ = model.moments(model.ratings_array(truth))
    projected = {t: float(mean[i]) for i, t in enumerate(model.teams)}
    calib = fit_ratings_to_win_totals(schedule, {}, prior={}, projected_wins=projected)

    assert (calib.n_market_teams, calib.n_projected_teams) == (0, 30)
    assert calib.max_abs_wins_error < 0.15  # wins sum to a fixed total, plus the weak prior pull
    teams = sorted(truth)
    fitted = np.array([calib.ratings[t] for t in teams])
    true = np.array([truth[t] for t in teams])
    np.testing.assert_allclose(fitted - fitted.mean(), true - true.mean(), atol=0.5)


def test_mixed_line_and_projected_targets(schedule, market):
    """Teams with a line fit the over price; the rest fit projected wins."""
    truth = sample_ratings()
    model = WinTotalModel(schedule)
    mean, _ = model.moments(model.ratings_array(truth))
    projected_only = ("WAS", "UTA", "OKC")
    lines = {t: w for t, w in market.items() if t not in projected_only}
    projected = {t: float(mean[model.idx[t]]) for t in projected_only}
    calib = fit_ratings_to_win_totals(schedule, lines, prior={}, projected_wins=projected)
    assert (calib.n_market_teams, calib.n_projected_teams) == (27, 3)
    assert calib.max_abs_error < 0.01
    assert calib.max_abs_wins_error < 0.1


class TestWinTargets:
    NOW = datetime(2026, 3, 12, 15, 0)

    def _fd(self, wins, days_old, over_prob=0.5):
        when = self.NOW - timedelta(days=days_old)
        return {"wins": wins, "over_prob": over_prob, "fetched_at": when, "projection_date": when.date()}

    def _espn(self, wins, hours_old=2):
        when = self.NOW - timedelta(hours=hours_old)
        return {"wins": wins, "over_prob": None, "fetched_at": when, "projection_date": when.date()}

    def test_blend_by_line_age(self):
        fanduel = {
            "OKC": self._fd(62.5, 0, over_prob=0.55),  # current line: over-prob target
            "BOS": self._fd(50.5, 3),  # 3 days old: weight 0.5
            "WAS": self._fd(20.5, 6),  # pulled: ESPN only
            "NYK": self._fd(53.5, 0, over_prob=None),  # current line without a price: mean target
        }
        espn = {"OKC": self._espn(61.0), "BOS": self._espn(48.0), "WAS": self._espn(18.0), "UTA": self._espn(22.0)}
        win_totals, projected, fetched_at = _win_targets(fanduel, espn, self.NOW)

        assert win_totals == {"OKC": WinTotal(62.5, 0.55)}
        assert projected["BOS"] == pytest.approx(0.5 * 50.5 + 0.5 * 48.0)
        assert projected["WAS"] == pytest.approx(18.0)
        assert projected["NYK"] == pytest.approx(53.5)  # no ESPN blend at full FanDuel weight
        assert projected["UTA"] == pytest.approx(22.0)  # never had a line
        assert fetched_at == self.NOW

    def test_stale_espn_ignored(self):
        fanduel = {"BOS": self._fd(50.5, 3), "WAS": self._fd(20.5, 6)}
        espn = {"BOS": self._espn(48.0, hours_old=48), "WAS": self._espn(18.0, hours_old=48)}
        win_totals, projected, _ = _win_targets(fanduel, espn, self.NOW)
        assert win_totals == {}
        assert projected == {"BOS": pytest.approx(50.5)}  # aging line alone; WAS has nothing current


class _FakeProjectionsRepo:
    def __init__(self, fanduel=None, espn=None, ladders=None, error: Exception | None = None):
        self.rows = {"fanduel": fanduel or {}, "espn_bpi": espn or {}}
        self.ladders = ladders or {}
        self.error = error

    async def get_latest_win_totals(self, season, source):
        if self.error:
            raise self.error
        return self.rows[source]

    async def get_latest_win_threshold_probs(self, season):
        if self.error:
            raise self.error
        return self.ladders


def _default_rating_sd(schedule):
    """No ladder: the default preseason uncertainty, shrunk by games played."""
    return current_rating_sd(schedule, {t: DEFAULT_PRESEASON_RATING_SD for t in sample_ratings()})


class _FakeNbaService:
    def get_current_season(self):
        return "2025-26"


class TestServiceRatings:
    async def test_fits_lines_and_espn_once_lines_are_pulled(self, schedule, market):
        now = utc_now()
        fanduel = {
            t: {"wins": w.line, "over_prob": w.over_prob, "fetched_at": now, "projection_date": now.date()}
            for t, w in market.items()
        }
        pulled = now - timedelta(days=10)
        fanduel["WAS"].update(fetched_at=pulled, projection_date=pulled.date())  # pulled from the board
        espn = {"WAS": {"wins": 15.0, "over_prob": None, "fetched_at": now, "projection_date": now.date()}}
        prior = {"WAS": -9.0}
        fit = await _regular_season_ratings(
            schedule,
            nba_service=_FakeNbaService(),
            projections_repo=_FakeProjectionsRepo(fanduel, espn),
            prior=prior,
            calibrate=True,
        )
        ratings, rating_sd, preseason_sd, fetched_at = fit.ratings, fit.rating_sd, fit.preseason_sd, fit.fetched_at
        assert fetched_at == now
        assert rating_sd == pytest.approx(_default_rating_sd(schedule))
        assert set(preseason_sd.values()) == {DEFAULT_PRESEASON_RATING_SD}
        expected = fit_ratings_to_win_totals(
            schedule,
            {t: w for t, w in market.items() if t != "WAS"},
            prior=prior,
            projected_wins={"WAS": 15.0},
            rating_sd=rating_sd,
        )
        assert ratings == pytest.approx(expected.ratings)

    async def test_prior_when_not_calibrating_or_on_error(self, schedule):
        prior = {"OKC": 8.0}
        kwargs = dict(nba_service=_FakeNbaService(), prior=prior)
        default_sd = pytest.approx(_default_rating_sd(schedule))
        for repo, calibrate in [
            (_FakeProjectionsRepo(), False),
            (None, True),
            (_FakeProjectionsRepo(error=RuntimeError("db down")), True),
        ]:
            fit = await _regular_season_ratings(schedule, projections_repo=repo, calibrate=calibrate, **kwargs)
            ratings, rating_sd, fetched_at = fit.ratings, fit.rating_sd, fit.fetched_at
            assert (ratings, fetched_at) == (prior, None)
            assert rating_sd == default_sd

    async def test_stored_uncertainty_once_the_ladder_is_gone(self, schedule):
        """No ladder rows (FanDuel pulled it): each team keeps the τ₀ stored with the last sim."""
        stored = {t: 2.0 + 0.05 * i for i, t in enumerate(sorted(sample_ratings()))}
        fit = await _regular_season_ratings(
            schedule,
            nba_service=_FakeNbaService(),
            projections_repo=_FakeProjectionsRepo(),
            prior={"OKC": 8.0},
            calibrate=False,
            stored=_StoredTeamState(preseason_sd=stored),
        )
        rating_sd, preseason_sd = fit.rating_sd, fit.preseason_sd
        assert preseason_sd == pytest.approx(stored)
        assert rating_sd == pytest.approx(current_rating_sd(schedule, stored))


async def test_stored_uncertainty_round_trips_through_saved_results():
    """τ₀, δ and the results cutoff saved with a run's team results are what the next run loads."""
    import uuid
    from datetime import datetime

    import numpy as np
    import pandas as pd

    from nba_wins_pool.models.team import LeagueSlug, Team
    from nba_wins_pool.services.nba_simulator.nba_simulator_service import (
        RawSimArrays,
        _build_team_records,
        _load_stored_state,
    )

    teams = {tc: Team(id=uuid.uuid4(), abbreviation=tc, name=tc, league=LeagueSlug.NBA) for tc in ("BOS", "NYK")}
    raw_sim = RawSimArrays(
        rs_wins_sim=np.zeros((2, 1), np.float32),
        po_wins_sim=np.zeros((2, 1), np.float32),
        all_tricodes=list(teams),
        preseason_rating_sd={"BOS": 2.7},
        ratings_through=datetime(2026, 11, 1, 23),
    )
    summary = pd.DataFrame({"tricode": list(teams), "mean_po_wins": [3.0, 2.0], "playoff_adjustment": [-0.5, 1.2]})
    records = _build_team_records(
        raw_sim,
        pd.DataFrame({"tricode": list(teams), "mean_wins": [50.0, 48.0]}),
        summary,
        {},
        teams,
        season="2026-27",
        phase_str="Regular Season",
        n_sims=1,
        simulated_at=datetime(2026, 10, 12),
    )
    assert {r.team_id: r.preseason_rating_sd for r in records} == {teams["BOS"].id: 2.7, teams["NYK"].id: None}

    class _SimRepo:
        async def get_latest_team_results(self, season):
            return records

    class _TeamRepo:
        async def get_all_by_league_slug(self, slug):
            return list(teams.values())

    state = await _load_stored_state(_SimRepo(), _TeamRepo(), "2026-27")
    assert state.preseason_sd == {"BOS": 2.7}
    assert state.playoff_adjustments == {"BOS": -0.5, "NYK": 1.2}
    assert state.ratings_through == datetime(2026, 11, 1, 23)
    assert (await _load_stored_state(None, None, "2026-27")).preseason_sd == {}
