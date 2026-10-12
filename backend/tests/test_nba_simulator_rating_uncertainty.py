"""Tests for core/rating_uncertainty.py: per-simulation rating offsets sized from FanDuel's X+ wins ladder."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from nba_schedule_snapshots import game_df_from_ratings, load_snapshot, sample_ratings
from scipy.stats import norm

from nba_wins_pool.services.nba_simulator.core.constants import GAME_MARGIN_SD
from nba_wins_pool.services.nba_simulator.core.rating_calibration import WinTotalModel
from nba_wins_pool.services.nba_simulator.core.rating_uncertainty import (
    DEFAULT_PRESEASON_RATING_SD,
    WinLadder,
    current_rating_sd,
    fit_ladder,
    games_played,
    preseason_equivalent_sd,
    preseason_rating_sd,
    schedule_as_of,
    shrink_rating_sd,
)
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import run_regular_season_simulation
from nba_wins_pool.services.nba_vegas_projections_service import NBAVegasProjectionsService

_PRESEASON = "2025-26-20251004"
_BEFORE_TIPOFF = datetime(2025, 10, 5)


def _ladder(mu: float, sigma: float, thresholds=range(20, 75, 5)) -> dict[int, float]:
    return {x: float(1 - norm.cdf((x - 0.5 - mu) / sigma)) for x in thresholds}


def test_fit_ladder_recovers_normal():
    mu, sigma = fit_ladder(_ladder(47.3, 7.9))
    assert mu == pytest.approx(47.3, abs=1e-6)
    assert sigma == pytest.approx(7.9, abs=1e-6)
    assert fit_ladder({50: 0.4}) is None  # one point can't give a spread


def test_shrink_and_preseason_equivalent_round_trip():
    assert shrink_rating_sd(3.0, 0) == pytest.approx(3.0)
    tau = shrink_rating_sd(3.0, 41)
    assert tau == pytest.approx(1.0 / np.sqrt(1 / 9 + 41 / GAME_MARGIN_SD**2))
    assert 1.5 < tau < 2.5
    assert preseason_equivalent_sd(tau, 41) == pytest.approx(3.0)
    assert shrink_rating_sd(0.0, 10) == 0.0


def test_recovers_rating_sd_from_ladders():
    """Ladders priced from a model with known τ give that τ back."""
    schedule = load_snapshot(_PRESEASON)
    ratings = sample_ratings()
    truth = {t: 2.0 + 0.05 * i for i, t in enumerate(sorted(ratings))}
    model = WinTotalModel(schedule, rating_sd=truth)
    mean, var = model.moments(model.ratings_array(ratings))
    ladders = {t: WinLadder(_ladder(mean[i], np.sqrt(var[i])), as_of=_BEFORE_TIPOFF) for i, t in enumerate(model.teams)}
    fitted = preseason_rating_sd(schedule, ladders, ratings)
    for t in truth:
        assert fitted[t] == pytest.approx(truth[t], abs=0.05), t


def test_teams_without_a_ladder_get_the_median_and_none_gets_the_default():
    schedule = load_snapshot(_PRESEASON)
    ratings = sample_ratings()
    model = WinTotalModel(schedule, rating_sd={t: 3.0 for t in ratings})
    mean, var = model.moments(model.ratings_array(ratings))
    ladders = {
        t: WinLadder(_ladder(mean[i], np.sqrt(var[i])), as_of=_BEFORE_TIPOFF)
        for i, t in enumerate(model.teams)
        if t != "BOS"
    }
    fitted = preseason_rating_sd(schedule, ladders, ratings)
    assert fitted["BOS"] == pytest.approx(np.median([fitted[t] for t in ladders]))
    assert set(preseason_rating_sd(schedule, {}, ratings).values()) == {DEFAULT_PRESEASON_RATING_SD}


def test_stored_uncertainty_fills_teams_without_a_ladder():
    """A ladder wins over the stored τ₀; teams without one keep theirs (else the median)."""
    schedule = load_snapshot(_PRESEASON)
    ratings = sample_ratings()
    model = WinTotalModel(schedule, rating_sd={t: 3.0 for t in ratings})
    mean, var = model.moments(model.ratings_array(ratings))
    ladders = {
        t: WinLadder(_ladder(mean[i], np.sqrt(var[i])), as_of=_BEFORE_TIPOFF)
        for i, t in enumerate(model.teams)
        if t not in ("BOS", "NYK")
    }
    stored = {"BOS": 4.2, "OKC": 1.0}
    fitted = preseason_rating_sd(schedule, ladders, ratings, stored=stored)
    plain = preseason_rating_sd(schedule, ladders, ratings)
    assert fitted["BOS"] == pytest.approx(4.2)
    assert fitted["NYK"] == pytest.approx(plain["NYK"])  # nothing stored: the median
    assert fitted["OKC"] == pytest.approx(plain["OKC"])  # its ladder wins
    # No ladders at all: stored values, else the default
    none = preseason_rating_sd(schedule, {}, ratings, stored=stored)
    assert (none["BOS"], none["OKC"], none["NYK"]) == (4.2, 1.0, DEFAULT_PRESEASON_RATING_SD)


def test_real_2026_27_ladder():
    """FanDuel's preseason ladder implies ~3 points of rating uncertainty, and the model then matches its spread."""
    response = json.loads((Path(__file__).parent / "fixtures" / "fanduel-win-ladder-2026-27.json").read_text())
    team_data: dict = {}
    NBAVegasProjectionsService(None, None, None)._collect_markets(response["attachments"]["markets"], team_data)
    to_tricode = NBAVegasProjectionsService.TEAM_NAME_TO_TRICODE
    ladders = {
        to_tricode[name]: WinLadder({int(k): v for k, v in data["win_threshold_probs"].items()}, _BEFORE_TIPOFF)
        for name, data in team_data.items()
    }
    assert len(ladders) == 30
    assert ladders["OKC"].probs[50] == pytest.approx(3000 / 3100)  # -3000 for OKC 50+

    # 2026-27 prices on the 2025-26 schedule: close enough in structure for the spread
    schedule = load_snapshot(_PRESEASON)
    ratings = sample_ratings()
    tau0 = preseason_rating_sd(schedule, ladders, ratings)
    assert np.median(list(tau0.values())) == pytest.approx(DEFAULT_PRESEASON_RATING_SD, abs=0.3)
    model = WinTotalModel(schedule, rating_sd=tau0)
    _, var = model.moments(model.ratings_array(ratings))
    ladder_sd = np.array([fit_ladder(ladders[t].probs)[1] for t in model.teams])
    np.testing.assert_allclose(np.sqrt(var), ladder_sd, atol=0.05)


def test_current_rating_sd_shrinks_with_games_played():
    preseason = {t: 3.0 for t in sample_ratings()}
    early = current_rating_sd(load_snapshot(_PRESEASON), preseason)
    midseason_schedule = load_snapshot("2025-26-20251231")
    later = current_rating_sd(midseason_schedule, preseason)
    played = games_played(midseason_schedule)
    assert early["BOS"] == pytest.approx(3.0)
    assert later["BOS"] == pytest.approx(shrink_rating_sd(3.0, played["BOS"]))
    assert later["BOS"] < 2.4


def test_schedule_as_of_unplays_later_games():
    schedule = load_snapshot("2025-26-20251231")
    cutoff = datetime(2025, 11, 1)
    before = schedule_as_of(schedule, cutoff)
    assert games_played(before) == games_played(schedule, before=cutoff)
    assert sum(games_played(before).values()) < sum(games_played(schedule).values())
    later = schedule["date_time"].dt.tz_convert("UTC").dt.tz_localize(None) >= cutoff
    assert (before.loc[later, "status"] == 1).all()
    assert before.loc[later, "home_score"].isna().all()


def test_simulation_spread_matches_model():
    """Offsetting ratings once per simulation widens season totals to what WinTotalModel predicts."""
    schedule = load_snapshot(_PRESEASON)
    ratings = sample_ratings()
    rating_sd = {t: 3.0 for t in ratings}
    game_df = game_df_from_ratings(schedule, ratings)
    model = WinTotalModel(schedule, rating_sd=rating_sd)
    mean, var = model.moments(model.ratings_array(ratings))
    fixed = run_regular_season_simulation(schedule, game_df, n_sims=4000, seed=3, ratings=ratings)
    uncertain = run_regular_season_simulation(
        schedule, game_df, n_sims=4000, seed=3, ratings=ratings, rating_sd=rating_sd
    )
    for i, tc in enumerate(uncertain.all_tricodes):
        j = model.idx[tc]
        # rs_wins_sim includes Cup Championship wins (pool), which the model excludes: a small extra spread
        assert uncertain.rs_wins_sim[i].std() == pytest.approx(np.sqrt(var[j]), rel=0.08), tc
        assert uncertain.rs_wins_sim[i].mean() == pytest.approx(mean[j], abs=0.6), tc
        assert uncertain.rs_wins_sim[i].std() > 1.5 * fixed.rs_wins_sim[i].std(), tc
    # Postseason uses the same offsets: title odds spread out from the favorites
    assert uncertain.playoff_summary["champ_pct"].max() < fixed.playoff_summary["champ_pct"].max()


def test_only_the_latest_fetch_is_fit():
    """A ladder FanDuel has since dropped isn't read against a later schedule: its team keeps
    the τ₀ stored while it was current (else the median)."""
    schedule = load_snapshot(_PRESEASON)
    ratings = sample_ratings()
    model = WinTotalModel(schedule, rating_sd={t: 3.0 for t in ratings})
    mean, var = model.moments(model.ratings_array(ratings))
    later = _BEFORE_TIPOFF + timedelta(days=3)
    ladders = {t: WinLadder(_ladder(mean[i], np.sqrt(var[i])), as_of=later) for i, t in enumerate(model.teams)}
    current = preseason_rating_sd(schedule, ladders, ratings)
    i = model.teams.index("BOS")
    ladders["BOS"] = WinLadder(_ladder(mean[i], 2 * np.sqrt(var[i])), as_of=later - timedelta(days=2))  # stale, wide
    fitted = preseason_rating_sd(schedule, ladders, ratings, stored={"BOS": 3.3})
    assert fitted["BOS"] == pytest.approx(3.3)
    assert fitted["NYK"] == pytest.approx(current["NYK"], abs=0.01)
    unstored = preseason_rating_sd(schedule, ladders, ratings)
    assert unstored["BOS"] == pytest.approx(np.median([unstored[t] for t in ladders if t != "BOS"]))
