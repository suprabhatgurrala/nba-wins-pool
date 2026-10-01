from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from nba_wins_pool.models.auction import Auction, AuctionStatus
from nba_wins_pool.models.auction_participant import AuctionParticipant
from nba_wins_pool.models.roster import Roster
from nba_wins_pool.services.roster_service import RosterService

POOL_ID = uuid4()
SEASON = "2025-26"


class FakeRosterRepository:
    def __init__(self):
        self.rosters: List[Roster] = []

    async def save(self, roster: Roster) -> Roster:
        if roster not in self.rosters:
            self.rosters.append(roster)
        return roster

    async def save_all(self, rosters: List[Roster]) -> List[Roster]:
        return [await self.save(r) for r in rosters]

    async def delete(self, roster: Roster) -> bool:
        self.rosters.remove(roster)
        return True


class FakeAuctionRepository:
    def __init__(self, auctions: List[Auction]):
        self.auctions = auctions

    async def get_all(self, pool_id: Optional[UUID], season: Optional[str], status: Optional[AuctionStatus]):
        return [a for a in self.auctions if a.pool_id == pool_id and a.season == season]

    async def delete(self, auction: Auction) -> bool:
        self.auctions.remove(auction)
        return True


class FakeAuctionParticipantRepository:
    def __init__(self):
        self.participants: List[AuctionParticipant] = []

    async def get_all_by_auction_id(self, auction_id: UUID):
        return [p for p in self.participants if p.auction_id == auction_id]

    async def get_by_roster_id_and_auction_id(self, roster_id: UUID, auction_id: UUID):
        return next(
            (p for p in self.participants if p.roster_id == roster_id and p.auction_id == auction_id),
            None,
        )

    async def save(self, participant: AuctionParticipant):
        if participant not in self.participants:
            self.participants.append(participant)
        return participant

    async def save_all(self, participants: List[AuctionParticipant]):
        return [await self.save(p) for p in participants]

    async def delete(self, participant: AuctionParticipant) -> bool:
        self.participants.remove(participant)
        return True


def make_auction(status: AuctionStatus = AuctionStatus.NOT_STARTED) -> Auction:
    return Auction(
        pool_id=POOL_ID,
        season=SEASON,
        status=status,
        max_lots_per_participant=5,
        min_bid_increment=Decimal(1),
        starting_participant_budget=Decimal(215),
    )


def make_roster(name: str) -> Roster:
    return Roster(pool_id=POOL_ID, season=SEASON, name=name)


def make_service(auctions: List[Auction]):
    rosters = FakeRosterRepository()
    participants = FakeAuctionParticipantRepository()
    service = RosterService(rosters, FakeAuctionRepository(auctions), participants)
    return service, rosters, participants


async def test_create_roster_deletes_auction_before_start():
    auction = make_auction()
    service, rosters, _ = make_service([auction])

    await service.create_roster(make_roster("Alice"))

    assert len(rosters.rosters) == 1
    assert service.auction_repository.auctions == []


async def test_create_roster_without_auction_just_saves():
    service, rosters, _ = make_service([])

    await service.create_roster(make_roster("Alice"))

    assert len(rosters.rosters) == 1


async def test_create_roster_leaves_started_auction_alone():
    auction = make_auction(AuctionStatus.ACTIVE)
    service, rosters, _ = make_service([auction])

    await service.create_roster(make_roster("Alice"))

    assert service.auction_repository.auctions == [auction]
    assert len(rosters.rosters) == 1


async def test_create_rosters_batch_deletes_auction_once():
    service, rosters, _ = make_service([make_auction()])

    await service.create_rosters([make_roster("Alice"), make_roster("Bob")])

    assert len(rosters.rosters) == 2
    assert service.auction_repository.auctions == []


async def test_rename_roster_updates_participant_name_and_keeps_auction():
    auction = make_auction()
    service, _, participants = make_service([auction])
    roster = make_roster("Alice")
    await service.roster_repository.save(roster)
    await participants.save(
        AuctionParticipant(auction_id=auction.id, roster_id=roster.id, name="Alice", budget=Decimal(215))
    )

    await service.rename_roster(roster, "Alicia")

    assert roster.name == "Alicia"
    assert participants.participants[0].name == "Alicia"
    assert service.auction_repository.auctions == [auction]


async def test_delete_roster_deletes_auction_before_start():
    auction = make_auction()
    service, rosters, participants = make_service([auction])
    roster = make_roster("Alice")
    await service.roster_repository.save(roster)
    await participants.save(
        AuctionParticipant(auction_id=auction.id, roster_id=roster.id, name="Alice", budget=Decimal(215))
    )

    await service.delete_roster(roster)

    assert rosters.rosters == []
    assert service.auction_repository.auctions == []


async def test_delete_roster_is_blocked_once_auction_started():
    auction = make_auction(AuctionStatus.ACTIVE)
    service, rosters, participants = make_service([auction])
    roster = make_roster("Alice")
    await service.roster_repository.save(roster)
    await participants.save(
        AuctionParticipant(auction_id=auction.id, roster_id=roster.id, name="Alice", budget=Decimal(215))
    )

    with pytest.raises(HTTPException) as exc:
        await service.delete_roster(roster)

    assert exc.value.status_code == 409
    assert rosters.rosters == [roster]
    assert service.auction_repository.auctions == [auction]
