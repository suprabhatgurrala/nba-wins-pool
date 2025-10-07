import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from sqlmodel import Field, SQLModel, UniqueConstraint

from nba_wins_pool.event.core import EventType
from nba_wins_pool.models.auction_lot import AuctionLotStatus
from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now


class AuctionStatus(str, Enum):
    NOT_STARTED = "not_started"
    ACTIVE = "active"
    COMPLETED = "completed"


class Auction(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(foreign_key="pool.id", index=True)
    season: SeasonStr = Field(index=True)

    # state
    status: AuctionStatus = Field(default=AuctionStatus.NOT_STARTED)
    current_lot_id: Optional[uuid.UUID] = Field(default=None, foreign_key="auctionlot.id")

    # config
    max_lots_per_participant: int = Field(gt=0)
    min_bid_increment: Decimal = Field(default=1, decimal_places=2)
    starting_participant_budget: Decimal = Field(gt=0, decimal_places=2)

    # timestamps
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    __table_args__ = (UniqueConstraint("pool_id", "season"),)


class AuctionCreate(SQLModel):
    pool_id: uuid.UUID
    season: SeasonStr
    max_lots_per_participant: int = Field(gt=0)
    min_bid_increment: Decimal = Field(default=1)
    starting_participant_budget: Decimal = Field(gt=0)


class AuctionComplete(SQLModel):
    id: uuid.UUID


class AuctionUpdate(SQLModel):
    status: Optional[AuctionStatus] = None
    max_lots_per_participant: Optional[int] = Field(default=None, gt=0)
    min_bid_increment: Optional[Decimal] = None
    starting_participant_budget: Optional[Decimal] = Field(default=None, gt=0)


# ========= response models =========
class AuctionOverviewPool(SQLModel):
    id: uuid.UUID
    name: str


class AuctionOverviewBid(SQLModel):
    bidder_name: str
    amount: Decimal


class AuctionOverviewTeam(SQLModel):
    id: uuid.UUID
    name: str
    abbreviation: str
    logo_url: str


class AuctionOverviewLot(SQLModel):
    id: uuid.UUID
    status: AuctionLotStatus
    team: AuctionOverviewTeam
    winning_bid: Optional[AuctionOverviewBid]


class AuctionOverviewParticipant(SQLModel):
    id: uuid.UUID
    name: str
    budget: Decimal
    lots_won: List[AuctionOverviewLot]


class AuctionOverview(SQLModel):
    id: uuid.UUID
    pool: AuctionOverviewPool
    season: SeasonStr
    status: AuctionStatus
    lots: List[AuctionOverviewLot]
    participants: List[AuctionOverviewParticipant]
    current_lot: Optional[AuctionOverviewLot]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    max_lots_per_participant: int
    min_bid_increment: Decimal
    starting_participant_budget: Decimal


# ========= events =========
class AuctionTopic(SQLModel):
    auction_id: uuid.UUID

    def __str__(self):
        return f"auction:{self.auction_id}"


class AuctionEventType(EventType):
    AUCTION_STARTED = "auction_started"
    AUCTION_COMPLETED = "auction_completed"
    BID_ACCEPTED = "bid_accepted"
    LOT_CLOSED = "lot_closed"


class AuctionEvent(SQLModel):
    auction_id: uuid.UUID
    type: AuctionEventType
    created_at: datetime = Field(default_factory=utc_now)


class AuctionStartedEvent(AuctionEvent):
    type: AuctionEventType = AuctionEventType.AUCTION_STARTED
    started_at: datetime


class AuctionCompletedEvent(AuctionEvent):
    type: AuctionEventType = AuctionEventType.AUCTION_COMPLETED
    completed_at: datetime


class LotClosedEvent(AuctionEvent):
    type: AuctionEventType = AuctionEventType.LOT_CLOSED
    lot: AuctionOverviewLot


class LotBidAcceptedEvent(AuctionEvent):
    type: AuctionEventType = AuctionEventType.BID_ACCEPTED
    lot: AuctionOverviewLot
