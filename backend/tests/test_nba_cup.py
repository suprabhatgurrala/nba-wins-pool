"""Tests for nba_simulator/nba_cup.py using archived NBA schedule snapshots.

Snapshots in ``fixtures/nba-schedule-snapshots`` are ``scheduleLeagueV2_1.json`` captures
from the Wayback Machine, named ``schedule-<season>-<capture date>.json.gz``. Each Cup
season has a capture before the Cup (TBD knockout slots) and one after it.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from nba_schedule_snapshots import SNAPSHOT_DIR
from nba_schedule_snapshots import game_df_from_ratings as _game_df
from nba_schedule_snapshots import load_snapshot as _load_snapshot
from nba_schedule_snapshots import sample_ratings as _ratings

from nba_wins_pool.services.nba_simulator.core.constants import GAME_MARGIN_SD, SPREAD_TO_WIN_PROB_K
from nba_wins_pool.services.nba_simulator.core.game_probability import home_win_probability
from nba_wins_pool.services.nba_simulator.core.nba_cup import (
    REGULAR_SEASON_GAMES,
    _CupSimulator,
    has_cup,
    is_cup_championship,
    margins_from_uniforms,
    remaining_fraction,
    simulate_cup,
)
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import load_team_metadata
from nba_wins_pool.services.nba_simulator.core.regular_season_sim import (
    completed_standings_games,
    run_regular_season_simulation,
)
from nba_wins_pool.services.nba_simulator.core.schedule import CupRound, with_cup_rounds
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.nba_game_type import NBAGameType

_N_SIMS = 500


def _run(schedule: pd.DataFrame, ratings: dict[str, float] | None, seed: int = 1, **kwargs):
    game_df = _game_df(schedule, ratings or _ratings())
    rng = np.random.default_rng(seed)
    uniforms = rng.random((len(game_df), _N_SIMS)).astype(np.float32)
    home_wins = (uniforms < game_df["home_win_prob"].to_numpy()[:, None]).astype(np.float32)
    return simulate_cup(schedule, game_df, home_wins, uniforms, ratings, _N_SIMS, seed=seed, **kwargs)


def _scheduled_games(schedule: pd.DataFrame, tricodes: list[str]) -> np.ndarray:
    rs = schedule[
        (schedule["game_type"] == NBAGameType.REGULAR_SEASON)
        & ~is_cup_championship(schedule)
        & (schedule["home_tricode"] != "")
        & (schedule["away_tricode"] != "")
    ]
    counts = pd.concat([rs["home_tricode"], rs["away_tricode"]]).value_counts()
    return np.array([counts.get(t, 0) for t in tricodes])


def _after_group_stage(schedule: pd.DataFrame, knockouts_start: str) -> pd.DataFrame:
    """Roll a finished-Cup snapshot back to the state right after the group stage.

    Games from the quarterfinals on become PREGAME. Matchups the NBA only sets once the
    quarterfinals are played (semifinals, QF-loser games, Championship) become TBD, which
    is what the schedule looked like on 2023-12-03.
    """
    df = schedule.copy()
    # QF-loser games: each QF loser's next game
    tbd = df["cup_round"].isin([CupRound.SEMIFINAL, CupRound.CHAMPIONSHIP])
    for _, qf in df[df["cup_round"] == CupRound.QUARTERFINAL].iterrows():
        loser = qf["away_tricode"] if qf["home_score"] > qf["away_score"] else qf["home_tricode"]
        after = (df["date_time"] > qf["date_time"]) & ((df["home_tricode"] == loser) | (df["away_tricode"] == loser))
        tbd[df[after].sort_values("date_time").index[0]] = True
    later = df["date_time"] >= pd.Timestamp(knockouts_start, tz="US/Eastern")
    df.loc[later, ["status", "home_score", "away_score", "status_text"]] = [NBAGameStatus.PREGAME, None, None, ""]
    df.loc[tbd, ["home_tricode", "away_tricode", "game_code"]] = ""
    return df


_PRE_CUP_SEASONS = ("2021-22", "2022-23")
_CUP_SNAPSHOTS = sorted(
    p.name[9:-8] for p in SNAPSHOT_DIR.glob("schedule-*.json.gz") if p.name[9:16] not in _PRE_CUP_SEASONS
)


def test_margins_center_on_expected_margin():
    """Median margin is the expected margin, sign matches the sampled outcome, sd π/(k√3) ≈ 13.6 points."""
    expected = 4.065
    p = float(home_win_probability(expected, 0.0, home_court=0.0))
    u = np.random.default_rng(0).random(200_000)
    margins = margins_from_uniforms(np.array([p]), u[None, :])[0]
    assert margins_from_uniforms(np.array([p]), np.array([[0.5]]))[0, 0] == pytest.approx(expected)
    assert np.array_equal(margins > 0, u < p)
    assert np.median(margins) == pytest.approx(expected, abs=0.15)
    assert margins.std() == pytest.approx(np.pi / (SPREAD_TO_WIN_PROB_K * np.sqrt(3)), abs=0.2)
    assert margins.std() == pytest.approx(GAME_MARGIN_SD, abs=0.5)  # the measured spread of real margins
    assert np.abs(margins - expected).max() < 75


class TestLiveMargins:
    def test_live_form_reduces_to_pregame(self):
        p = 0.626
        u = np.random.default_rng(0).random((1, 10_000))
        expected = float(np.log(p / (1 - p)) / SPREAD_TO_WIN_PROB_K)
        pregame = margins_from_uniforms(np.array([p]), u)
        np.testing.assert_allclose(margins_from_uniforms(np.array([p]), u, current_margin=expected), pregame)

    @pytest.mark.parametrize(
        ("lead", "minutes_left", "p"),
        [(15, 5, 0.99), (15, 5, 0.90), (-3, 24, 0.40), (2, 0.1, 0.97), (10, 1, 0.0005)],
    )
    def test_centered_on_the_live_score(self, lead, minutes_left, p):
        u = np.random.default_rng(1).random((1, 50_000))
        margins = margins_from_uniforms(np.array([p]), u, current_margin=lead, remaining=minutes_left / 48)[0]
        assert np.isfinite(margins).all()
        assert np.array_equal(margins > 0, u[0] < p)  # the main simulation's outcome decides the sign
        assert (np.abs(margins) >= 1).all()
        if p < 0.01 and lead > 0:
            # Price contradicts the score (stale or suspended odds): a narrow loss, not a blowout
            assert np.median(margins) > -3 and margins.min() > -15
            return
        # The median stays near the current margin
        assert abs(np.median(margins) - lead) < 2
        # Spread scales with the time left (an upset maps into the far tail of the losing side),
        # never the full-game spread of a near-certain price (36 points at p = 0.99)
        assert np.abs(margins - lead).max() < 100 * np.sqrt(minutes_left / 48) + 5

    def test_remaining_fraction(self):
        assert remaining_fraction(0, None) == 1.0
        assert remaining_fraction(1, "PT12M00.00S") == 1.0
        assert remaining_fraction(4, "PT05M00.00S") == pytest.approx(5 / 48)
        assert remaining_fraction(2, "--:--") == pytest.approx(30 / 48)  # between periods: half the period
        assert remaining_fraction(5, "PT02M30.00S") == pytest.approx(2.5 / 48)

    def test_in_progress_group_game_uses_the_score(self):
        schedule = _load_snapshot("2025-26-20251107")
        group = schedule.index[(schedule["cup_round"] == CupRound.GROUP) & (schedule["status"] != NBAGameStatus.FINAL)]
        i = group[0]
        schedule.loc[i, ["status", "home_score", "away_score", "period", "game_clock", "home_win_prob"]] = [
            NBAGameStatus.INGAME,
            100,
            80,
            4,
            "PT02M00.00S",
            0.99,
        ]
        game_df = _game_df(schedule, _ratings())
        u = np.random.default_rng(2).random((len(game_df), _N_SIMS)).astype(np.float32)
        home_wins = (u < game_df["home_win_prob"].to_numpy()[:, None]).astype(np.float32)
        sim = _CupSimulator(
            schedule, game_df, home_wins, u, _ratings(), _N_SIMS, np.random.default_rng(0), load_team_metadata()
        )
        home_won, margin = sim._scheduled_outcome(schedule.loc[i], hca=True)
        assert np.array_equal(margin > 0, home_won)
        assert np.median(margin) == pytest.approx(20, abs=1.5)
        assert margin.max() < 40

        schedule.loc[i, "period"] = 5  # in overtime: counts 0 toward point differential
        _, margin = sim._scheduled_outcome(schedule.loc[i], hca=True)
        assert (margin == 0).all()


class TestHasCup:
    def test_no_cup_before_2023_24(self):
        # 2022-23 reuses the later seasons' knockout game IDs for ordinary games; no Cup games
        schedule = _load_snapshot("2022-23-20230409")
        assert schedule["cup_round"].isna().all()
        assert not has_cup(schedule)
        assert _run(schedule, _ratings()) is None

    @pytest.mark.parametrize("name", _CUP_SNAPSHOTS)
    def test_cup_rounds(self, name):
        schedule = _load_snapshot(name)
        assert has_cup(schedule)
        counts = schedule["cup_round"].value_counts()
        assert counts.to_dict() == {
            CupRound.GROUP: 60,
            CupRound.QUARTERFINAL: 4,
            CupRound.SEMIFINAL: 2,
            CupRound.CHAMPIONSHIP: 1,
        }
        rounds = schedule.dropna(subset=["cup_round"])
        last_qf = rounds.loc[rounds["cup_round"] == CupRound.QUARTERFINAL, "date_time"].max()
        sf = rounds.loc[rounds["cup_round"] == CupRound.SEMIFINAL, "date_time"]
        assert last_qf < sf.min() and sf.max() < rounds.loc[is_cup_championship(rounds), "date_time"].iloc[0]

    @pytest.mark.parametrize("name", _CUP_SNAPSHOTS)
    def test_groups_found_from_matchups(self, name):
        result = _run(_load_snapshot(name), _ratings())
        groups = result.summary.groupby("group")["tricode"].count()
        assert len(groups) == 6 and (groups == 5).all()
        assert result.summary["champ_pct"].sum() == pytest.approx(1)

    def test_groups_named_without_labels(self):
        # 2023-24 kept the group in seriesText, later seasons in gameSubLabel; neither is needed
        schedule = _load_snapshot("2025-26-20251107")
        schedule[["series_game_text", "series_status_text"]] = None
        groups = _run(schedule, _ratings()).summary["group"]
        assert sorted(groups.unique()) == [f"{c} Group {k}" for c in ("East", "West") for k in (1, 2, 3)]


class TestScheduledBracket:
    """Once the NBA sets the quarterfinals, they're used instead of our group standings."""

    @staticmethod
    def _quarterfinalist_loses_group_games(team: str) -> pd.DataFrame:
        # 2023-12-03: group stage final, quarterfinals set (IND is East seed 2)
        schedule = _load_snapshot("2023-24-20231203")
        rows = (schedule["cup_round"] == CupRound.GROUP) & (
            (schedule["home_tricode"] == team) | (schedule["away_tricode"] == team)
        )
        team_home = schedule["home_tricode"] == team
        schedule.loc[rows & team_home, ["home_score", "away_score"]] = [90, 120]
        schedule.loc[rows & ~team_home, ["home_score", "away_score"]] = [120, 90]
        return schedule

    def _check_real_bracket(self, schedule: pd.DataFrame):
        result = _run(schedule, _ratings())
        qf = schedule[schedule["cup_round"] == CupRound.QUARTERFINAL]
        real = set(qf["home_tricode"]) | set(qf["away_tricode"])
        knockout = result.summary.set_index("tricode")["knockout_pct"]
        assert set(knockout[knockout > 0].index) == real
        assert (knockout[list(real)] == 1).all()
        # No imaginary quarterfinal next to the real one: everyone still plays exactly 82
        scheduled = _scheduled_games(schedule, result.all_tricodes)
        assert (scheduled[:, None] + result.added_games == REGULAR_SEASON_GAMES).all()
        return result

    def test_real_quarterfinals_beat_our_standings(self):
        self._check_real_bracket(self._quarterfinalist_loses_group_games("IND"))

    def test_real_pairings_without_seeds(self):
        schedule = self._quarterfinalist_loses_group_games("IND")
        schedule[["home_seed", "away_seed"]] = None
        self._check_real_bracket(schedule)


@pytest.mark.parametrize(
    ("name", "after_quarterfinals"),
    [("2023-24-20240524", "2023-12-06"), ("2024-25-20250210", "2024-12-12"), ("2025-26-20260525", "2025-12-11")],
)
def test_quarterfinal_loser_hosts_match_the_nba(name, after_quarterfinals):
    """The QF loser who played on the road hosts the losers' game (the higher seed if both did)."""
    finished = _load_snapshot(name)
    schedule = _after_group_stage(finished, after_quarterfinals)  # QFs final, losers' games TBD
    qf = finished[finished["cup_round"] == CupRound.QUARTERFINAL]
    losers = {r.away_tricode if r.home_score > r.away_score else r.home_tricode for r in qf.itertuples()}
    real = finished[
        finished["home_tricode"].isin(losers)
        & finished["away_tricode"].isin(losers)
        & finished["cup_round"].isna()
        & (finished["date_time"] >= pd.Timestamp(after_quarterfinals, tz="US/Eastern"))
        & (finished["date_time"] <= finished.loc[is_cup_championship(finished), "date_time"].iloc[0])
    ]
    assert len(real) == 2
    teams = sorted(load_team_metadata())
    hosts = []
    original = _CupSimulator._play_filler

    def record(self, a, b, mask, deficit, a_first=True):
        home, away = self._host(a, b, a_first)
        hosts.extend({(teams[h], teams[w]) for h, w, m in zip(home, away, mask) if m})
        original(self, a, b, mask, deficit, a_first)

    with patch.object(_CupSimulator, "_play_filler", record):
        _run(schedule, _ratings())
    assert set(hosts) == set(zip(real["home_tricode"], real["away_tricode"]))


class TestUnexpectedKnockouts:
    """A knockout game missing from (or added to) the schedule can't shift the rounds."""

    @staticmethod
    def _drop_first_quarterfinal(schedule: pd.DataFrame) -> pd.DataFrame:
        qf = schedule.index[schedule["cup_round"] == CupRound.QUARTERFINAL][0]
        return with_cup_rounds(schedule.drop(index=qf).reset_index(drop=True))

    def test_only_the_championship_keeps_its_round(self):
        schedule = self._drop_first_quarterfinal(_load_snapshot("2025-26-20251107"))
        counts = schedule["cup_round"].value_counts().to_dict()
        assert counts == {CupRound.GROUP: 60, CupRound.KNOCKOUT: 5, CupRound.CHAMPIONSHIP: 1}
        champ = schedule[is_cup_championship(schedule)]
        assert champ["date_time"].iloc[0] == schedule.loc[schedule["cup_round"].notna(), "date_time"].max()

    def test_bracket_skipped_but_every_team_plays_82(self, caplog):
        schedule = self._drop_first_quarterfinal(_load_snapshot("2025-26-20251107"))
        with caplog.at_level("WARNING"):
            result = _run(schedule, _ratings())
        assert "Unexpected NBA Cup knockout games" in caplog.text
        assert result.summary["knockout_pct"].sum() == 0
        scheduled = _scheduled_games(schedule, result.all_tricodes)
        assert (scheduled[:, None] + result.added_games == REGULAR_SEASON_GAMES).all()

    def test_scheduled_championship_still_counts(self):
        # Matchup set but not played yet, and a quarterfinal row missing
        schedule = _load_snapshot("2025-26-20251231")
        champ = is_cup_championship(schedule)
        schedule.loc[champ, ["status", "home_score", "away_score"]] = [NBAGameStatus.PREGAME, None, None]
        schedule = self._drop_first_quarterfinal(schedule)
        result = _run(schedule, _ratings())
        assert (result.championship_wins.sum(axis=0) == 1).all()
        finalists = set(schedule.loc[is_cup_championship(schedule), ["home_tricode", "away_tricode"]].iloc[0])
        winners = result.summary.loc[result.summary["champ_pct"] > 0, "tricode"]
        assert set(winners) <= finalists


class TestBeforeCup:
    @pytest.mark.parametrize("name", ["2024-25-20241004", "2025-26-20251004", "2025-26-20251107"])
    def test_every_team_plays_82_games(self, name):
        schedule = _load_snapshot(name)
        result = _run(schedule, _ratings())

        scheduled = _scheduled_games(schedule, result.all_tricodes)
        assert set(scheduled) == {80}
        assert (scheduled[:, None] + result.added_games == REGULAR_SEASON_GAMES).all()

    @pytest.mark.parametrize("name", ["2024-25-20241004", "2025-26-20251107"])
    def test_wins_per_simulation(self, name):
        result = _run(_load_snapshot(name), _ratings())

        # 4 QF + 2 SF + 2 QF-loser games + 22 games among the eliminated teams
        assert (result.standings_wins.sum(axis=0) == 30).all()
        assert (result.championship_wins.sum(axis=0) == 1).all()

    def test_knockout_field(self):
        result = _run(_load_snapshot("2025-26-20251107"), _ratings())

        summary = result.summary
        for conf in ("East", "West"):
            assert summary.loc[summary["conference"] == conf, "knockout_pct"].sum() == pytest.approx(4)
            assert summary.loc[summary["conference"] == conf, "final_pct"].sum() == pytest.approx(1)
        assert summary["champ_pct"].sum() == pytest.approx(1)
        assert summary["group"].notna().all()

    def test_eliminated_team_slate(self):
        """22 games per sim: each team plays 2, exactly 2 are cross-conference, nobody plays both cross.

        Hosting matches the NBA's: every eliminated team gets one home and one road game.
        """
        conf = {t: m["conference"] for t, m in load_team_metadata().items()}
        teams = sorted(conf)
        calls = []
        original = _CupSimulator._play_filler
        sims = []

        def record(self, a, b, mask, deficit, a_first=True):
            home, away = self._host(a, b, a_first)
            calls.append((home.copy(), away.copy(), mask.copy()))
            sims.append(self)
            original(self, a, b, mask, deficit, a_first)

        with patch.object(_CupSimulator, "_play_filler", record):
            _run(_load_snapshot("2025-26-20251107"), _ratings())

        for s in range(_N_SIMS):
            games = [(teams[h[s]], teams[a[s]]) for h, a, m in calls if m[s]]
            cross = [g for g in games if conf[g[0]] != conf[g[1]]]
            assert len(games) == 2 + 22  # 2 QF-loser games + 22 eliminated-team games
            assert len(cross) == 2
            assert len({t for g in cross for t in g}) == 4
            assert all(a != b for a, b in games)
            hosts = pd.Series([h for h, _ in games]).value_counts()
            played = pd.Series([t for g in games for t in g]).value_counts()
            eliminated = played[played == 2].index
            assert len(eliminated) == 22 and (hosts.reindex(eliminated, fill_value=0) == 1).all()
        # Listed 40 + simulated QF/SF hosting + fillers lands in 40-42, like the real seasons: two QF
        # losers who both played on the road can't both host, and a QF + SF host reaches 42
        home_games = sims[0].home_games
        assert home_games.min() == 40 and home_games.max() == 42

    def test_cross_conference_games_are_bottom_finishers(self):
        """The two lowest group-play finishers per conference play cross-conference, 15th vs 15th
        and 14th vs 14th; the rest is within conference, one home and one road game each."""
        schedule = _load_snapshot("2025-26-20251107")
        game_df = _game_df(schedule, _ratings())
        u = np.random.default_rng(0).random((len(game_df), _N_SIMS)).astype(np.float32)
        sim = _CupSimulator(
            schedule,
            game_df,
            (u < 0.5).astype(np.float32),
            u,
            _ratings(),
            _N_SIMS,
            np.random.default_rng(0),
            load_team_metadata(),
        )
        teams = sim.all_tricodes
        conf = sim.conf
        # 4 per conference advanced; the rest need 2 games. Standings: random per sim.
        advanced = {t for c in ("East", "West") for t in [x for x in teams if conf[teams.index(x)] == c][:4]}
        deficit = np.array([[0 if t in advanced else 2] * _N_SIMS for t in teams])
        standings = np.random.default_rng(1).random((len(teams), _N_SIMS))
        games = []
        original = _CupSimulator._play_filler

        def record(self, a, b, mask, deficit, a_first=True):
            home, away = self._host(a, b, a_first)
            games.append((home.copy(), away.copy(), mask.copy()))
            original(self, a, b, mask, deficit, a_first)

        with patch.object(_CupSimulator, "_play_filler", record):
            sim._schedule_eliminated_teams(deficit, standings)
        assert (deficit == 0).all()

        for s_ in range(_N_SIMS):
            played = [(h[s_], a[s_]) for h, a, m in games if m[s_]]
            assert len(played) == 22
            cross = [g for g in played if conf[g[0]] != conf[g[1]]]
            bottom = {}
            for c in ("East", "West"):
                pool = [i for i, t in enumerate(teams) if conf[i] == c and t not in advanced]
                bottom[c] = sorted(pool, key=lambda i: standings[i, s_])[:2]  # [15th, 14th]
            expected = {frozenset((bottom["East"][k], bottom["West"][k])) for k in (0, 1)}
            assert {frozenset(g) for g in cross} == expected
            hosts = pd.Series([h for h, _ in played]).value_counts()
            assert len(hosts) == 22 and (hosts == 1).all()

    def test_requires_ratings(self):
        with pytest.raises(ValueError, match="Power ratings are required"):
            _run(_load_snapshot("2025-26-20251004"), ratings=None)

    def test_deterministic_with_seed(self):
        schedule = _load_snapshot("2025-26-20251107")
        a, b = _run(schedule, _ratings(), seed=7), _run(schedule, _ratings(), seed=7)
        np.testing.assert_array_equal(a.standings_wins, b.standings_wins)
        np.testing.assert_array_equal(a.championship_wins, b.championship_wins)


class TestAfterGroupStage:
    def test_only_undecided_matchups_are_simulated(self):
        schedule = _after_group_stage(_load_snapshot("2025-26-20251231"), "2025-12-09")
        result = _run(schedule, _ratings())

        scheduled = _scheduled_games(schedule, result.all_tricodes)
        assert (scheduled[:, None] + result.added_games == REGULAR_SEASON_GAMES).all()
        # 2 SF + 2 QF-loser games; the QFs and eliminated-team games are already scheduled
        assert (result.standings_wins.sum(axis=0) == 4).all()
        assert (result.championship_wins.sum(axis=0) == 1).all()

        knockout = set(result.summary.loc[result.summary["knockout_pct"] == 1, "tricode"])
        assert knockout == {"MIA", "ORL", "NYK", "TOR", "PHX", "OKC", "SAS", "LAL"}


class TestAfterCup:
    @pytest.mark.parametrize(
        ("name", "knockout", "champion"),
        [
            # 2024-25 needs the OT rule: HOU's Final/OT win must not count toward point differential
            ("2024-25-20250210", {"MIL", "ORL", "NYK", "ATL", "OKC", "DAL", "HOU", "GSW"}, "MIL"),
            ("2025-26-20251231", {"MIA", "ORL", "NYK", "TOR", "PHX", "OKC", "SAS", "LAL"}, "NYK"),
        ],
    )
    def test_bracket_matches_actual_results(self, name, knockout, champion):
        # No ratings: every matchup the bracket derives must match a played game
        result = _run(_load_snapshot(name), ratings=None)

        summary = result.summary.set_index("tricode")
        assert set(summary.index[summary["knockout_pct"] == 1]) == knockout
        assert set(summary.index[summary["knockout_pct"] == 0]) == set(summary.index) - knockout
        assert summary.loc[champion, "champ_pct"] == 1
        assert not result.added_games.any()
        assert not result.standings_wins.any()
        assert not result.championship_wins.any()


class TestRegularSeasonIntegration:
    def test_cup_wins_flow_into_projections(self):
        schedule = _load_snapshot("2025-26-20251107")
        ratings = _ratings()
        result = run_regular_season_simulation(
            schedule, _game_df(schedule, ratings), n_sims=200, seed=3, ratings=ratings
        )

        # 82 games x 30 teams / 2, plus the Championship (which counts toward the pool)
        assert len(result.all_tricodes) == 30
        assert (result.rs_wins_sim.sum(axis=0) == 30 * REGULAR_SEASON_GAMES / 2 + 1).all()
        assert len(result.seeding) == 30

    def test_championship_excluded_from_standings(self):
        schedule = _load_snapshot("2025-26-20251231")
        standings = completed_standings_games(schedule)
        assert not is_cup_championship(standings).any()
        assert is_cup_championship(schedule[schedule["status"] == NBAGameStatus.FINAL]).sum() == 1
