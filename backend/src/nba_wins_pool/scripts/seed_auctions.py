"""Seed a completed auction per pool season from rosters.csv, then create roster slots from it as the app does.

The original bidding was never recorded, so each lot gets one bid at its final price and the activity feed is a
replay. Replay events carry a `historical_seed` flag, which marks auctions this module may rebuild. Auctions run in
the app are never touched.
"""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, NamedTuple, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import engine
from nba_wins_pool.event.broker import get_broker
from nba_wins_pool.models.auction import (
    Auction,
    AuctionCompletedEvent,
    AuctionEvent,
    AuctionOverviewBid,
    AuctionOverviewLot,
    AuctionOverviewTeam,
    AuctionStartedEvent,
    AuctionStatus,
    LotBidAcceptedEvent,
    LotClosedEvent,
)
from nba_wins_pool.models.auction_event_log import AuctionEventLog
from nba_wins_pool.models.auction_lot import AuctionLot, AuctionLotStatus
from nba_wins_pool.models.auction_participant import AuctionParticipant
from nba_wins_pool.models.bid import Bid
from nba_wins_pool.models.pool_season import PoolSeason
from nba_wins_pool.models.roster import Roster
from nba_wins_pool.repositories.auction_event_log_repository import AuctionEventLogRepository
from nba_wins_pool.repositories.auction_lot_repository import AuctionLotRepository
from nba_wins_pool.repositories.auction_participant_repository import AuctionParticipantRepository
from nba_wins_pool.repositories.auction_repository import AuctionRepository
from nba_wins_pool.repositories.bid_repository import BidRepository
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.repositories.pool_repository import PoolRepository
from nba_wins_pool.repositories.pool_season_repository import PoolSeasonRepository
from nba_wins_pool.repositories.pool_team_season_result_repository import PoolTeamSeasonResultRepository
from nba_wins_pool.repositories.roster_repository import RosterRepository
from nba_wins_pool.repositories.roster_slot_repository import RosterSlotRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.scripts.pool_seasons import DEFAULT_STARTING_BUDGET, PoolSeasonRecord
from nba_wins_pool.services.auction_draft_service import AuctionDraftService
from nba_wins_pool.services.auction_event_service import AuctionEventService
from nba_wins_pool.services.auction_valuation_service import AuctionValuationService
from nba_wins_pool.utils.time import utc_now

logger = logging.getLogger("seed_auctions")

SECONDS_PER_BID = 15
HISTORICAL_SEED_FLAG = "historical_seed"


class SlotSpec(NamedTuple):
    """A team an owner won, as listed in rosters.csv."""

    team_id: uuid.UUID
    auction_price: Decimal


class ExistingAuction(Enum):
    SEEDED = "seeded"
    PLACEHOLDER = "placeholder"
    REAL = "real"


async def _classify(session: AsyncSession, auction: Auction) -> ExistingAuction:
    """Tell an auction built here apart from one run in the app, which must never be overwritten."""
    bid_count = await session.scalar(
        select(func.count())
        .select_from(Bid)
        .join(AuctionLot, AuctionLot.id == Bid.lot_id)
        .where(AuctionLot.auction_id == auction.id)
    )
    event_count = await session.scalar(
        select(func.count()).select_from(AuctionEventLog).where(AuctionEventLog.auction_id == auction.id)
    )
    seeded_event_count = await session.scalar(
        select(func.count())
        .select_from(AuctionEventLog)
        .where(AuctionEventLog.auction_id == auction.id)
        .where(AuctionEventLog.payload.op("->>")(HISTORICAL_SEED_FLAG).is_not(None))
    )
    if auction.status == AuctionStatus.NOT_STARTED and not bid_count and not event_count:
        return ExistingAuction.PLACEHOLDER
    if auction.status == AuctionStatus.COMPLETED and event_count and seeded_event_count == event_count:
        return ExistingAuction.SEEDED
    return ExistingAuction.REAL


async def _is_current(
    session: AsyncSession,
    auction: Auction,
    record: PoolSeasonRecord,
    rosters: List[Roster],
    slots_by_roster: Dict[uuid.UUID, List[SlotSpec]],
) -> bool:
    """True if a seeded auction still reflects rosters.csv (owner, team, price) and the file's date and budget."""
    if auction.starting_participant_budget != record.starting_budget:
        return False
    if record.auction_at is not None and auction.started_at != record.auction_at:
        return False
    rows = await session.execute(
        select(AuctionParticipant.name, AuctionLot.team_id, Bid.amount)
        .join(Bid, Bid.participant_id == AuctionParticipant.id)
        .join(AuctionLot, AuctionLot.id == Bid.lot_id)
        .where(AuctionLot.auction_id == auction.id)
    )
    current = {(name, team_id): amount for name, team_id, amount in rows}
    wanted = {
        (roster.name, slot.team_id): slot.auction_price for roster in rosters for slot in slots_by_roster[roster.id]
    }
    return current == wanted


async def _clear(session: AsyncSession, auction: Auction) -> None:
    """Delete an auction's lots, bids, participants and events, keeping the auction row."""
    lots = await AuctionLotRepository(session).get_all_by_auction_id(auction.id)
    auction.current_lot_id = None
    for lot in lots:
        lot.winning_bid_id = None
    await session.flush()
    await session.execute(delete(Bid).where(Bid.lot_id.in_([lot.id for lot in lots])))
    await session.execute(delete(AuctionLot).where(AuctionLot.auction_id == auction.id))
    await session.execute(delete(AuctionParticipant).where(AuctionParticipant.auction_id == auction.id))
    await session.execute(delete(AuctionEventLog).where(AuctionEventLog.auction_id == auction.id))
    await session.flush()


async def _owners(
    session: AsyncSession, pool_id: uuid.UUID, season: str, wanted: Dict[str, List[SlotSpec]]
) -> Tuple[List[Roster], Dict[uuid.UUID, List[SlotSpec]]]:
    """The season's rosters that appear in rosters.csv, with the teams each one won."""
    rosters = [r for r in await RosterRepository(session).get_all(pool_id=pool_id, season=season) if r.name in wanted]
    return rosters, {roster.id: wanted[roster.name] for roster in rosters}


def _draft_service(session: AsyncSession) -> AuctionDraftService:
    return AuctionDraftService(
        db_session=session,
        auction_repository=AuctionRepository(session),
        auction_lot_repository=AuctionLotRepository(session),
        bid_repository=BidRepository(session),
        pool_repository=PoolRepository(session),
        pool_season_repository=PoolSeasonRepository(session),
        nba_projections_repository=NBAProjectionsRepository(session),
        auction_participant_repository=AuctionParticipantRepository(session),
        roster_repository=RosterRepository(session),
        roster_slot_repository=RosterSlotRepository(session),
        team_repository=TeamRepository(session),
        auction_event_service=AuctionEventService(AuctionEventLogRepository(session), get_broker()),
        event_broker=get_broker(),
    )


async def import_rosters(session: AsyncSession, auction: Auction, rebuilt: bool) -> None:
    """Create the roster slots from the auction's lots, unless the existing ones already match."""
    lots = await AuctionLotRepository(session).get_all_by_auction_id(auction.id)
    participants = await AuctionParticipantRepository(session).get_all_by_auction_id(auction.id)
    roster_ids = [p.roster_id for p in participants]
    existing = await RosterSlotRepository(session).get_all_by_roster_id_in(roster_ids)
    have = {(s.roster_id, s.team_id, s.auction_price, s.auction_lot_id) for s in existing}

    participant_roster = {p.id: p.roster_id for p in participants}
    wanted = set()
    for lot in lots:
        bid = await session.get(Bid, lot.winning_bid_id) if lot.winning_bid_id else None
        if bid is not None:
            wanted.add((participant_roster[bid.participant_id], lot.team_id, bid.amount, lot.id))

    if have == wanted and not rebuilt:
        return
    slots = await _draft_service(session).create_roster_slots_from_lots_won(auction.id)
    logger.info(f"{auction.season}: imported {len(slots)} roster slots from the auction")


async def seed_auction(
    session: AsyncSession, pool_id: uuid.UUID, record: PoolSeasonRecord, wanted: Dict[str, List[SlotSpec]]
) -> Tuple[Optional[Auction], bool]:
    """Build (or keep) the season's auction. Returns it with whether it was just built; None if it is the app's."""
    pool_slug, season = record.pool, record.season
    rosters, slots_by_roster = await _owners(session, pool_id, season, wanted)
    if len(rosters) != len(wanted):
        logger.warning(f"{pool_slug} {season}: rosters missing, run seed_data.py first; skipping")
        return None, False

    auctions = await AuctionRepository(session).get_all(pool_id=pool_id, season=season, status=None)
    auction: Optional[Auction] = auctions[0] if auctions else None

    if auction:
        kind = await _classify(session, auction)
        if kind == ExistingAuction.REAL:
            logger.info(f"{pool_slug} {season}: auction was run in the app; leaving it alone")
            return None, False
        if kind == ExistingAuction.SEEDED and await _is_current(session, auction, record, rosters, slots_by_roster):
            logger.info(f"{pool_slug} {season}: auction is up to date")
            return auction, False
        logger.info(f"{pool_slug} {season}: {'rebuilding' if kind == ExistingAuction.SEEDED else 'filling in'} auction")
        await _clear(session, auction)

    starting_budget = record.starting_budget
    max_lots = max(len(slots) for slots in slots_by_roster.values())
    if auction is None:
        auction = Auction(
            pool_id=pool_id,
            season=season,
            max_lots_per_participant=max_lots,
            starting_participant_budget=starting_budget,
        )
        session.add(auction)
    auction.status = AuctionStatus.COMPLETED
    auction.current_lot_id = None
    auction.max_lots_per_participant = max_lots
    auction.starting_participant_budget = starting_budget
    await session.flush()

    participants = {}
    for roster in rosters:
        slots = slots_by_roster[roster.id]
        spent = sum((slot.auction_price or Decimal(0) for slot in slots), Decimal(0))
        participant = AuctionParticipant(
            name=roster.name,
            auction_id=auction.id,
            roster_id=roster.id,
            budget=starting_budget - spent,
            num_lots_won=len(slots),
        )
        session.add(participant)
        participants[roster.id] = participant
    await session.flush()

    queues = [
        sorted(slots_by_roster[r.id], key=lambda slot: slot.auction_price or Decimal(0), reverse=True)
        for r in sorted(rosters, key=lambda r: r.name)
    ]
    owner_ids = [r.id for r in sorted(rosters, key=lambda r: r.name)]
    nominations = [
        (owner_ids[i], queue[turn]) for turn in range(max_lots) for i, queue in enumerate(queues) if turn < len(queue)
    ]

    started_at = record.auction_at or utc_now()
    teams = {t.id: t for t in await TeamRepository(session).get_all_by_ids([slot.team_id for _, slot in nominations])}
    events: List[AuctionEvent] = [
        AuctionStartedEvent(auction_id=auction.id, created_at=started_at, started_at=started_at)
    ]

    clock = started_at
    for roster_id, slot in nominations:
        participant = participants[roster_id]
        opened_at = clock + timedelta(seconds=SECONDS_PER_BID)
        closed_at = opened_at + timedelta(seconds=SECONDS_PER_BID)
        lot = AuctionLot(
            auction_id=auction.id,
            team_id=slot.team_id,
            status=AuctionLotStatus.CLOSED,
            created_at=started_at,
            opened_at=opened_at,
            closed_at=closed_at,
        )
        session.add(lot)
        await session.flush()
        bid = Bid(lot_id=lot.id, participant_id=participant.id, amount=slot.auction_price, created_at=opened_at)
        session.add(bid)
        await session.flush()
        lot.winning_bid_id = bid.id

        team = teams[slot.team_id]
        overview_team = AuctionOverviewTeam(
            id=team.id, name=team.name, abbreviation=team.abbreviation, logo_url=team.logo_url
        )
        winning_bid = AuctionOverviewBid(id=bid.id, bidder_name=participant.name, amount=slot.auction_price)
        events.append(
            LotBidAcceptedEvent(
                auction_id=auction.id,
                created_at=opened_at,
                lot=AuctionOverviewLot(
                    id=lot.id, status=AuctionLotStatus.READY, team=overview_team, winning_bid=winning_bid
                ),
            )
        )
        events.append(
            LotClosedEvent(
                auction_id=auction.id,
                created_at=closed_at,
                lot=AuctionOverviewLot(
                    id=lot.id, status=AuctionLotStatus.CLOSED, team=overview_team, winning_bid=winning_bid
                ),
            )
        )
        clock = closed_at

    auction.started_at = started_at
    auction.completed_at = clock
    events.append(AuctionCompletedEvent(auction_id=auction.id, created_at=clock, completed_at=clock))
    for event in events:
        session.add(
            AuctionEventLog(
                auction_id=auction.id,
                event_type=event.type.value,
                payload={**event.model_dump(mode="json"), HISTORICAL_SEED_FLAG: True},
                created_at=event.created_at,
            )
        )

    await session.commit()
    logger.info(
        f"{pool_slug} {season}: seeded {len(rosters)} participants, {sum(map(len, slots_by_roster.values()))} lots"
    )
    return auction, True


async def refresh_valuations(
    session: AsyncSession, record: PoolSeasonRecord, auction: Auction, pool_season: PoolSeason
) -> None:
    """Recompute projected_wins / projected_price of a materialized season from its auction."""
    results_repo = PoolTeamSeasonResultRepository(session)
    results = await results_repo.get_all_by_pool_season(pool_season.id)
    if not results:
        return

    valuation_service = AuctionValuationService(
        db_session=session,
        external_data_repository=ExternalDataRepository(session),
        team_repository=TeamRepository(session),
        auction_repository=AuctionRepository(session),
        auction_participant_repository=AuctionParticipantRepository(session),
        nba_projections_repository=NBAProjectionsRepository(session),
        pool_season_repository=PoolSeasonRepository(session),
    )
    valuation = await valuation_service.get_valuation_data_for_auction(auction.id)
    by_team_id = {v.team_id: v for v in valuation.data if v.team_id is not None}
    winning_bids = await session.execute(
        select(AuctionLot.team_id, Bid.amount)
        .join(Bid, Bid.id == AuctionLot.winning_bid_id)
        .where(AuctionLot.auction_id == auction.id)
    )
    price_by_team_id = {team_id: amount for team_id, amount in winning_bids}

    updated = 0
    for result in results:
        if result.team_id in price_by_team_id:
            result.auction_price = price_by_team_id[result.team_id]
        team_valuation = by_team_id.get(result.team_id)
        if team_valuation is None:
            continue
        result.projected_wins = team_valuation.expected_wins
        if team_valuation.auction_value is not None:
            result.projected_price = Decimal(str(team_valuation.auction_value))
        session.add(result)
        updated += 1
    await session.commit()
    logger.info(f"{record.pool} {record.season}: refreshed valuations for {updated}/{len(results)} teams")


async def seed_auctions(
    records: Dict[Tuple[str, str], PoolSeasonRecord],
    wanted: Dict[Tuple[str, str], Dict[str, List[SlotSpec]]],
    pool_filter: Optional[str] = None,
) -> None:
    """Seed the auction and roster slots of every pool season in rosters.csv (see module docstring)."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        pool_repo = PoolRepository(session)
        pool_season_repo = PoolSeasonRepository(session)

        for (pool_slug, season), owners in sorted(wanted.items()):
            if pool_filter and pool_slug != pool_filter:
                continue
            pool = await pool_repo.get_by_slug(pool_slug)
            if pool is None:
                logger.warning(f"{pool_slug} {season}: no such pool, run seed_data.py first; skipping")
                continue

            record = records.get((pool_slug, season)) or PoolSeasonRecord(
                pool=pool_slug,
                season=season,
                starting_budget=DEFAULT_STARTING_BUDGET,
                auction_at=None,
                projection_date=None,
                rules=None,
            )
            auction, built = await seed_auction(session, pool.id, record, owners)
            if auction is None:
                continue
            await import_rosters(session, auction, rebuilt=built)
            pool_season = await pool_season_repo.get_by_pool_and_season(pool.id, season)
            if pool_season is not None:
                await refresh_valuations(session, record, auction, pool_season)
