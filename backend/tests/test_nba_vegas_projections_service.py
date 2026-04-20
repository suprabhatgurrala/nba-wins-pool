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
