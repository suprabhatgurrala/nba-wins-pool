"""Regular-season phase: seeds from our standings feed our own play-in and playoff brackets."""

import numpy as np
import pandas as pd
import pytest
from nba_schedule_snapshots import (
    SNAPSHOT_DIR,
    game_df_from_ratings,
    load_schedule_file,
    load_snapshot,
    sample_ratings,
)

from nba_wins_pool.services.nba_simulator.core.play_in_tournament import compute_play_in_results
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import compute_raw_seedings, load_team_metadata
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import (
    completed_standings_games,
    run_regular_season_simulation,
)
from nba_wins_pool.services.nba_simulator.core.schedule import GameStatus, GameType
from nba_wins_pool.types.nba_game_type import NBAGameType

_N_SIMS = 300
_TOTAL_RS_WINS = 30 * 82 // 2  # one win per regular-season game
_FULL_2024_25 = SNAPSHOT_DIR.parent / "sample-nba-schedule-response.json"


def _run(name: str, seed: int = 5, ratings: dict[str, float] | None = None, n_sims: int = _N_SIMS):
    schedule = load_snapshot(name)
    ratings = sample_ratings() if ratings is None else ratings
    game_df = game_df_from_ratings(schedule, ratings or sample_ratings())
    return run_regular_season_simulation(schedule, game_df, n_sims=n_sims, seed=seed, ratings=ratings or None)


class TestPostseasonFromSeeds:
    @pytest.mark.parametrize("name", ["2025-26-20251107", "2025-26-20260406"])
    def test_every_sim_has_a_full_postseason(self, name):
        result = _run(name)
        summary = result.playoff_summary

        assert summary["champ_pct"].sum() == pytest.approx(1)
        assert summary["conf_champ_pct"].sum() == pytest.approx(2)
        # The champion wins 16 playoff games (plus up to 2 play-in games)
        assert (result.po_wins_sim.max(axis=0) >= 16).all()
        # 6 play-in games + 15 best-of-7 series: winners take 60, losers 0-3 each
        po_games_won = result.po_wins_sim.sum(axis=0)
        assert ((po_games_won >= 6 + 60) & (po_games_won <= 6 + 60 + 45)).all()

    def test_bracket_rows_are_not_sampled_as_games(self):
        # 2026-04-06: 58 regular-season games left, TBD play-in rows and Finals placeholders on the schedule.
        # Pool regular-season wins must be exactly one per regular-season game plus the (played) Cup final.
        result = _run("2025-26-20260406")
        assert (result.rs_wins_sim.sum(axis=0) == _TOTAL_RS_WINS + 1).all()

    def test_pool_wins_add_postseason(self):
        result = _run("2025-26-20260406")
        rs_mean = dict(zip(result.win_stats["tricode"], result.win_stats["mean_wins"]))
        po_mean = dict(zip(result.playoff_summary["tricode"], result.playoff_summary["mean_po_wins"]))
        i = result.all_tricodes.index("OKC")
        assert result.po_wins_sim[i].mean() == pytest.approx(po_mean["OKC"])
        assert (result.rs_wins_sim[i] + result.po_wins_sim[i]).mean() == pytest.approx(rs_mean["OKC"] + po_mean["OKC"])

    def test_team_whose_season_is_over_keeps_its_wins(self):
        # OKC finishes its regular season early (e.g. others still have a postponed game to make up)
        schedule = load_snapshot("2025-26-20260406")
        okc_left = (
            (schedule["status"] != GameStatus.FINAL)
            & (schedule["game_type"] == GameType.REGULAR_SEASON)
            & ((schedule["home_tricode"] == "OKC") | (schedule["away_tricode"] == "OKC"))
        )
        assert okc_left.any()
        schedule.loc[okc_left, "status"] = GameStatus.FINAL
        okc_home = schedule["home_tricode"] == "OKC"
        schedule.loc[okc_left, "home_score"] = np.where(okc_home[okc_left], 110, 100)
        schedule.loc[okc_left, "away_score"] = np.where(okc_home[okc_left], 100, 110)
        game_df = game_df_from_ratings(schedule, sample_ratings())
        assert "OKC" not in set(game_df["home_tricode"]) | set(game_df["away_tricode"])

        result = run_regular_season_simulation(schedule, game_df, n_sims=_N_SIMS, seed=5, ratings=sample_ratings())
        assert len(result.all_tricodes) == 30
        i = result.all_tricodes.index("OKC")
        assert (result.rs_wins_sim[i] == result.rs_wins_sim[i, 0]).all()
        assert result.rs_wins_sim[i, 0] >= 60
        assert (result.rs_wins_sim.sum(axis=0) == _TOTAL_RS_WINS + 1).all()
        assert result.po_wins_sim[i].mean() > 0

    def test_requires_ratings(self):
        with pytest.raises(ValueError, match="Power ratings are required"):
            _run("2025-26-20260406", ratings={})

    def test_deterministic_with_seed(self):
        a, b = _run("2025-26-20260406", seed=9), _run("2025-26-20260406", seed=9)
        np.testing.assert_array_equal(a.po_wins_sim, b.po_wins_sim)
        pd.testing.assert_frame_equal(a.playoff_summary, b.playoff_summary)


def test_play_in_wins_out():
    """Each conference's three play-in games give out exactly three wins per simulation."""
    schedule = load_snapshot("2025-26-20260406")
    standings = completed_standings_games(schedule)
    raw = compute_raw_seedings(standings, pd.DataFrame(), np.empty((0, 1), dtype=np.float32), seed=0)
    n_sims = 400
    seeds = np.repeat(raw["seeds"], n_sims, axis=1)
    wins = np.zeros((raw["n_teams"], n_sims), dtype=np.float32)
    play_in_7, play_in_8 = compute_play_in_results(
        raw["east_teams"],
        raw["west_teams"],
        seeds,
        raw["n_teams"],
        n_sims,
        np.random.default_rng(1),
        sample_ratings(),
        raw["team_idx"],
        wins_out=wins,
    )
    assert (wins.sum(axis=0) == 6).all()
    assert (wins[play_in_7 == 1] >= 1).all()  # Game A winner
    assert (wins[play_in_8 == 1] >= 1).all()  # Game C winner
    assert not wins[(seeds < 7) | (seeds > 10)].any()


def _play_in_seeds(schedule: pd.DataFrame, total_wins: dict[str, float]) -> dict[str, int]:
    """Seeds 7-10 from each conference's two opening play-in games (7 hosts 8, 9 hosts 10).

    Older captures (2021-22, 2022-23) list play-in seeds as 0, so seeds come from the games
    themselves: the pair with the better records is 7v8, and the home team is the higher seed.
    """
    conf = {t: m["conference"] for t, m in load_team_metadata().items()}
    play_in = schedule[schedule["game_type"] == NBAGameType.PLAY_IN].sort_values("date_time")
    seeds: dict[str, int] = {}
    for c in ("East", "West"):
        openers = play_in[play_in["home_tricode"].map(conf) == c].head(2)
        by_wins = sorted(openers.itertuples(), key=lambda g: -(total_wins[g.home_tricode] + total_wins[g.away_tricode]))
        for game, high in zip(by_wins, (7, 9)):
            seeds[game.home_tricode], seeds[game.away_tricode] = high, high + 1
    return seeds


@pytest.mark.parametrize(
    "path",
    [
        SNAPSHOT_DIR / "schedule-2021-22-20220520.json.gz",
        SNAPSHOT_DIR / "schedule-2022-23-20230501.json.gz",
        SNAPSHOT_DIR / "schedule-2023-24-20240524.json.gz",
        _FULL_2024_25,
        SNAPSHOT_DIR / "schedule-2025-26-20260525.json.gz",
    ],
    ids=["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"],
)
def test_final_standings_match_nba_seeds(path):
    """Our tiebreakers must reproduce the NBA's seeds 1-10, since the RS phase builds brackets from them."""
    schedule = load_schedule_file(path)
    raw = compute_raw_seedings(
        completed_standings_games(schedule), pd.DataFrame(), np.empty((0, 1), dtype=np.float32), seed=0
    )
    ours = {tc: int(raw["seeds"][i, 0]) for i, tc in enumerate(raw["all_tricodes"])}
    total_wins = {tc: float(raw["total_wins"][i, 0]) for i, tc in enumerate(raw["all_tricodes"])}

    # Seeds 1-6 from first-round rows (later rows show seeds after the play-in); 7-10 from
    # the opening play-in games.
    nba: dict[str, int] = {}
    for row in schedule[schedule["game_type"] == NBAGameType.PLAYOFFS].itertuples():
        for tricode, seed in ((row.home_tricode, row.home_seed), (row.away_tricode, row.away_seed)):
            if tricode and pd.notna(seed) and 1 <= seed <= 6:
                nba.setdefault(tricode, int(seed))
    nba.update(_play_in_seeds(schedule, total_wins))

    assert len(nba) == 20
    assert sorted(nba.values()) == sorted(list(range(1, 11)) * 2)
    assert {tc: ours[tc] for tc in nba} == nba
