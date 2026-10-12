"""Regular-season phase: per-team playoff strength (rating + δ) fit to FanDuel's futures ladder."""

from datetime import timedelta

import numpy as np
import pytest
from nba_schedule_snapshots import game_df_from_ratings, load_snapshot, sample_ratings

from nba_wins_pool.services.nba_simulator.core.calibration import (
    PLAYOFF_ADJUSTMENT_MIN_PROB,
    PLAYOFF_ROUNDS,
    _Postseason,
    fit_playoff_adjustments,
)
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import compute_raw_seedings
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import (
    _simulate_games,
    completed_standings_games,
    run_regular_season_simulation,
)
from nba_wins_pool.services.nba_simulator.nba_simulator_service import (
    PLAYOFF_FUTURES_MAX_AGE,
    _load_playoff_market,
)
from nba_wins_pool.utils.time import utc_now

_PRESEASON = "2025-26-20251004"
_SIMS = 20_000


@pytest.fixture(scope="module")
def season():
    schedule = load_snapshot(_PRESEASON)
    ratings = sample_ratings()
    game_df = game_df_from_ratings(schedule, ratings)
    game_df = game_df[game_df["game_id"].isin(schedule.loc[schedule["game_type"] == "Regular Season", "game_id"])]
    game_df = game_df.reset_index(drop=True)
    home_wins, _ = _simulate_games(game_df, _SIMS, seed=1)
    raw = compute_raw_seedings(completed_standings_games(schedule), game_df, home_wins, seed=2)
    return schedule, ratings, raw


def _market(raw, ratings, truth: dict[str, float]) -> dict:
    """FanDuel-style ladder from a postseason with known adjustments (independent random numbers)."""
    delta = np.array([truth.get(t, 0.0) for t in raw["all_tricodes"]])
    prices = _Postseason.build(raw, ratings, None, _SIMS, seed=77).prices(delta)
    return {
        t: {k: float(prices[j, i]) for j, k in enumerate(PLAYOFF_ROUNDS)} for i, t in enumerate(raw["all_tricodes"])
    }


def _truth(ratings) -> dict[str, float]:
    best = sorted(ratings, key=lambda t: -ratings[t])
    return dict(zip(best[:8], [3.0, -2.0, 2.5, -1.5, 1.0, -3.0, 2.0, 1.5]))


def test_recovers_known_adjustments(season):
    _, ratings, raw = season
    truth = _truth(ratings)
    market = _market(raw, ratings, truth)
    fit = fit_playoff_adjustments(raw, ratings, market)
    # The ridge (and the market's own play-in draws) leave ~0.25 points
    for tc, d in truth.items():
        assert fit.adjustments[tc] == pytest.approx(d, abs=0.35), tc
    others = [d for tc, d in fit.adjustments.items() if tc not in truth]
    assert max(map(abs, others)) < 0.35
    # Prices reproduced with other play-in draws
    delta = np.array([fit.adjustments.get(t, 0.0) for t in raw["all_tricodes"]])
    replay = _Postseason.build(raw, ratings, None, _SIMS, seed=91).prices(delta)
    target = np.array([[market[t][k] for t in raw["all_tricodes"]] for k in PLAYOFF_ROUNDS])
    assert np.abs(replay - target).max() < 0.015


def test_long_shots_keep_zero(season):
    _, ratings, raw = season
    market = _market(raw, ratings, {})
    fit = fit_playoff_adjustments(raw, ratings, market)
    long_shots = {t for t, row in market.items() if row["reach_conf_semis_prob"] < PLAYOFF_ADJUSTMENT_MIN_PROB}
    assert long_shots and not long_shots & set(fit.adjustments)
    assert fit.n_market_teams == 30 - len(long_shots)
    # Market priced from unadjusted ratings: nothing to adjust
    assert max(map(abs, fit.adjustments.values())) < 0.1


def test_no_market_no_adjustments(season):
    _, ratings, raw = season
    assert fit_playoff_adjustments(raw, ratings, {}).adjustments == {}


def test_only_the_playoffs_change(season):
    schedule, ratings, raw = season
    truth = _truth(ratings)
    market = _market(raw, ratings, truth)
    game_df = game_df_from_ratings(schedule, ratings)
    plain = run_regular_season_simulation(schedule, game_df, n_sims=4000, seed=5, ratings=ratings)
    adjusted = run_regular_season_simulation(
        schedule, game_df, n_sims=4000, seed=5, ratings=ratings, playoff_market=market
    )
    np.testing.assert_array_equal(plain.rs_wins_sim, adjusted.rs_wins_sim)
    summary = adjusted.playoff_summary.set_index("tricode")
    assert summary.loc[list(truth), "playoff_adjustment"].abs().min() > 0
    assert (plain.playoff_summary["playoff_adjustment"] == 0).all()
    # Title odds move toward the market
    champ_market = {t: market[t]["win_finals_prob"] for t in truth}
    before = plain.playoff_summary.set_index("tricode").loc[list(truth), "champ_pct"]
    after = summary.loc[list(truth), "champ_pct"]
    assert sum(abs(after[t] - champ_market[t]) for t in truth) < sum(abs(before[t] - champ_market[t]) for t in truth)


class _FuturesRepo:
    def __init__(self, rows):
        self.rows, self.seasons = rows, []

    async def get_latest_fanduel_futures(self, season=None):
        self.seasons.append(season)
        return self.rows


async def test_load_playoff_market_drops_stale_rows():
    now = utc_now()
    rows = {
        "OKC": {"win_finals_prob": 0.24, "fetched_at": now - timedelta(hours=1)},
        "SAS": {"win_finals_prob": 0.21, "fetched_at": now - PLAYOFF_FUTURES_MAX_AGE - timedelta(hours=1)},
    }
    repo = _FuturesRepo(rows)
    market = await _load_playoff_market(repo, "2026-27", None)
    assert set(market) == {"OKC"} and repo.seasons == ["2026-27"]
    assert await _load_playoff_market(_FuturesRepo({}), "2026-27", None) is None
    # Futures passed in directly win, and rows without a fetch time are kept
    assert await _load_playoff_market(repo, "2026-27", {"BOS": {"win_finals_prob": 0.05}}) == {
        "BOS": {"win_finals_prob": 0.05}
    }
