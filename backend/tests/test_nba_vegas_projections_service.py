"""Tests for NBAVegasProjectionsService."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_vegas_projections_service import NBAVegasProjectionsService


@pytest.fixture
def mock_db_session():
    """Mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    return session


@pytest.fixture
def mock_team_repository():
    """Mock TeamRepository."""
    repo = AsyncMock(spec=TeamRepository)
    return repo


@pytest.fixture
def mock_nba_projections_repo():
    """Mock NBAProjectionsRepository."""
    repo = AsyncMock(spec=NBAProjectionsRepository)
    return repo


@pytest.fixture
def vegas_service(mock_db_session, mock_team_repository, mock_nba_projections_repo):
    """Create NBAVegasProjectionsService with mocked dependencies."""
    return NBAVegasProjectionsService(mock_db_session, mock_team_repository, mock_nba_projections_repo)


_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_EMPTY_RESPONSE = {"attachments": {"markets": {}}}


@pytest.fixture
def sample_fanduel_response():
    with open(_FIXTURE_DIR / "sample-fanduel-response.json") as f:
        return json.load(f)


@pytest.fixture
def sample_fanduel_futures_response():
    with open(_FIXTURE_DIR / "sample-fanduel-futures-response.json") as f:
        return json.load(f)


@pytest.fixture
def expected_probs():
    with open(_FIXTURE_DIR / "expected_fanduel_probs.json") as f:
        return json.load(f)


@pytest.fixture
def team_map():
    return {
        tricode: Team(id=uuid.uuid4(), abbreviation=tricode, name=team_name, league=LeagueSlug.NBA)
        for team_name, tricode in NBAVegasProjectionsService.TEAM_NAME_TO_TRICODE.items()
    }


class TestParseFanduelResponse:
    """Tests for parse_fanduel_responses."""

    def test_standard_response_probability_calculations(
        self, vegas_service, sample_fanduel_response, team_map, expected_probs
    ):
        """Standard-response fields (reg season wins, make playoffs, conf/title odds) match fixture."""
        fetched_at = datetime(2024, 10, 20, 12, 0, 0)

        records = vegas_service.parse_fanduel_responses(sample_fanduel_response, _EMPTY_RESPONSE, fetched_at, team_map)

        assert len(records) > 0
        for record in records:
            assert record.make_playoffs_prob == pytest.approx(
                expected_probs[record.team_name]["make_playoffs_prob"], abs=1e-6
            )
            assert record.over_wins_prob == pytest.approx(
                expected_probs[record.team_name]["over_reg_season_wins_prob"], abs=1e-6
            )
            assert record.win_conference_prob == pytest.approx(expected_probs[record.team_name]["conf_prob"], abs=1e-6)
            assert record.win_finals_prob == pytest.approx(expected_probs[record.team_name]["title_prob"], abs=1e-6)

    def test_futures_response_populates_playoff_fields(self, vegas_service, sample_fanduel_futures_response, team_map):
        """Futures response populates all four playoff probability fields for playoff teams."""
        fetched_at = datetime(2026, 4, 20, 12, 0, 0)

        records = vegas_service.parse_fanduel_responses(
            _EMPTY_RESPONSE, sample_fanduel_futures_response, fetched_at, team_map
        )

        # Futures endpoint only covers the 16 playoff teams
        assert len(records) == 16
        assert all(r.source == "fanduel" for r in records)
        assert all(r.season == "2025-26" for r in records)

        bos = next(r for r in records if r.team_name == "Boston Celtics")
        assert bos.win_finals_prob == pytest.approx(0.1304, abs=1e-3)
        assert bos.win_conference_prob == pytest.approx(0.3830, abs=1e-3)
        assert bos.reach_conf_semis_prob == pytest.approx(0.9112, abs=1e-3)
        assert bos.reach_conf_finals_prob == pytest.approx(0.6151, abs=1e-3)
        assert bos.win_finals_odds == 600

        # Probabilities are bounded correctly
        for r in records:
            assert 0 < r.win_finals_prob <= 1
            assert 0 < r.win_conference_prob <= 1
            assert 0 < r.reach_conf_semis_prob <= 1
            assert 0 < r.reach_conf_finals_prob <= 1

    def test_combined_responses_merge_without_duplicates(
        self, vegas_service, sample_fanduel_response, sample_fanduel_futures_response, team_map, expected_probs
    ):
        """Combined parse produces one record per team and futures odds overwrite standard playoff odds."""
        fetched_at = datetime(2026, 4, 20, 12, 0, 0)

        records = vegas_service.parse_fanduel_responses(
            sample_fanduel_response, sample_fanduel_futures_response, fetched_at, team_map
        )

        # One record per team — no duplicates
        assert len(records) == len({r.team_name for r in records})
        # All 30 teams present (standard response covers full league)
        assert len(records) == 30

        bos = next(r for r in records if r.team_name == "Boston Celtics")
        # Regular-season fields come from the standard response
        assert bos.reg_season_wins is not None
        assert bos.make_playoffs_prob == pytest.approx(expected_probs["Boston Celtics"]["make_playoffs_prob"], abs=1e-6)
        # Playoff fields come from the futures response (overwrite standard)
        assert bos.reach_conf_semis_prob == pytest.approx(0.9112, abs=1e-3)
        assert bos.win_finals_odds == 600

    def test_series_market_uses_suspended_runner_odds(self, vegas_service, team_map):
        """Suspended runner odds (e.g. heavy series favorite) are read directly and vig-normalized."""
        with open(_FIXTURE_DIR / "sample-fanduel-futures-suspended-response.json") as f:
            suspended_response = json.load(f)

        # OKC is heavily favored (SUSPENDED at -100000); PHX is ACTIVE at +10000
        okc_odds, phx_odds = -100000, 10000
        okc_raw = 100000 / (100000 + 100)
        phx_raw = 100 / (10000 + 100)
        total = okc_raw + phx_raw

        playoff_round_lookup = {frozenset(["OKC", "PHX"]): 1}
        fetched_at = datetime(2026, 4, 25, 12, 0, 0)
        records = vegas_service.parse_fanduel_responses(
            _EMPTY_RESPONSE, suspended_response, fetched_at, team_map, playoff_round_lookup=playoff_round_lookup
        )

        okc = next(r for r in records if r.team_name == "Oklahoma City Thunder")
        phx = next(r for r in records if r.team_name == "Phoenix Suns")

        assert okc.reach_conf_semis_prob == pytest.approx(okc_raw / total, abs=1e-6)
        assert phx.reach_conf_semis_prob == pytest.approx(phx_raw / total, abs=1e-6)
        assert okc.reach_conf_semis_prob + phx.reach_conf_semis_prob == pytest.approx(1.0, abs=1e-6)
        assert okc.reach_conf_semis_odds == okc_odds
        assert phx.reach_conf_semis_odds == phx_odds

    def test_series_betting_overrides_pool_futures_regardless_of_order(self, vegas_service, team_map):
        """Series betting prob always wins over pool-level futures even if it appears first in the response."""
        series_okc_odds, series_phx_odds = -100000, 10000
        pool_okc_odds = -400  # pool-level futures would assign a much lower probability

        playoff_round_lookup = {frozenset(["OKC", "PHX"]): 1}
        response = {
            "attachments": {
                "markets": {
                    # Series market comes FIRST in the dict — pool market would overwrite without two-pass logic
                    "1": {
                        "marketType": "SERIES_BETTING_OBP",
                        "marketName": "PHX vs OKC Series Betting",
                        "runners": [
                            {
                                "runnerName": "Oklahoma City Thunder",
                                "runnerStatus": "SUSPENDED",
                                "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": series_okc_odds}},
                            },
                            {
                                "runnerName": "Phoenix Suns",
                                "runnerStatus": "ACTIVE",
                                "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": series_phx_odds}},
                            },
                        ],
                    },
                    # Pool-level conf semis market comes AFTER — must NOT overwrite series betting
                    "2": {
                        "marketType": "TO_ADVANCE_TO_CONFERENCE_SEMIFINALS_-_WEST",
                        "marketName": "To Advance to Conference Semifinals - West",
                        "runners": [
                            {
                                "runnerName": "Oklahoma City Thunder",
                                "runnerStatus": "ACTIVE",
                                "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": pool_okc_odds}},
                            },
                        ],
                    },
                    "3": {
                        "marketType": "NBA_CHAMPIONSHIP",
                        "marketName": "2025-26 NBA Finals Winner",
                        "runners": [
                            {
                                "runnerName": "Oklahoma City Thunder",
                                "runnerStatus": "ACTIVE",
                                "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": -200}},
                            }
                        ],
                    },
                }
            }
        }

        fetched_at = datetime(2026, 4, 25, 12, 0, 0)
        records = vegas_service.parse_fanduel_responses(
            _EMPTY_RESPONSE, response, fetched_at, team_map, playoff_round_lookup=playoff_round_lookup
        )

        okc_raw = 100000 / (100000 + 100)
        phx_raw = 100 / (10000 + 100)
        total = okc_raw + phx_raw

        okc = next(r for r in records if r.team_name == "Oklahoma City Thunder")
        assert okc.reach_conf_semis_prob == pytest.approx(okc_raw / total, abs=1e-6)
        assert okc.reach_conf_semis_odds == series_okc_odds


class TestSuspendedFixtureExpectedProbs:
    """End-to-end test: parse the suspended-runner futures fixture and compare to manually
    computed expected probabilities for all 16 playoff teams."""

    # Round-1 series matchups (used to derive per-pair semis normalization)
    PLAYOFF_ROUND_LOOKUP = {
        frozenset(["OKC", "PHX"]): 1,
        frozenset(["LAL", "HOU"]): 1,
        frozenset(["SAS", "POR"]): 1,
        frozenset(["MIN", "DEN"]): 1,
        frozenset(["BOS", "PHI"]): 1,
        frozenset(["NYK", "ATL"]): 1,
        frozenset(["ORL", "DET"]): 1,
        frozenset(["CLE", "TOR"]): 1,
    }

    # Half-bracket sides for conf-finals normalization.
    # Group 0: OKC/PHX series winner vs LAL/HOU series winner in conf semis.
    # Group 1: SAS/POR series winner vs MIN/DEN series winner in conf semis.
    # Same logic for East (BOS/PHI+NYK/ATL on one side; CLE/TOR+ORL/DET on the other).
    BRACKET_GROUPS = {
        "OKC": 0,
        "PHX": 0,
        "LAL": 0,
        "HOU": 0,
        "SAS": 1,
        "POR": 1,
        "MIN": 1,
        "DEN": 1,
        "BOS": 0,
        "PHI": 0,
        "NYK": 0,
        "ATL": 0,
        "CLE": 1,
        "TOR": 1,
        "ORL": 1,
        "DET": 1,
    }

    def test_all_probabilities_match_expected_csv(self, vegas_service, team_map):
        """Parsed probs from the suspended-runner fixture match the manually computed CSV."""
        import csv

        with open(_FIXTURE_DIR / "sample-fanduel-futures-suspended-response.json") as f:
            futures = json.load(f)
        with open(_FIXTURE_DIR / "expected-futures-probs.csv") as f:
            expected = {
                row["team_name"]: {k.strip(): float(v) for k, v in row.items() if k.strip() != "team_name"}
                for row in csv.DictReader(f)
            }

        fetched_at = datetime(2026, 4, 25, 12, 0, 0)
        records = vegas_service.parse_fanduel_responses(
            _EMPTY_RESPONSE,
            futures,
            fetched_at,
            team_map,
            playoff_round_lookup=self.PLAYOFF_ROUND_LOOKUP,
            bracket_groups=self.BRACKET_GROUPS,
        )

        records_by_name = {r.team_name: r for r in records}
        for team_name, exp in expected.items():
            r = records_by_name[team_name]
            assert r.reach_conf_semis_prob == pytest.approx(
                exp["reach_conf_semis_prob"], abs=5e-4
            ), f"{team_name} reach_conf_semis_prob"
            assert r.reach_conf_finals_prob == pytest.approx(
                exp["reach_conf_finals_prob"], abs=5e-4
            ), f"{team_name} reach_conf_finals_prob"
            assert r.win_conference_prob == pytest.approx(
                exp["win_conference_prob"], abs=5e-4
            ), f"{team_name} win_conference_prob"
            assert r.win_finals_prob == pytest.approx(exp["win_finals_prob"], abs=5e-4), f"{team_name} win_finals_prob"


class TestBracketGroupNormalization:
    """Tests for bracket-aware vig normalization of pool-level futures markets."""

    def _make_conf_semis_response(self, runners: list[dict], season: str = "2025-26") -> dict:
        return {
            "attachments": {
                "markets": {
                    "1": {
                        "marketType": "TO_ADVANCE_TO_CONFERENCE_SEMIFINALS_-_WEST",
                        "marketName": "To Advance to Conference Semifinals - West",
                        "runners": runners,
                    },
                    "2": {
                        "marketType": "NBA_CHAMPIONSHIP",
                        "marketName": f"{season} NBA Finals Winner",
                        "runners": [
                            {
                                "runnerName": runners[0]["runnerName"],
                                "runnerStatus": "ACTIVE",
                                "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": -200}},
                            }
                        ],
                    },
                }
            }
        }

    def _make_conf_finals_response(self, runners: list[dict], season: str = "2025-26") -> dict:
        return {
            "attachments": {
                "markets": {
                    "1": {
                        "marketType": "TO_ADVANCE_TO_CONFERENCE_FINALS_-_WEST",
                        "marketName": "To Advance to Conference Finals - West",
                        "runners": runners,
                    },
                    "2": {
                        "marketType": "NBA_CHAMPIONSHIP",
                        "marketName": f"{season} NBA Finals Winner",
                        "runners": [
                            {
                                "runnerName": runners[0]["runnerName"],
                                "runnerStatus": "ACTIVE",
                                "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": -200}},
                            }
                        ],
                    },
                }
            }
        }

    def _active_runner(self, name: str, odds: int) -> dict:
        return {
            "runnerName": name,
            "runnerStatus": "ACTIVE",
            "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": odds}},
        }

    def test_conf_semis_pair_normalization(self, vegas_service, team_map):
        """reach_conf_semis_prob normalizes within each round-1 pair when playoff_round_lookup is set."""
        # OKC -400 vs PHX +280 (one pair), LAL -200 vs MEM +155 (another pair)
        response = self._make_conf_semis_response(
            [
                self._active_runner("Oklahoma City Thunder", -400),
                self._active_runner("Phoenix Suns", 280),
                self._active_runner("Los Angeles Lakers", -200),
                self._active_runner("Memphis Grizzlies", 155),
            ]
        )
        playoff_round_lookup = {
            frozenset(["OKC", "PHX"]): 1,
            frozenset(["LAL", "MEM"]): 1,
        }
        fetched_at = datetime(2026, 4, 25, 12, 0, 0)
        records = vegas_service.parse_fanduel_responses(
            _EMPTY_RESPONSE, response, fetched_at, team_map, playoff_round_lookup=playoff_round_lookup
        )

        def raw(odds):
            return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)

        okc_raw, phx_raw = raw(-400), raw(280)
        lal_raw, mem_raw = raw(-200), raw(155)

        okc = next(r for r in records if r.team_name == "Oklahoma City Thunder")
        phx = next(r for r in records if r.team_name == "Phoenix Suns")
        lal = next(r for r in records if r.team_name == "Los Angeles Lakers")
        mem = next(r for r in records if r.team_name == "Memphis Grizzlies")

        # Each pair normalizes independently
        assert okc.reach_conf_semis_prob == pytest.approx(okc_raw / (okc_raw + phx_raw), abs=1e-6)
        assert phx.reach_conf_semis_prob == pytest.approx(phx_raw / (okc_raw + phx_raw), abs=1e-6)
        assert lal.reach_conf_semis_prob == pytest.approx(lal_raw / (lal_raw + mem_raw), abs=1e-6)
        assert mem.reach_conf_semis_prob == pytest.approx(mem_raw / (lal_raw + mem_raw), abs=1e-6)

        # Each pair sums to 1.0, not 2.0
        assert okc.reach_conf_semis_prob + phx.reach_conf_semis_prob == pytest.approx(1.0, abs=1e-6)
        assert lal.reach_conf_semis_prob + mem.reach_conf_semis_prob == pytest.approx(1.0, abs=1e-6)

    def test_conf_finals_bracket_group_normalization(self, vegas_service, team_map):
        """reach_conf_finals_prob normalizes within each half-bracket when bracket_groups is set."""
        # Side 0: seeds 1, 4, 5, 8 (OKC, MEM, LAL, NOP)  — 1 advances
        # Side 1: seeds 2, 3, 6, 7 (GSW, HOU, DAL, SAC)  — 1 advances
        runners = [
            self._active_runner("Oklahoma City Thunder", -250),
            self._active_runner("Memphis Grizzlies", 400),
            self._active_runner("Los Angeles Lakers", 300),
            self._active_runner("New Orleans Pelicans", 600),
            self._active_runner("Golden State Warriors", -180),
            self._active_runner("Houston Rockets", 220),
            self._active_runner("Dallas Mavericks", 350),
            self._active_runner("Sacramento Kings", 700),
        ]
        bracket_groups = {
            "OKC": 0,
            "MEM": 0,
            "LAL": 0,
            "NOP": 0,
            "GSW": 1,
            "HOU": 1,
            "DAL": 1,
            "SAC": 1,
        }
        response = self._make_conf_finals_response(runners)
        fetched_at = datetime(2026, 4, 25, 12, 0, 0)
        records = vegas_service.parse_fanduel_responses(
            _EMPTY_RESPONSE, response, fetched_at, team_map, bracket_groups=bracket_groups
        )

        def raw(odds):
            return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)

        side0 = ["Oklahoma City Thunder", "Memphis Grizzlies", "Los Angeles Lakers", "New Orleans Pelicans"]
        side1 = ["Golden State Warriors", "Houston Rockets", "Dallas Mavericks", "Sacramento Kings"]
        odds_map = {r["runnerName"]: r["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"] for r in runners}

        side0_raw_total = sum(raw(odds_map[n]) for n in side0)
        side1_raw_total = sum(raw(odds_map[n]) for n in side1)

        for name in side0:
            rec = next(r for r in records if r.team_name == name)
            assert rec.reach_conf_finals_prob == pytest.approx(raw(odds_map[name]) / side0_raw_total, abs=1e-6)

        for name in side1:
            rec = next(r for r in records if r.team_name == name)
            assert rec.reach_conf_finals_prob == pytest.approx(raw(odds_map[name]) / side1_raw_total, abs=1e-6)

        # Each side sums to 1.0; combined = 2.0 (the correct number of conf finals participants)
        side0_probs = sum(next(r for r in records if r.team_name == n).reach_conf_finals_prob for n in side0)
        side1_probs = sum(next(r for r in records if r.team_name == n).reach_conf_finals_prob for n in side1)
        assert side0_probs == pytest.approx(1.0, abs=1e-6)
        assert side1_probs == pytest.approx(1.0, abs=1e-6)

    def test_fallback_pool_normalization_capped_at_one(self, vegas_service, team_map):
        """Pool * n_winners is capped at 1.0 — a two-team conf finals market can't give > 1.0."""
        # Two-team market with * 2 would give 1.25 raw; it must be capped at 1.0
        runners = [
            self._active_runner("Oklahoma City Thunder", -200),
            self._active_runner("Golden State Warriors", 150),
        ]
        response = self._make_conf_finals_response(runners)
        fetched_at = datetime(2026, 4, 25, 12, 0, 0)
        records = vegas_service.parse_fanduel_responses(_EMPTY_RESPONSE, response, fetched_at, team_map)

        okc = next(r for r in records if r.team_name == "Oklahoma City Thunder")
        gsw = next(r for r in records if r.team_name == "Golden State Warriors")
        assert okc.reach_conf_finals_prob <= 1.0
        assert gsw.reach_conf_finals_prob <= 1.0
