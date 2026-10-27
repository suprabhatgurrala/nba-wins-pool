import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from nba_wins_pool.models.projection import MarketQuote, ProjectionFetch, ProjectionMarket, QuoteCreate
from nba_wins_pool.repositories.projection_repository import LatestQuote, ProjectionRepository

NOW = datetime(2026, 10, 26, 22, 52)
EARLIER = datetime(2026, 10, 20, 12, 0)
OKC = uuid.uuid4()


def _quote(market, *, line=None, prob=None, odds=None, opp_odds=None, fetched_at=NOW) -> LatestQuote:
    return LatestQuote("OKC", OKC, market, line, prob, odds, opp_odds, fetched_at)


@pytest.fixture
def repo():
    session = MagicMock()
    session.flush = AsyncMock()
    repo = ProjectionRepository(session)
    repo.get_latest_quotes = AsyncMock()
    return repo


@pytest.mark.asyncio
async def test_add_fetch_copies_the_fetch_onto_each_quote(repo):
    quotes = [
        QuoteCreate(team_id=OKC, market=ProjectionMarket.WIN_TOTAL, line=58.5, prob=0.48, odds=-105, opp_odds=-120),
        QuoteCreate(team_id=OKC, market=ProjectionMarket.WIN_TITLE, prob=0.185, odds=380),
    ]

    fetch = await repo.add_fetch("fanduel", "2026-27", NOW, quotes)

    assert isinstance(fetch, ProjectionFetch) and fetch.quote_count == 2
    repo.session.flush.assert_awaited_once()
    stored = list(repo.session.add_all.call_args.args[0])
    assert all(isinstance(q, MarketQuote) for q in stored)
    assert {(q.fetch_id, q.source, q.season, q.fetched_at) for q in stored} == {(fetch.id, "fanduel", "2026-27", NOW)}
    assert (stored[0].line, stored[0].odds, stored[0].opp_odds) == (58.5, -105, -120)


@pytest.mark.asyncio
async def test_add_fetch_writes_nothing_without_quotes(repo):
    assert await repo.add_fetch("fanduel", "2026-27", NOW, []) is None
    repo.session.add.assert_not_called()


@pytest.mark.asyncio
async def test_futures_come_from_each_teams_latest_fetch_only(repo):
    """A market pulled since the team's latest fetch is absent, not its stale last quote."""
    repo.get_latest_quotes.return_value = [
        _quote(ProjectionMarket.MAKE_PLAYOFFS, prob=0.99, odds=-20000, opp_odds=5000),
        _quote(ProjectionMarket.WIN_TITLE, prob=0.185),
        _quote(ProjectionMarket.REACH_SEMIS, prob=0.9, fetched_at=EARLIER),
    ]

    futures = await repo.get_latest_fanduel_futures("2026-27")

    assert futures["OKC"] == {
        "make_playoffs_prob": 0.99,
        "reach_conf_semis_prob": None,
        "reach_conf_finals_prob": None,
        "win_conference_prob": None,
        "win_finals_prob": 0.185,
        "make_playoffs_odds": -20000,
        "miss_playoffs_odds": 5000,
        "fetched_at": NOW,
    }


@pytest.mark.asyncio
async def test_win_ladder_groups_thresholds(repo):
    repo.get_latest_quotes.return_value = [
        _quote(ProjectionMarket.WINS_LADDER, line=50, prob=0.97, fetched_at=EARLIER),
        _quote(ProjectionMarket.WINS_LADDER, line=60, prob=0.55, fetched_at=EARLIER),
    ]

    ladders = await repo.get_latest_win_threshold_probs("2026-27")

    assert ladders == {"OKC": {"probs": {50: 0.97, 60: 0.55}, "fetched_at": EARLIER}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source, market, over_prob",
    [("fanduel", ProjectionMarket.WIN_TOTAL, 0.48), ("espn_bpi", ProjectionMarket.ESPN_WINS, None)],
)
async def test_win_totals_read_each_sources_wins_market(repo, source, market, over_prob):
    repo.get_latest_quotes.return_value = [_quote(market, line=58.5, prob=over_prob)]

    totals = await repo.get_latest_win_totals("2026-27", source)

    assert repo.get_latest_quotes.call_args.args == ("2026-27", source, [market])
    assert totals == {"OKC": {"wins": 58.5, "over_prob": over_prob, "fetched_at": NOW, "projection_date": NOW.date()}}
