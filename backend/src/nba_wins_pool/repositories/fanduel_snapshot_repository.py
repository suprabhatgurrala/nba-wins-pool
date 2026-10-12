"""Repository for the raw FanDuel response archive."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nba_wins_pool.models.fanduel_snapshot import FanDuelSnapshot


class FanDuelSnapshotRepository:
    """Stores one raw FanDuel futures response per projection date: the fullest one seen."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, snapshot: FanDuelSnapshot) -> None:
        """Insert the snapshot, or replace that projection date's existing one unless it has fewer populated markets.

        Ties replace, so a day keeps the latest of its fullest fetches. Does not commit; the
        caller commits alongside the parsed projections.
        """
        statement = select(FanDuelSnapshot).where(FanDuelSnapshot.projection_date == snapshot.projection_date)
        existing = (await self.session.execute(statement)).scalars().first()
        if existing:
            if snapshot.populated_markets < existing.populated_markets:
                return
            existing.season = snapshot.season
            existing.fetched_at = snapshot.fetched_at
            existing.populated_markets = snapshot.populated_markets
            existing.futures_response = snapshot.futures_response
            self.session.add(existing)
        else:
            self.session.add(snapshot)
