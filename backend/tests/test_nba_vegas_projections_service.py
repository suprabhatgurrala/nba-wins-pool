"""Tests for NBAVegasProjectionsService."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.projection import ProjectionMarket
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.projection_repository import ProjectionRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_vegas_projections_service import NBAVegasProjectionsService
from nba_wins_pool.utils.odds import shin_devig


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
def mock_projection_repo():
    """Mock ProjectionRepository."""
    repo = AsyncMock(spec=ProjectionRepository)
    return repo


@pytest.fixture
def vegas_service(mock_db_session, mock_team_repository, mock_projection_repo):
    """Create NBAVegasProjectionsService with mocked dependencies."""
    return NBAVegasProjectionsService(mock_db_session, mock_team_repository, mock_projection_repo)


_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_EMPTY_RESPONSE = {"attachments": {"markets": {}}}


_FUTURES_FIELDS = {
    ProjectionMarket.REACH_SEMIS: "reach_conf_semis",
    ProjectionMarket.REACH_CONF_FINALS: "reach_conf_finals",
    ProjectionMarket.WIN_CONF: "win_conference",
    ProjectionMarket.WIN_TITLE: "win_finals",
}


def _parse(service, standard, futures, team_map, **kwargs) -> list[SimpleNamespace]:
    """Parse, then fold each team's quotes into one flat row per team for compact assertions."""
    parsed = service.parse_fanduel_responses(standard, futures, team_map, **kwargs)
    name_by_id = {team_map[tc].id: name for name, tc in NBAVegasProjectionsService.TEAM_NAME_TO_TRICODE.items()}
    fields = ["reg_season_wins", "over_wins_prob", "over_wins_odds", "under_wins_odds"]
    fields += ["make_playoffs_prob", "make_playoffs_odds", "miss_playoffs_odds"]
    fields += [f"{prefix}_{kind}" for prefix in _FUTURES_FIELDS.values() for kind in ("prob", "odds")]
    rows: dict = {}
    for q in parsed.quotes:
        row = rows.setdefault(
            q.team_id,
            SimpleNamespace(
                team_name=name_by_id[q.team_id],
                season=parsed.season,
                source="fanduel",
                win_threshold_probs={},
                **dict.fromkeys(fields),
            ),
        )
        if q.market == ProjectionMarket.WIN_TOTAL:
            row.reg_season_wins, row.over_wins_prob = q.line, q.prob
            row.over_wins_odds, row.under_wins_odds = q.odds, q.opp_odds
        elif q.market == ProjectionMarket.WINS_LADDER:
            row.win_threshold_probs[int(q.line)] = q.prob
        elif q.market == ProjectionMarket.MAKE_PLAYOFFS:
            row.make_playoffs_prob, row.make_playoffs_odds, row.miss_playoffs_odds = q.prob, q.odds, q.opp_odds
        else:
            prefix = _FUTURES_FIELDS[q.market]
            setattr(row, f"{prefix}_prob", q.prob)
            setattr(row, f"{prefix}_odds", q.odds)
    return list(rows.values())


@pytest.fixture
def sample_fanduel_response():
    with open(_FIXTURE_DIR / "sample-fanduel-2025-26-response.json") as f:
        return json.load(f)


@pytest.fixture
def sample_fanduel_futures_response():
    with open(_FIXTURE_DIR / "sample-fanduel-futures-2025-26-response.json") as f:
        return json.load(f)


@pytest.fixture
def sample_fanduel_futures_2026_27_response():
    """Off-season (26-27) futures response: NBA_FINALS_WINNER naming, 2-digit season, full-league outrights."""
    with open(_FIXTURE_DIR / "sample-fanduel-futures-2026-27-response.json") as f:
        return json.load(f)


@pytest.fixture
def sample_fanduel_2026_27_response():
    """Off-season (26-27) standard response.

    FanDuel reshaped both per-team markets for 26-27: reg-season wins moved to
    NBA_REGULAR_SEASON_WINS_O/U with the team folded into the runner name and the season
    leading the market name, and per-team Yes/No make-playoffs became a pair of
    per-conference multi-way outrights (NBA_TO_MAKE/MISS_PLAYOFFS).
    """
    with open(_FIXTURE_DIR / "sample-fanduel-2026-27-response.json") as f:
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

        records = _parse(vegas_service, sample_fanduel_response, _EMPTY_RESPONSE, team_map)

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

        records = _parse(vegas_service, _EMPTY_RESPONSE, sample_fanduel_futures_response, team_map)

        # Futures endpoint only covers the 16 playoff teams
        assert len(records) == 16
        assert all(r.source == "fanduel" for r in records)
        assert all(r.season == "2025-26" for r in records)

        bos = next(r for r in records if r.team_name == "Boston Celtics")
        assert bos.win_finals_prob == pytest.approx(0.1324, abs=1e-3)
        assert bos.win_conference_prob == pytest.approx(0.3953, abs=1e-3)
        assert bos.reach_conf_semis_prob == pytest.approx(0.9203, abs=1e-3)
        assert bos.reach_conf_finals_prob == pytest.approx(0.6275, abs=1e-3)
        assert bos.win_finals_odds == 600

        # Probabilities are bounded correctly
        for r in records:
            assert 0 < r.win_finals_prob <= 1
            assert 0 < r.win_conference_prob <= 1
            assert 0 < r.reach_conf_semis_prob <= 1
            assert 0 < r.reach_conf_finals_prob <= 1

    def test_offseason_futures_response_populates_playoff_fields(
        self, vegas_service, sample_fanduel_futures_2026_27_response, team_map
    ):
        """Off-season futures response (NBA_FINALS_WINNER naming, 2-digit season) parses the same
        four playoff probability fields as the in-season NBA_CHAMPIONSHIP shape, across all 30
        teams since the off-season endpoint carries full-league outrights rather than just the
        16 playoff teams."""

        records = _parse(vegas_service, _EMPTY_RESPONSE, sample_fanduel_futures_2026_27_response, team_map)

        assert len(records) == 30
        assert all(r.source == "fanduel" for r in records)
        assert all(r.season == "2026-27" for r in records)

        okc = next(r for r in records if r.team_name == "Oklahoma City Thunder")
        assert okc.win_finals_prob == pytest.approx(0.2712, abs=1e-3)
        assert okc.win_conference_prob == pytest.approx(0.4041, abs=1e-3)
        assert okc.reach_conf_semis_prob == pytest.approx(0.8542, abs=1e-3)
        assert okc.reach_conf_finals_prob == pytest.approx(0.6563, abs=1e-3)
        assert okc.win_finals_odds == 230

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

        records = _parse(vegas_service, sample_fanduel_response, sample_fanduel_futures_response, team_map)

        # One record per team — no duplicates
        assert len(records) == len({r.team_name for r in records})
        # All 30 teams present (standard response covers full league)
        assert len(records) == 30

        bos = next(r for r in records if r.team_name == "Boston Celtics")
        # Regular-season fields come from the standard response
        assert bos.reg_season_wins is not None
        assert bos.make_playoffs_prob == pytest.approx(expected_probs["Boston Celtics"]["make_playoffs_prob"], abs=1e-6)
        # Playoff fields come from the futures response (overwrite standard)
        assert bos.reach_conf_semis_prob == pytest.approx(0.9203, abs=1e-3)
        assert bos.win_finals_odds == 600

    def test_fallback_season_used_when_no_championship_market(self, vegas_service, team_map):
        """fallback_season is used when neither response has a parseable NBA_CHAMPIONSHIP market."""
        response = {
            "attachments": {
                "markets": {
                    "m1": {
                        "marketType": "NBA_TO_MAKE_PLAYOFFS",
                        "marketName": "Boston Celtics To Make Playoffs",
                        "runners": [
                            {
                                "runnerName": "Yes",
                                "runnerStatus": "ACTIVE",
                                "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": -200}},
                            },
                            {
                                "runnerName": "No",
                                "runnerStatus": "ACTIVE",
                                "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": 150}},
                            },
                        ],
                    }
                }
            }
        }

        records = _parse(vegas_service, response, _EMPTY_RESPONSE, team_map, fallback_season="2026-27")

        assert len(records) == 1
        assert records[0].season == "2026-27"

    def test_parsed_championship_season_takes_precedence_over_fallback(
        self, vegas_service, sample_fanduel_response, team_map
    ):
        """When a championship market with a season is present, it wins over fallback_season."""

        records = _parse(vegas_service, sample_fanduel_response, _EMPTY_RESPONSE, team_map, fallback_season="1999-00")

        assert all(r.season != "1999-00" for r in records)

    def test_offseason_reg_season_wins_market_is_parsed(self, vegas_service, sample_fanduel_2026_27_response, team_map):
        """NBA_REGULAR_SEASON_WINS_O/U yields a win total for all 30 teams.

        Regression for the 26-27 rename: the market was silently skipped, leaving
        reg_season_wins NULL, which in turn 500'd the leaderboard.
        """

        records = _parse(vegas_service, sample_fanduel_2026_27_response, _EMPTY_RESPONSE, team_map)

        assert len(records) == 30
        assert all(r.reg_season_wins is not None for r in records)
        assert all(r.over_wins_odds is not None and r.under_wins_odds is not None for r in records)
        for r in records:
            assert 10 < r.reg_season_wins < 74, f"{r.team_name}: {r.reg_season_wins}"
            assert 0 < r.over_wins_prob < 1

    def test_quotes_carry_raw_odds_and_skip_unlisted_markets(self, vegas_service, team_map):
        """A win total keeps both sides' odds, each ladder rung is its own quote, and unlisted markets get none."""
        response = json.loads((_FIXTURE_DIR / "fanduel-win-ladder-2026-27.json").read_text())
        parsed = vegas_service.parse_fanduel_responses(response, _EMPTY_RESPONSE, team_map, fallback_season="2026-27")

        okc = [q for q in parsed.quotes if q.team_id == team_map["OKC"].id]
        assert {q.market for q in okc} == {ProjectionMarket.WINS_LADDER, ProjectionMarket.WIN_TOTAL}
        rung = next(q for q in okc if q.line == 50)
        assert rung.odds is not None and rung.prob == pytest.approx(3000 / 3100)

        parsed = vegas_service.parse_fanduel_responses(
            json.loads((_FIXTURE_DIR / "sample-fanduel-2026-27-response.json").read_text()), _EMPTY_RESPONSE, team_map
        )
        total = next(
            q for q in parsed.quotes if q.team_id == team_map["OKC"].id and q.market == ProjectionMarket.WIN_TOTAL
        )
        assert total.line is not None and total.odds is not None and total.opp_odds is not None
        assert 0 < total.prob < 1

    def test_win_threshold_ladder_is_parsed(self, vegas_service, team_map):
        """FanDuel's "X+ Regular Season Wins" markets become a per-team ladder of raw implied probabilities."""
        response = json.loads((_FIXTURE_DIR / "fanduel-win-ladder-2026-27.json").read_text())
        records = _parse(vegas_service, response, _EMPTY_RESPONSE, team_map, fallback_season="2026-27")

        ladders = {r.team_name: r.win_threshold_probs for r in records}
        assert len(ladders) == 30 and all(ladders.values())
        assert ladders["Oklahoma City Thunder"][50] == pytest.approx(3000 / 3100)
        for ladder in ladders.values():
            probs = [ladder[k] for k in sorted(ladder)]
            assert probs == sorted(probs, reverse=True)

    def test_offseason_make_miss_playoffs_markets_are_paired(
        self, vegas_service, sample_fanduel_2026_27_response, team_map
    ):
        """Each team's "to Make" and "to Miss" outrights de-vig into one make_playoffs_prob.

        The probabilities are checked against the 16 available playoff slots, which a
        correctly de-vigged league should sum to.
        """

        records = _parse(vegas_service, sample_fanduel_2026_27_response, _EMPTY_RESPONSE, team_map)

        assert all(r.make_playoffs_prob is not None for r in records)
        assert all(0 < r.make_playoffs_prob < 1 for r in records)
        assert all(r.make_playoffs_odds is not None and r.miss_playoffs_odds is not None for r in records)
        assert sum(r.make_playoffs_prob for r in records) == pytest.approx(16, abs=2)

    def test_offseason_season_prefix_stripped_from_team_name(
        self, vegas_service, sample_fanduel_2026_27_response, team_map
    ):
        """The leading "26-27 NBA " in off-season market names never leaks into team names."""

        records = _parse(vegas_service, sample_fanduel_2026_27_response, _EMPTY_RESPONSE, team_map)

        assert {r.team_name for r in records} == set(NBAVegasProjectionsService.TEAM_NAME_TO_TRICODE)
        assert all(r.season == "2026-27" for r in records)

    def test_inseason_and_offseason_wins_runner_shapes_both_parse(self, vegas_service, team_map):
        """The bare "Over 42.5" and team-prefixed "... Over 50.5 Wins" runners both parse."""

        def wins_market(market_type, market_name, over_name, under_name):
            return {
                "marketType": market_type,
                "marketName": market_name,
                "runners": [
                    {
                        "runnerName": over_name,
                        "runnerStatus": "ACTIVE",
                        "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": -110}},
                    },
                    {
                        "runnerName": under_name,
                        "runnerStatus": "ACTIVE",
                        "winRunnerOdds": {"americanDisplayOdds": {"americanOddsInt": -110}},
                    },
                ],
            }

        response = {
            "attachments": {
                "markets": {
                    "in_season": wins_market(
                        "NBA_REGULAR_SEASON_WINS_SGP",
                        "Boston Celtics Regular Season Wins 2025-26",
                        "Over 42.5",
                        "Under 42.5",
                    ),
                    "off_season": wins_market(
                        "NBA_REGULAR_SEASON_WINS_O/U",
                        "26-27 NBA Denver Nuggets Regular Season Wins",
                        "Denver Nuggets Over 50.5 Wins",
                        "Denver Nuggets Under 50.5 Wins",
                    ),
                }
            }
        }

        records = _parse(vegas_service, response, _EMPTY_RESPONSE, team_map, fallback_season="2026-27")

        by_team = {r.team_name: r for r in records}
        assert by_team["Boston Celtics"].reg_season_wins == 42.5
        assert by_team["Denver Nuggets"].reg_season_wins == 50.5

    def test_series_market_uses_suspended_runner_odds(self, vegas_service, team_map):
        """Suspended runner odds (e.g. heavy series favorite) are read directly and vig-normalized."""
        with open(_FIXTURE_DIR / "sample-fanduel-futures-suspended-2025-26-response.json") as f:
            suspended_response = json.load(f)

        # OKC is heavily favored (SUSPENDED at -100000); PHX is ACTIVE at +10000
        okc_odds, phx_odds = -100000, 10000
        okc_fair, phx_fair = shin_devig([100000 / (100000 + 100), 100 / (10000 + 100)])

        playoff_round_lookup = {frozenset(["OKC", "PHX"]): 1}
        records = _parse(
            vegas_service, _EMPTY_RESPONSE, suspended_response, team_map, playoff_round_lookup=playoff_round_lookup
        )

        okc = next(r for r in records if r.team_name == "Oklahoma City Thunder")
        phx = next(r for r in records if r.team_name == "Phoenix Suns")

        assert okc.reach_conf_semis_prob == pytest.approx(okc_fair, abs=1e-6)
        assert phx.reach_conf_semis_prob == pytest.approx(phx_fair, abs=1e-6)
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

        records = _parse(vegas_service, _EMPTY_RESPONSE, response, team_map, playoff_round_lookup=playoff_round_lookup)

        okc_fair, phx_fair = shin_devig([100000 / (100000 + 100), 100 / (10000 + 100)])

        okc = next(r for r in records if r.team_name == "Oklahoma City Thunder")
        assert okc.reach_conf_semis_prob == pytest.approx(okc_fair, abs=1e-6)
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

        with open(_FIXTURE_DIR / "sample-fanduel-futures-suspended-2025-26-response.json") as f:
            futures = json.load(f)
        with open(_FIXTURE_DIR / "expected-futures-probs.csv") as f:
            expected = {
                row["team_name"]: {k.strip(): float(v) for k, v in row.items() if k.strip() != "team_name"}
                for row in csv.DictReader(f)
            }

        records = _parse(
            vegas_service,
            _EMPTY_RESPONSE,
            futures,
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
        records = _parse(vegas_service, _EMPTY_RESPONSE, response, team_map, playoff_round_lookup=playoff_round_lookup)

        def raw(odds):
            return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)

        okc_fair, phx_fair = shin_devig([raw(-400), raw(280)])
        lal_fair, mem_fair = shin_devig([raw(-200), raw(155)])

        okc = next(r for r in records if r.team_name == "Oklahoma City Thunder")
        phx = next(r for r in records if r.team_name == "Phoenix Suns")
        lal = next(r for r in records if r.team_name == "Los Angeles Lakers")
        mem = next(r for r in records if r.team_name == "Memphis Grizzlies")

        # Each pair normalizes independently
        assert okc.reach_conf_semis_prob == pytest.approx(okc_fair, abs=1e-6)
        assert phx.reach_conf_semis_prob == pytest.approx(phx_fair, abs=1e-6)
        assert lal.reach_conf_semis_prob == pytest.approx(lal_fair, abs=1e-6)
        assert mem.reach_conf_semis_prob == pytest.approx(mem_fair, abs=1e-6)

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
        records = _parse(vegas_service, _EMPTY_RESPONSE, response, team_map, bracket_groups=bracket_groups)

        def raw(odds):
            return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)

        side0 = ["Oklahoma City Thunder", "Memphis Grizzlies", "Los Angeles Lakers", "New Orleans Pelicans"]
        side1 = ["Golden State Warriors", "Houston Rockets", "Dallas Mavericks", "Sacramento Kings"]
        odds_map = {r["runnerName"]: r["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"] for r in runners}

        for side in (side0, side1):
            fair = shin_devig([raw(odds_map[n]) for n in side])
            for name, prob in zip(side, fair):
                rec = next(r for r in records if r.team_name == name)
                assert rec.reach_conf_finals_prob == pytest.approx(prob, abs=1e-6)

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
        records = _parse(vegas_service, _EMPTY_RESPONSE, response, team_map)

        okc = next(r for r in records if r.team_name == "Oklahoma City Thunder")
        gsw = next(r for r in records if r.team_name == "Golden State Warriors")
        assert okc.reach_conf_finals_prob <= 1.0
        assert gsw.reach_conf_finals_prob <= 1.0
