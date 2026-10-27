"""Projection fetches and their market quotes."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from fastapi import Depends
from sqlalchemy import String, and_, column, delete, func, select, true, values
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.projection import MarketQuote, ProjectionFetch, ProjectionMarket, QuoteCreate
from nba_wins_pool.models.team import Team

FANDUEL = "fanduel"
ESPN_BPI = "espn_bpi"
DRAFTKINGS = "draftkings"

FUTURES_PROB_KEYS: dict[ProjectionMarket, str] = {
    ProjectionMarket.MAKE_PLAYOFFS: "make_playoffs_prob",
    ProjectionMarket.REACH_SEMIS: "reach_conf_semis_prob",
    ProjectionMarket.REACH_CONF_FINALS: "reach_conf_finals_prob",
    ProjectionMarket.WIN_CONF: "win_conference_prob",
    ProjectionMarket.WIN_TITLE: "win_finals_prob",
}


@dataclass(frozen=True)
class LatestQuote:
    """A team's most recent quote in one market, with when it was fetched."""

    tricode: str
    team_id: uuid.UUID
    market: ProjectionMarket
    line: float | None
    prob: float | None
    odds: int | None
    opp_odds: int | None
    fetched_at: datetime


def quotes_by_team(quotes: list[LatestQuote]) -> dict[str, dict[ProjectionMarket, LatestQuote]]:
    """Index quotes by tricode, then market. Not for the ladder, which has one quote per threshold."""
    result: dict[str, dict[ProjectionMarket, LatestQuote]] = {}
    for q in quotes:
        result.setdefault(q.tricode, {})[q.market] = q
    return result


class ProjectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_fetch(
        self, source: str, season: str, fetched_at: datetime, quotes: list[QuoteCreate]
    ) -> Optional[ProjectionFetch]:
        """Add a fetch and its quotes; nothing when there are no quotes. Flushes the fetch first, but doesn't commit."""
        if not quotes:
            return None
        fetch = ProjectionFetch(source=source, season=season, fetched_at=fetched_at, quote_count=len(quotes))
        self.session.add(fetch)
        await self.session.flush()
        self.session.add_all(
            MarketQuote(
                fetch_id=fetch.id,
                source=source,
                season=season,
                fetched_at=fetched_at,
                **q.model_dump(),
            )
            for q in quotes
        )
        return fetch

    async def has_fetch(self, source: str, season: str, fetched_at: datetime) -> bool:
        statement = select(ProjectionFetch.id).where(
            ProjectionFetch.source == source,
            ProjectionFetch.season == season,
            ProjectionFetch.fetched_at == fetched_at,
        )
        return (await self.session.execute(statement.limit(1))).first() is not None

    async def delete_fetches(self, source: str, season: str, fetched_at: datetime) -> None:
        """Delete the fetches at this time, quotes included. Does not commit."""
        await self.session.execute(
            delete(ProjectionFetch).where(
                ProjectionFetch.source == source,
                ProjectionFetch.season == season,
                ProjectionFetch.fetched_at == fetched_at,
            )
        )

    async def get_latest_fetched_at(
        self, season: str, source: Optional[str] = None, as_of: Optional[datetime] = None
    ) -> Optional[datetime]:
        """The newest fetch of the season (from *source*, at or before *as_of*, when given)."""
        statement = select(func.max(ProjectionFetch.fetched_at)).where(ProjectionFetch.season == season)
        if source:
            statement = statement.where(ProjectionFetch.source == source)
        if as_of:
            statement = statement.where(ProjectionFetch.fetched_at <= as_of)
        return (await self.session.execute(statement)).scalar()

    async def get_latest_quotes(
        self,
        season: str,
        source: str,
        markets: list[ProjectionMarket],
        as_of: Optional[datetime] = None,
    ) -> list[LatestQuote]:
        """Each team's most recent quote in each market, however old, at or before *as_of* when given.

        A market FanDuel has pulled keeps its last quote; callers judge its age by ``fetched_at``. The ladder
        returns every threshold from the team's latest fetch that had one.
        """
        if not markets:
            return []
        wanted = values(column("market", String), name="wanted").data([(m.value,) for m in markets])

        def same_key(quote) -> list:
            return [
                quote.source == source,
                quote.season == season,
                quote.team_id == Team.id,
                quote.market == wanted.c.market,
            ]

        prior = aliased(MarketQuote)
        newest = select(func.max(prior.fetched_at).label("fetched_at")).where(*same_key(prior))
        if as_of:
            newest = newest.where(prior.fetched_at <= as_of)
        latest = newest.lateral("latest")
        statement = (
            select(Team.abbreviation, MarketQuote)
            .select_from(Team)
            .join(wanted, true())
            .join(latest, true())
            .join(MarketQuote, and_(*same_key(MarketQuote), MarketQuote.fetched_at == latest.c.fetched_at))
        )
        rows = (await self.session.execute(statement)).all()
        return [
            LatestQuote(
                tricode=abbreviation,
                team_id=q.team_id,
                market=ProjectionMarket(q.market),
                line=q.line,
                prob=q.prob,
                odds=q.odds,
                opp_odds=q.opp_odds,
                fetched_at=q.fetched_at,
            )
            for abbreviation, q in rows
        ]

    async def get_latest_win_totals(self, season: str, source: str) -> dict[str, dict[str, Any]]:
        """Each team's latest regular-season wins projection from one source.

        Returns:
            Tricode -> ``wins`` (FanDuel's line or ESPN's projected wins), ``over_prob`` (FanDuel, de-vigged;
            None for ESPN), ``fetched_at`` and ``projection_date``. Callers check the age: a pulled line keeps
            its last quote.
        """
        market = ProjectionMarket.ESPN_WINS if source == ESPN_BPI else ProjectionMarket.WIN_TOTAL
        quotes = await self.get_latest_quotes(season, source, [market])
        return {
            q.tricode: {
                "wins": float(q.line),
                "over_prob": q.prob,
                "fetched_at": q.fetched_at,
                "projection_date": q.fetched_at.date(),
            }
            for q in quotes
            if q.line is not None
        }

    async def get_latest_win_threshold_probs(self, season: str) -> dict[str, dict[str, Any]]:
        """Each team's latest FanDuel X+ wins ladder, which FanDuel lists only early on, so it may be weeks old.

        Returns:
            Tricode -> ``probs`` (threshold -> raw ``P(wins >= threshold)``) and ``fetched_at``.
        """
        quotes = await self.get_latest_quotes(season, FANDUEL, [ProjectionMarket.WINS_LADDER])
        result: dict[str, dict[str, Any]] = {}
        for q in quotes:
            entry = result.setdefault(q.tricode, {"probs": {}, "fetched_at": q.fetched_at})
            entry["probs"][int(q.line)] = q.prob
        return result

    async def get_latest_playoff_bpi(self, season: str) -> dict[str, float]:
        """Each team's latest ESPN playoff BPI (PBPI), by tricode."""
        quotes = await self.get_latest_quotes(season, ESPN_BPI, [ProjectionMarket.ESPN_PLAYOFF_BPI])
        return {q.tricode: float(q.line) for q in quotes if q.line is not None}

    async def get_latest_fanduel_futures(self, season: str) -> dict[str, dict[str, Any]]:
        """Each team's FanDuel futures from its latest fetch that had any.

        Only that fetch's markets are returned, so a market FanDuel has since pulled (an eliminated team's
        title odds, say) doesn't linger next to current ones.

        Returns:
            Tricode -> ``make_playoffs_prob``, ``make_playoffs_odds``, ``miss_playoffs_odds``,
            ``reach_conf_semis_prob``, ``reach_conf_finals_prob``, ``win_conference_prob``, ``win_finals_prob``
            (None when absent from that fetch) and ``fetched_at``.
        """
        quotes = await self.get_latest_quotes(season, FANDUEL, list(FUTURES_PROB_KEYS))
        result: dict[str, dict[str, Any]] = {}
        for tricode, by_market in quotes_by_team(quotes).items():
            fetched_at = max(q.fetched_at for q in by_market.values())
            current = {m: q for m, q in by_market.items() if q.fetched_at == fetched_at}
            make = current.get(ProjectionMarket.MAKE_PLAYOFFS)
            entry: dict[str, Any] = {key: None for key in FUTURES_PROB_KEYS.values()}
            entry.update({FUTURES_PROB_KEYS[m]: q.prob for m, q in current.items()})
            entry["make_playoffs_odds"] = make.odds if make else None
            entry["miss_playoffs_odds"] = make.opp_odds if make else None
            entry["fetched_at"] = fetched_at
            result[tricode] = entry
        return result


async def get_projection_repository(db: AsyncSession = Depends(get_db_session)) -> ProjectionRepository:
    return ProjectionRepository(db)
