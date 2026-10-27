"""Tests for how PoolHistoryService treats finished and in-progress seasons."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from nba_wins_pool.services.pool_history_service import PoolHistoryService

POOL_ID = uuid4()
CURRENT = "2025-26"
PAST = "2024-25"


def _roster(name, wins, rank):
    return {"name": name, "wins": wins, "losses": 82 - wins, "rank": rank}


def _team(roster_name, abbreviation, wins, preseason_projected_wins=None):
    return {
        "name": roster_name,
        "team": abbreviation,
        "abbreviation": abbreviation,
        "logo_url": "",
        "wins": wins,
        "losses": 82 - wins,
        "preseason_projected_wins": preseason_projected_wins,
    }


class FakeLeaderboardService:
    def __init__(self, leaderboards):
        self.leaderboards = leaderboards

    async def get_leaderboard(self, pool_id, season, pool_season):
        return self.leaderboards[season]


class FakeNbaDataService:
    def __init__(self, finished_seasons):
        self.finished_seasons = finished_seasons

    async def is_season_finished(self, season):
        return season in self.finished_seasons


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    async def get_all_by_pool(self, pool_id):
        return self.rows

    async def get_all(self, pool_id, season, status):
        return self.rows


def _service(leaderboards, finished_seasons, materialized_rows=()):
    pool_seasons = [SimpleNamespace(id=uuid4(), season=season) for season in leaderboards]
    return PoolHistoryService(
        pool_season_repository=FakeRepository(pool_seasons),
        leaderboard_service=FakeLeaderboardService(leaderboards),
        pool_team_season_result_repository=FakeRepository(list(materialized_rows)),
        nba_data_service=FakeNbaDataService(finished_seasons),
        auction_repository=FakeRepository([]),
    )


@pytest.fixture
def leaderboards():
    return {
        CURRENT: {
            "roster": [_roster("Alice", 30, 1), _roster("Bob", 20, 2), _roster("Cara", 10, 3)],
            "team": [
                _team("Alice", "BOS", 30, 50.0),
                _team("Bob", "NYK", 20, 40.0),
                _team("Cara", "UTA", 10, 30.0),
            ],
        },
        PAST: {
            "roster": [_roster("Bob", 50, 1), _roster("Alice", 40, 2)],
            "team": [_team("Bob", "OKC", 50), _team("Alice", "DEN", 40)],
        },
    }


@pytest.mark.asyncio
async def test_in_progress_season_counts_toward_seasons_played_but_not_results(leaderboards):
    history = await _service(leaderboards, {PAST}).get_pool_history(POOL_ID)

    alice = next(p for p in history.participants if p.name == "Alice")
    assert alice.seasons_played == 2
    assert alice.championships == 0
    assert alice.average_finish == 2
    assert alice.average_wins == 40


@pytest.mark.asyncio
async def test_seasons_report_whether_they_are_in_progress(leaderboards):
    history = await _service(leaderboards, {PAST}).get_pool_history(POOL_ID)

    assert {s.season: s.in_progress for s in history.seasons} == {CURRENT: True, PAST: False}


@pytest.mark.asyncio
async def test_first_season_participant_is_listed_last_without_averages(leaderboards):
    history = await _service(leaderboards, {PAST}).get_pool_history(POOL_ID)

    assert [p.name for p in history.participants] == ["Bob", "Alice", "Cara"]
    cara = history.participants[-1]
    assert (cara.seasons_played, cara.championships, cara.average_wins, cara.average_finish) == (1, 0, None, None)


@pytest.mark.asyncio
async def test_unmaterialized_season_projections_come_from_the_leaderboard(leaderboards):
    history = await _service(leaderboards, {PAST}).get_pool_history(POOL_ID)

    assert {p.name: p.average_projected_wins for p in history.participants} == {
        "Alice": 50.0,
        "Bob": 40.0,
        "Cara": 30.0,
    }


@pytest.mark.asyncio
async def test_finished_current_season_counts_its_champion(leaderboards):
    history = await _service(leaderboards, {PAST, CURRENT}).get_pool_history(POOL_ID)

    alice = next(p for p in history.participants if p.name == "Alice")
    assert alice.championships == 1
    assert alice.average_finish == 1.5


@pytest.mark.asyncio
async def test_participant_history_flags_in_progress_seasons(leaderboards):
    history = await _service(leaderboards, {PAST}).get_participant_history(POOL_ID, "Alice")

    assert [(s.season, s.rank, s.in_progress) for s in history.seasons] == [(CURRENT, 1, True), (PAST, 2, False)]


@pytest.mark.asyncio
async def test_blurb_ignores_the_in_progress_lead(leaderboards):
    service = _service(leaderboards, {PAST})

    assert (await service.get_participant_history(POOL_ID, "Alice")).blurb == "2 seasons · Best finish: 2nd"
    assert (await service.get_participant_history(POOL_ID, "Bob")).blurb == "2 seasons · Champion in 2024-25"
    assert (await service.get_participant_history(POOL_ID, "Cara")).blurb == "1 season"


@pytest.mark.asyncio
async def test_blurb_counts_multiple_finished_titles(leaderboards):
    leaderboards["2023-24"] = {"roster": [_roster("Bob", 55, 1)], "team": [_team("Bob", "BOS", 55)]}

    history = await _service(leaderboards, {PAST, "2023-24"}).get_participant_history(POOL_ID, "Bob")

    assert history.blurb == "3 seasons · 2-time champion"


@pytest.fixture
def tied_leaderboards():
    return {
        PAST: {
            "roster": [_roster("Alice", 48, 1), _roster("Bob", 48, 1), _roster("Cara", 41, 3), _roster("Dan", 41, 3)],
            "team": [
                _team("Alice", "BOS", 48),
                _team("Bob", "OKC", 48),
                _team("Cara", "NYK", 41),
                _team("Dan", "UTA", 41),
            ],
        },
    }


@pytest.mark.asyncio
async def test_tie_for_first_lists_co_champions_without_runner_up(tied_leaderboards):
    history = await _service(tied_leaderboards, {PAST}).get_pool_history(POOL_ID)

    season = history.seasons[0]
    assert [c.name for c in season.champions] == ["Alice", "Bob"]
    assert season.runner_up is None
    assert {p.name: p.championships for p in history.participants} == {"Alice": 1, "Bob": 1, "Cara": 0, "Dan": 0}


@pytest.mark.asyncio
async def test_untied_season_has_one_champion_and_runner_up(leaderboards):
    history = await _service(leaderboards, {PAST}).get_pool_history(POOL_ID)

    season = next(s for s in history.seasons if s.season == PAST)
    assert [c.name for c in season.champions] == ["Bob"]
    assert season.runner_up.name == "Alice"


@pytest.mark.asyncio
async def test_participant_seasons_flag_shared_ranks(tied_leaderboards):
    service = _service(tied_leaderboards, {PAST})

    alice = await service.get_participant_history(POOL_ID, "Alice")
    cara = await service.get_participant_history(POOL_ID, "Cara")

    assert (alice.seasons[0].rank, alice.seasons[0].rank_tied) == (1, True)
    assert (cara.seasons[0].rank, cara.seasons[0].rank_tied) == (3, True)


@pytest.mark.asyncio
async def test_blurb_marks_shared_titles_and_finishes(tied_leaderboards):
    service = _service(tied_leaderboards, {PAST})

    assert (await service.get_participant_history(POOL_ID, "Alice")).blurb == "1 season · Co-champion in 2024-25"
    assert (await service.get_participant_history(POOL_ID, "Cara")).blurb == "1 season · Best finish: T-3rd"
