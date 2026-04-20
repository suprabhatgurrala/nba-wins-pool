"""Tests for nba_simulator/data.py — combining play-in bracket, playoff bracket, and schedule."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nba_wins_pool.services.nba_simulator.data import (
    detect_season_phase,
    get_play_in_results,
    get_playoff_bracket_state,
)
from nba_wins_pool.services.nba_simulator.play_in_tournament import ConferencePlayInResults
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.nba_game_type import NBAGameType

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / name).read_text())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SCHEDULE_COLUMNS = [
    "date_time",
    "game_id",
    "game_code",
    "home_tricode",
    "away_tricode",
    "home_score",
    "away_score",
    "status",
    "game_type",
    "home_win_prob",
    "away_win_prob",
]
_SCHEDULE_DEFAULTS = {
    "date_time": pd.Timestamp("2025-04-15", tz="US/Eastern"),
    "game_id": "0",
    "game_code": "",
    "home_tricode": "HOM",
    "away_tricode": "AWY",
    "home_score": None,
    "away_score": None,
    "status": NBAGameStatus.PREGAME,
    "game_type": NBAGameType.REGULAR_SEASON,
    "home_win_prob": None,
    "away_win_prob": None,
}


def _make_schedule(*rows: dict) -> pd.DataFrame:
    """Build a minimal schedule DataFrame from row dicts."""
    if not rows:
        return pd.DataFrame(columns=_SCHEDULE_COLUMNS)
    return pd.DataFrame([{**_SCHEDULE_DEFAULTS, **r} for r in rows])


# ---------------------------------------------------------------------------
# detect_season_phase
# ---------------------------------------------------------------------------


class TestDetectSeasonPhase:
    def test_empty_schedule_returns_regular_season(self):
        schedule = _make_schedule()
        assert detect_season_phase(schedule) == NBAGameType.REGULAR_SEASON

    def test_only_regular_season_pregames(self):
        schedule = _make_schedule(
            {"status": NBAGameStatus.PREGAME, "game_type": NBAGameType.REGULAR_SEASON},
            {"status": NBAGameStatus.FINAL, "game_type": NBAGameType.PLAY_IN},
        )
        assert detect_season_phase(schedule) == NBAGameType.REGULAR_SEASON

    def test_play_in_pregames_detected(self):
        schedule = _make_schedule(
            {"status": NBAGameStatus.PREGAME, "game_type": NBAGameType.REGULAR_SEASON},
            {"status": NBAGameStatus.PREGAME, "game_type": NBAGameType.PLAY_IN},
        )
        assert detect_season_phase(schedule) == NBAGameType.PLAY_IN

    def test_playoff_pregames_detected(self):
        schedule = _make_schedule(
            {"status": NBAGameStatus.PREGAME, "game_type": NBAGameType.REGULAR_SEASON},
            {"status": NBAGameStatus.PREGAME, "game_type": NBAGameType.PLAYOFFS},
        )
        assert detect_season_phase(schedule) == NBAGameType.PLAYOFFS

    def test_play_in_takes_priority_over_regular_season(self):
        schedule = _make_schedule(
            {"status": NBAGameStatus.PREGAME, "game_type": NBAGameType.REGULAR_SEASON},
            {"status": NBAGameStatus.PREGAME, "game_type": NBAGameType.PLAY_IN},
            {"status": NBAGameStatus.PREGAME, "game_type": NBAGameType.PLAYOFFS},
        )
        # Play-In is checked first — but actually Playoffs also present, so…
        # Re-check the logic: PLAY_IN checked before PLAYOFFS → returns PLAY_IN
        assert detect_season_phase(schedule) == NBAGameType.PLAY_IN

    def test_completed_games_not_counted(self):
        # All final games; no PREGAME entries → regular season
        schedule = _make_schedule(
            {"status": NBAGameStatus.FINAL, "game_type": NBAGameType.PLAYOFFS},
        )
        assert detect_season_phase(schedule) == NBAGameType.REGULAR_SEASON


# ---------------------------------------------------------------------------
# get_play_in_results
# ---------------------------------------------------------------------------


PLAYIN_BRACKET = _load_fixture("sample-nba-playin-bracket-response.json")


def _mock_service_for_playin(bracket: dict | None = None):
    svc = MagicMock()
    svc.get_current_season.return_value = "2024-25"
    svc.fetch_play_in_bracket.return_value = bracket or PLAYIN_BRACKET
    return svc


class TestGetPlayInResults:
    def _call(self, schedule: pd.DataFrame, bracket: dict | None = None):
        mock_svc = _mock_service_for_playin(bracket)
        with patch("nba_wins_pool.services.nba_simulator.data._make_service", return_value=mock_svc):
            return get_play_in_results(schedule)

    def test_no_completed_play_in_games_returns_all_none(self):
        # Schedule has no FINAL PLAY_IN rows
        schedule = _make_schedule(
            {"status": NBAGameStatus.PREGAME, "game_type": NBAGameType.PLAY_IN, "game_id": "0052400101"},
        )
        results = self._call(schedule)

        assert set(results.keys()) == {"East", "West"}
        assert results["East"] == ConferencePlayInResults(None, None, None)
        assert results["West"] == ConferencePlayInResults(None, None, None)

    def test_east_game_a_winner_when_home_wins(self):
        # Game A East: ORL (7) vs ATL (8), game_id 0052400101 — ORL wins at home
        schedule = _make_schedule(
            {
                "status": NBAGameStatus.FINAL,
                "game_type": NBAGameType.PLAY_IN,
                "game_id": "0052400101",
                "home_tricode": "ORL",
                "away_tricode": "ATL",
                "home_score": 110,
                "away_score": 100,
            }
        )
        results = self._call(schedule)
        assert results["East"].game_a_winner == "ORL"
        assert results["East"].game_b_winner is None
        assert results["East"].game_c_winner is None

    def test_east_game_a_winner_when_away_wins(self):
        # ATL (away) wins
        schedule = _make_schedule(
            {
                "status": NBAGameStatus.FINAL,
                "game_type": NBAGameType.PLAY_IN,
                "game_id": "0052400101",
                "home_tricode": "ORL",
                "away_tricode": "ATL",
                "home_score": 98,
                "away_score": 105,
            }
        )
        results = self._call(schedule)
        assert results["East"].game_a_winner == "ATL"

    def test_west_game_a_winner(self):
        # Game A West: GSW vs MEM, game_id 0052400121
        schedule = _make_schedule(
            {
                "status": NBAGameStatus.FINAL,
                "game_type": NBAGameType.PLAY_IN,
                "game_id": "0052400121",
                "home_tricode": "GSW",
                "away_tricode": "MEM",
                "home_score": 115,
                "away_score": 108,
            }
        )
        results = self._call(schedule)
        assert results["West"].game_a_winner == "GSW"
        assert results["East"].game_a_winner is None

    def test_multiple_games_filled(self):
        # Game A East (ORL wins) + Game B West (SAC wins) + Game C East (ATL wins)
        schedule = _make_schedule(
            {
                "status": NBAGameStatus.FINAL,
                "game_type": NBAGameType.PLAY_IN,
                "game_id": "0052400101",  # East 7v8
                "home_tricode": "ORL",
                "away_tricode": "ATL",
                "home_score": 110,
                "away_score": 100,
            },
            {
                "status": NBAGameStatus.FINAL,
                "game_type": NBAGameType.PLAY_IN,
                "game_id": "0052400131",  # West 9v10
                "home_tricode": "SAC",
                "away_tricode": "DAL",
                "home_score": 102,
                "away_score": 99,
            },
            {
                "status": NBAGameStatus.FINAL,
                "game_type": NBAGameType.PLAY_IN,
                "game_id": "0052400201",  # East WvL
                "home_tricode": "ATL",
                "away_tricode": "MIA",
                "home_score": 95,
                "away_score": 112,
            },
        )
        results = self._call(schedule)
        assert results["East"].game_a_winner == "ORL"
        assert results["East"].game_b_winner is None
        assert results["East"].game_c_winner == "MIA"
        assert results["West"].game_b_winner == "SAC"

    def test_non_play_in_final_games_are_ignored(self):
        # A FINAL regular-season game with same game_id should not count
        schedule = _make_schedule(
            {
                "status": NBAGameStatus.FINAL,
                "game_type": NBAGameType.REGULAR_SEASON,
                "game_id": "0052400101",
                "home_tricode": "ORL",
                "away_tricode": "ATL",
                "home_score": 110,
                "away_score": 100,
            }
        )
        results = self._call(schedule)
        assert results["East"].game_a_winner is None

    def test_returns_conference_play_in_results_type(self):
        schedule = _make_schedule()
        results = self._call(schedule)
        assert isinstance(results["East"], ConferencePlayInResults)
        assert isinstance(results["West"], ConferencePlayInResults)


# ---------------------------------------------------------------------------
# get_playoff_bracket_state
# ---------------------------------------------------------------------------


PLAYOFF_BRACKET = _load_fixture("sample-nba-playoff-bracket-response.json")


def _mock_service_for_playoffs(bracket: dict | None = None):
    svc = MagicMock()
    svc.get_current_season.return_value = "2024-25"
    svc.fetch_playoff_bracket.return_value = bracket or PLAYOFF_BRACKET
    return svc


class TestGetPlayoffBracketState:
    def _call(self, schedule: pd.DataFrame, bracket: dict | None = None):
        mock_svc = _mock_service_for_playoffs(bracket)
        with patch("nba_wins_pool.services.nba_simulator.data._make_service", return_value=mock_svc):
            return get_playoff_bracket_state(schedule)

    def test_completed_series_are_present(self):
        # The fixture has all series completed — every series should appear in results
        schedule = _make_schedule()
        state = self._call(schedule)
        # Round 1 East: CLE (1) wins 4-0 over MIA (8)
        result = state.get("East", 1, "CLE")
        assert result is not None
        assert result.higher_seed_wins == 4
        assert result.lower_seed_wins == 0
        assert result.is_complete is True

    def test_round1_west_series_present(self):
        schedule = _make_schedule()
        state = self._call(schedule)
        # OKC (1) wins 4-0 over MEM (8)
        result = state.get("West", 1, "OKC")
        assert result is not None
        assert result.higher_seed_wins == 4
        assert result.lower_seed_wins == 0

    def test_upset_series_parsed_correctly(self):
        # GSW (7) beat HOU (2) in Round 1 — the series key uses HOU as highSeed
        schedule = _make_schedule()
        state = self._call(schedule)
        result = state.get("West", 1, "HOU")
        assert result is not None
        assert result.higher_seed_wins == 3  # HOU won 3
        assert result.lower_seed_wins == 4  # GSW won 4
        assert result.is_complete is True

    def test_nba_finals_mapped_to_finals_key(self):
        schedule = _make_schedule()
        state = self._call(schedule)
        # NBA Finals: OKC vs IND — OKC is highSeed
        result = state.get("Finals", 4, "OKC")
        assert result is not None
        assert result.higher_seed_wins == 4
        assert result.lower_seed_wins == 3

    def test_unstarted_series_not_in_state(self):
        # Build a bracket with one series having 0-0 wins
        minimal_bracket = {
            "bracket": {
                "playoffBracketSeries": [
                    {
                        "seriesId": "test",
                        "roundNumber": 1,
                        "seriesConference": "East",
                        "seriesText": "CLE leads 0-0",
                        "seriesStatus": 1,
                        "seriesWinner": 0,
                        "highSeedId": 1610612739,
                        "highSeedTricode": "CLE",
                        "highSeedRank": 1,
                        "highSeedSeriesWins": 0,
                        "highSeedRegSeasonWins": 64,
                        "highSeedRegSeasonLosses": 18,
                        "lowSeedId": 1610612748,
                        "lowSeedTricode": "MIA",
                        "lowSeedRank": 8,
                        "lowSeedSeriesWins": 0,
                        "lowSeedRegSeasonWins": 37,
                        "lowSeedRegSeasonLosses": 45,
                        "nextGameId": "0042400101",
                        "nextGameStatus": 1,
                    }
                ]
            }
        }
        schedule = _make_schedule()
        state = self._call(schedule, bracket=minimal_bracket)
        assert state.get("East", 1, "CLE") is None

    def test_home_win_prob_set_for_in_progress_series(self):
        # Build a bracket with one in-progress series (1-0 lead)
        minimal_bracket = {
            "bracket": {
                "playoffBracketSeries": [
                    {
                        "seriesId": "test",
                        "roundNumber": 1,
                        "seriesConference": "East",
                        "highSeedTricode": "CLE",
                        "highSeedSeriesWins": 1,
                        "lowSeedSeriesWins": 0,
                        "nextGameId": "0042400102",
                        "nextGameStatus": 1,
                    }
                ]
            }
        }
        schedule = _make_schedule(
            {
                "status": NBAGameStatus.PREGAME,
                "game_type": NBAGameType.PLAYOFFS,
                "game_id": "0042400102",
                "home_tricode": "CLE",
                "away_tricode": "MIA",
                "home_win_prob": 0.72,
            }
        )
        state = self._call(schedule, bracket=minimal_bracket)
        result = state.get("East", 1, "CLE")
        assert result is not None
        assert result.next_game_home_win_prob == pytest.approx(0.72)

    def test_home_win_prob_none_when_no_pregame_odds(self):
        minimal_bracket = {
            "bracket": {
                "playoffBracketSeries": [
                    {
                        "seriesId": "test",
                        "roundNumber": 1,
                        "seriesConference": "East",
                        "highSeedTricode": "CLE",
                        "highSeedSeriesWins": 1,
                        "lowSeedSeriesWins": 0,
                        "nextGameId": "0042400102",
                        "nextGameStatus": 1,
                    }
                ]
            }
        }
        schedule = _make_schedule()
        state = self._call(schedule, bracket=minimal_bracket)
        result = state.get("East", 1, "CLE")
        assert result is not None
        assert result.next_game_home_win_prob is None

    def test_all_round1_series_present_from_fixture(self):
        schedule = _make_schedule()
        state = self._call(schedule)
        # 8 Round 1 series (4 East + 4 West)
        round1_keys = [(conf, 1, tc) for conf, rnd, tc in state.series_results if rnd == 1]
        assert len(round1_keys) == 8

    def test_conference_finals_present(self):
        schedule = _make_schedule()
        state = self._call(schedule)
        # East Conf Finals: IND (seed 4) beat NYK (seed 3) — NYK is highSeed
        result = state.get("East", 3, "NYK")
        assert result is not None
        assert result.higher_seed_wins == 2
        assert result.lower_seed_wins == 4
        assert result.is_complete is True
