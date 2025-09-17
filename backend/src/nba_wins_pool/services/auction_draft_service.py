import logging
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.event.broker import Broker, get_broker
from nba_wins_pool.models.auction import (
    Auction,
    AuctionCompletedEvent,
    AuctionCreate,
    AuctionOverview,
    AuctionOverviewBid,
    AuctionOverviewLot,
    AuctionOverviewParticipant,
    AuctionOverviewTeam,
    AuctionStartedEvent,
    AuctionStatus,
    AuctionTopic,
    LotBidAcceptedEvent,
    LotClosedEvent,
)
from nba_wins_pool.models.auction_lot import (
    AuctionLot,
    AuctionLotCreate,
    AuctionLotStatus,
)
from nba_wins_pool.models.auction_participant import (
    AuctionParticipant,
    AuctionParticipantCreate,
)
from nba_wins_pool.models.bid import Bid, BidCreate
from nba_wins_pool.models.roster_slot import RosterSlot
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.auction_lot_repository import AuctionLotRepository
from nba_wins_pool.repositories.auction_participant_repository import (
    AuctionParticipantRepository,
)
from nba_wins_pool.repositories.auction_repository import AuctionRepository
from nba_wins_pool.repositories.bid_repository import BidRepository
from nba_wins_pool.repositories.pool_repository import PoolRepository
from nba_wins_pool.repositories.roster_repository import RosterRepository
from nba_wins_pool.repositories.roster_slot_repository import RosterSlotRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.time import utc_now

logger = logging.getLogger(__name__)


class AuctionDraftService:
    def __init__(
        self,
        db_session: AsyncSession,
        auction_repository: AuctionRepository,
        auction_lot_repository: AuctionLotRepository,
        bid_repository: BidRepository,
        pool_repository: PoolRepository,
        auction_participant_repository: AuctionParticipantRepository,
        roster_repository: RosterRepository,
        roster_slot_repository: RosterSlotRepository,
        team_repository: TeamRepository,
        event_broker: Broker,
    ):
        self.db_session = db_session
        self.auction_repository = auction_repository
        self.auction_lot_repository = auction_lot_repository
        self.bid_repository = bid_repository
        self.pool_repository = pool_repository
        self.auction_participant_repository = auction_participant_repository
        self.roster_repository = roster_repository
        self.roster_slot_repository = roster_slot_repository
        self.team_repository = team_repository
        self.event_broker = event_broker

    # ================== Auction Lifecycle ==================

    async def create_auction(self, auction_create: AuctionCreate) -> Auction:
        """
        Create a new auction
        requirements:
        - pool must exist (foreign key constraint)
        - no other auctions can exist for the same pool and season (unique constraint)
        """
        auction = Auction.model_validate(auction_create)
        return await self.auction_repository.save(auction)

    async def get_auctions(
        self, pool_id: UUID = None, season: SeasonStr = None, status: AuctionStatus = None
    ) -> List[Auction]:
        """
        Get all auctions
        """
        auctions = await self.auction_repository.get_all(pool_id=pool_id, season=season, status=status)
        return auctions

    async def delete_auction(self, auction_id: UUID) -> bool:
        """
        Delete an auction
        requirements:
        - auction must exist
        """
        auction = await self.auction_repository.get_by_id(auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")
        await self.auction_repository.delete(auction)
        return True

    async def start_auction(self, auction_id: UUID) -> Auction:
        """
        Start an auction
        requirements:
        - auction must exist
        - auction must be in draft status
        """
        auction = await self.auction_repository.get_by_id(auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")
        if auction.status != AuctionStatus.NOT_STARTED:
            raise HTTPException(status_code=400, detail="Auction has already started")

        participants = await self.auction_participant_repository.get_all_by_auction_id(auction.id)
        if len(participants) < 2:
            raise HTTPException(status_code=400, detail="Cannot start without at least 2 participants")
        for participant in participants:
            if participant.budget < auction.max_lots_per_participant * auction.min_bid_increment:
                raise HTTPException(
                    status_code=400,
                    detail=f"Participant {participant.name} has insufficient funds {participant.budget}",
                )
        lots = await self.auction_lot_repository.get_all_by_auction_id(auction.id)
        if not lots:
            raise HTTPException(status_code=400, detail="Cannot start without lots")
        lots_needed = len(participants) * auction.max_lots_per_participant
        lots_available = len(lots)
        if lots_needed > lots_available:
            raise HTTPException(
                status_code=400,
                detail=f"Participants ({len(participants)}) * Max lots per participant ({auction.max_lots_per_participant}) > Lots available ({lots_available})",
            )

        if auction.starting_participant_budget < auction.max_lots_per_participant * auction.min_bid_increment:
            raise HTTPException(status_code=400, detail="Starting participant budget is too low")

        auction.status = AuctionStatus.ACTIVE
        auction.started_at = utc_now()

        auction = await self.auction_repository.save(auction)

        try:
            await self.event_broker.publish(
                topic=AuctionTopic(auction_id=auction.id),
                event=AuctionStartedEvent(auction_id=auction.id, started_at=auction.started_at),
            )
        except Exception as e:
            logger.error(f"Failed to publish auction started event: {e}", exc_info=True)
        return auction

    async def complete_auction(self, auction_id: UUID) -> Auction:
        """
        Complete an auction
        requirements:
        - auction must be active
        - all lots must be closed
        successful outcome:
        - auction is completed
        - return auction
        """

        auction = await self.auction_repository.get_by_id(auction_id)
        if auction.status != AuctionStatus.ACTIVE:
            raise HTTPException(status_code=400, detail="Auction is not active")

        if auction.current_lot_id:
            lot = await self.auction_lot_repository.get_by_id(auction.current_lot_id)
            if lot.status == AuctionLotStatus.OPEN:
                raise HTTPException(status_code=400, detail=f"Auction has an open lot: {auction.current_lot_id}")

        auction.status = AuctionStatus.COMPLETED
        auction.completed_at = utc_now()
        auction = await self.auction_repository.save(auction)

        try:
            await self.event_broker.publish(
                topic=AuctionTopic(auction_id=auction.id),
                event=AuctionCompletedEvent(auction_id=auction.id, completed_at=auction.completed_at),
            )
        except Exception as e:
            logger.error(f"Failed to publish auction completed event: {e}", exc_info=True)
        return auction

    # ================== Auction Participants ==================

    async def add_participant(self, participant_create: AuctionParticipantCreate) -> AuctionParticipant:
        """
        Add participants to an auction
        requirements:
        - auction must be in draft status
        - participant must not already exist (db unique constraint)
        """
        auction = await self.auction_repository.get_by_id(participant_create.auction_id)
        roster = await self.roster_repository.get_by_id(participant_create.roster_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")
        if auction.status != AuctionStatus.NOT_STARTED:
            raise HTTPException(status_code=400, detail=f"Auction not configurable in state {auction.status}")
        if not roster:
            raise HTTPException(status_code=404, detail="Roster not found")
        if roster.pool_id != auction.pool_id:
            raise HTTPException(status_code=400, detail="Roster does not belong to the same pool as the auction")
        if roster.season != auction.season:
            raise HTTPException(status_code=400, detail="Roster does not belong to the same season as the auction")
        participant = AuctionParticipant(
            auction_id=participant_create.auction_id,
            roster_id=participant_create.roster_id,
            name=participant_create.name,
            budget=auction.starting_participant_budget,
        )
        return await self.auction_participant_repository.save(participant)

    async def remove_participant(self, participant_id: UUID) -> bool:
        """
        Remove a participant from an auction
        requirements:
        - auction must be in draft status
        """
        participant = await self.auction_participant_repository.get_by_id(participant_id)
        if not participant:
            raise HTTPException(status_code=404, detail="Participant not found")
        auction = await self.auction_repository.get_by_id(participant.auction_id)
        if auction.status != AuctionStatus.NOT_STARTED:
            raise HTTPException(status_code=400, detail=f"Auction not configurable in state {auction.status}")
        await self.auction_participant_repository.delete(participant)
        return True

    async def add_participants_by_pool(self, auction_id: UUID) -> List[AuctionParticipant]:
        auction = await self.auction_repository.get_by_id(auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")
        if auction.status != AuctionStatus.NOT_STARTED:
            raise HTTPException(status_code=400, detail=f"Auction not configurable in state {auction.status}")
        pool = await self.pool_repository.get_by_id(auction.pool_id)
        if not pool:
            raise HTTPException(status_code=404, detail="Pool not found")

        participants = await self.auction_participant_repository.get_all_by_auction_id(auction_id)
        participant_roster_ids = {p.roster_id for p in participants}

        pool_rosters = await self.roster_repository.get_all(pool_id=auction.pool_id, season=auction.season)
        if not pool_rosters:
            raise HTTPException(status_code=404, detail="Pool rosters not found")
        participants_to_add = []
        for roster in pool_rosters:
            if roster.id in participant_roster_ids:
                logger.info(f"Participant already exists for roster {roster.id}, skipping")
                continue
            participant = AuctionParticipant(
                auction_id=auction_id,
                roster_id=roster.id,
                name=roster.name,
                budget=auction.starting_participant_budget,
            )
            participants_to_add.append(participant)

        return await self.auction_participant_repository.save_all(participants_to_add)

    # ================== Auction Lots ==================

    async def create_lot(self, lot_create: AuctionLotCreate) -> AuctionLot:
        """
        Add a lot to an auction
        requirements:
        - auction must exist
        - auction must be in draft status
        """
        auction = await self.auction_repository.get_by_id(lot_create.auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")
        if auction.status != AuctionStatus.NOT_STARTED:
            raise HTTPException(status_code=400, detail=f"Auction not configurable in state {auction.status}")

        lot = AuctionLot.model_validate(lot_create)
        return await self.auction_lot_repository.save(lot)

    async def close_lot(self, lot_id: UUID) -> AuctionLot:
        """
        Close a lot
        requirements:
        - lot must be open
        successful outcome:
        - lot is closed
        """
        lot = await self.auction_lot_repository.get_by_id(lot_id)
        if lot.status != AuctionLotStatus.OPEN:
            raise HTTPException(status_code=400, detail="Lot is not open")

        winner = None
        winning_bid = None
        if lot.winning_bid_id:
            winning_bid = await self.bid_repository.get_by_id(lot.winning_bid_id)
            winner = await self.auction_participant_repository.get_by_id(winning_bid.participant_id)
        else:
            logger.error(f"Lot {lot.id} has no winning bid, closing anyways")

        if winner:
            winner.num_lots_won += 1
        lot.status = AuctionLotStatus.CLOSED
        lot.closed_at = utc_now()
        team = await self.team_repository.get_by_id(lot.team_id)
        event = LotClosedEvent(
            auction_id=lot.auction_id,
            lot=self._build_auction_overview_lot(lot, team, winning_bid, winner),
        )
        try:
            if winner:
                self.db_session.add(winner)
            self.db_session.add(lot)
            await self.db_session.commit()
            await self.db_session.refresh(lot)
        except Exception as e:
            await self.db_session.rollback()
            raise e

        try:
            await self.event_broker.publish(
                topic=AuctionTopic(auction_id=lot.auction_id),
                event=event,
            )
        except Exception as e:
            logger.error(f"Failed to publish lot closed event: {e}", exc_info=True)
        return lot

    async def add_lots_by_league(self, auction_id: UUID, league_slug: LeagueSlug) -> List[AuctionLot]:
        if league_slug != LeagueSlug.NBA:
            raise HTTPException(status_code=400, detail="Invalid league slug")

        auction = await self.auction_repository.get_by_id(auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")
        if auction.status != AuctionStatus.NOT_STARTED:
            raise HTTPException(status_code=400, detail=f"Auction not configurable in state {auction.status}")

        teams = await self.team_repository.get_all_by_league_slug(league_slug)
        existing_lots = await self.auction_lot_repository.get_all_by_auction_id(auction_id)
        existing_team_ids = {lot.team_id for lot in existing_lots}

        lots_to_add = []
        for team in teams:
            if team.id in existing_team_ids:
                logger.info(f"Lot already exists for team {team.name} ({team.id}), skipping")
                continue
            lot = AuctionLot(auction_id=auction_id, team_id=team.id)
            lots_to_add.append(lot)
        added_lots = await self.auction_lot_repository.save_all(lots_to_add)
        return added_lots

    # ================== Auction Lot Bids ==================

    @staticmethod
    def _calculate_participant_max_bid(participant: AuctionParticipant, auction: Auction) -> Decimal:
        remaining_lots = auction.max_lots_per_participant - participant.num_lots_won - 1
        return participant.budget - (remaining_lots * auction.min_bid_increment)

    @staticmethod
    def _calculate_min_bid(auction: Auction, winning_bid: Optional[Bid]) -> Decimal:
        if winning_bid is None:
            return auction.min_bid_increment
        return winning_bid.amount + auction.min_bid_increment

    async def place_bid(self, bid_create: BidCreate) -> Bid:
        """
        Place a bid on a lot. Nominates lot if no current lot is open
        requirements:
        - lot must be open
        - auction must be active
        - bidder must have enough budget
        - bidder must not have reached max lots won
        - bid must be greater than current highest bid
        - bid must be at least the minimum bid increment
        successful outcome:
        - bid is placed
        - previous winning bidder's budget is increased
        - participant's budget is deducted
        - lot's winning bid is updated
        """
        bid = Bid.model_validate(bid_create)
        participant = await self.auction_participant_repository.get_by_id(bid.participant_id)
        if not participant:
            raise HTTPException(status_code=400, detail="Participant not found")

        lot = await self.auction_lot_repository.get_by_id(bid.lot_id)
        if not lot:
            raise HTTPException(status_code=400, detail="Lot not found")

        if lot.status == AuctionLotStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Lot is closed")

        auction = await self.auction_repository.get_by_id(lot.auction_id)
        if auction.status != AuctionStatus.ACTIVE:
            raise HTTPException(status_code=400, detail="Auction is not active")

        if participant.num_lots_won >= auction.max_lots_per_participant:
            raise HTTPException(status_code=400, detail="Participant has reached the maximum number of lots won")

        max_bid = self._calculate_participant_max_bid(participant, auction)
        if bid.amount > max_bid:
            raise HTTPException(
                status_code=400, detail=f"Bid of {bid.amount} exceeds participant's maximum bid of {max_bid}"
            )

        if auction.current_lot_id is not None:
            if auction.current_lot_id != lot.id:
                current_lot = await self.auction_lot_repository.get_by_id(auction.current_lot_id)
                if current_lot.status != AuctionLotStatus.CLOSED:
                    raise HTTPException(status_code=400, detail="Current lot must be closed before opening a new lot")

        previous_winner = None
        previous_winning_bid = None
        if lot.winning_bid_id:
            previous_winning_bid = await self.bid_repository.get_by_id(lot.winning_bid_id)
            previous_winner = await self.auction_participant_repository.get_by_id(previous_winning_bid.participant_id)

        min_bid = self._calculate_min_bid(auction, previous_winning_bid)
        if bid.amount < min_bid:
            raise HTTPException(
                status_code=400, detail=f"Bid of {bid.amount} is lower than the minimum bid of {min_bid}"
            )
        team = await self.team_repository.get_by_id(lot.team_id)
        topic = AuctionTopic(auction_id=auction.id)
        event = LotBidAcceptedEvent(
            auction_id=auction.id,
            lot=self._build_auction_overview_lot(lot, team, bid, participant),
        )

        try:
            self.db_session.add(bid)
            await self.db_session.flush()

            lot.winning_bid_id = bid.id
            if lot.status == AuctionLotStatus.READY:
                lot.status = AuctionLotStatus.OPEN
                lot.opened_at = utc_now()
            self.db_session.add(lot)

            auction.current_lot_id = lot.id
            self.db_session.add(auction)

            if previous_winner:
                previous_winner.budget += previous_winning_bid.amount
                self.db_session.add(previous_winner)

            participant.budget -= bid.amount
            self.db_session.add(participant)
            await self.db_session.commit()
            await self.db_session.refresh(bid)
        except Exception as e:
            await self.db_session.rollback()
            raise e

        try:
            await self.event_broker.publish(topic=topic, event=event)
        except Exception as e:
            logger.error(f"Failed to publish lot bid accepted event: {e}")
        return bid

    # ================== Auction <> Pool Roster ==================

    async def create_roster_slots_from_lots_won(self, auction_id: UUID, replace: bool = True) -> List[RosterSlot]:
        """
        Assign roster slots
        requirements:
        - auction must be completed
        successful outcome:
        - team ownerships are assigned
        - return team ownerships
        """
        auction = await self.auction_repository.get_by_id(auction_id)
        if not auction:
            raise HTTPException(status_code=400, detail="Auction not found")
        if auction.status != AuctionStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Auction is not completed")

        lots = await self.auction_lot_repository.get_all_by_auction_id(auction_id)
        participants = await self.auction_participant_repository.get_all_by_auction_id(auction_id)
        participants_by_id = {p.id: p for p in participants}
        roster_slots = []
        for lot in lots:
            if lot.status != AuctionLotStatus.CLOSED or not lot.winning_bid_id:
                continue

            winning_bid = await self.bid_repository.get_by_id(lot.winning_bid_id)
            participant = participants_by_id.get(winning_bid.participant_id)

            roster_slot = RosterSlot(
                roster_id=participant.roster_id,
                team_id=lot.team_id,
                auction_lot_id=lot.id,
                auction_price=winning_bid.amount,
            )
            roster_slots.append(roster_slot)

        roster_ids = [p.roster_id for p in participants]
        if replace:
            await self.roster_slot_repository.delete_all_by_roster_id_in(roster_ids)
        else:
            # Filter out duplicate teams
            roster_slots = await self.roster_slot_repository.get_all_by_roster_id_in(roster_ids)
            team_ids = {r.team_id for r in roster_slots}
            roster_slots = [r for r in roster_slots if r.team_id not in team_ids]

        if not roster_slots:
            logger.info("No roster slots created")
            return []
        return await self.roster_slot_repository.save_all(roster_slots)

    # ================== Auction Overview ==================

    async def get_auction_overview(self, auction_id: UUID) -> AuctionOverview:
        auction = await self.auction_repository.get_by_id(auction_id)
        if not auction:
            raise HTTPException(status_code=400, detail="Auction not found")

        lots = await self.auction_lot_repository.get_all_by_auction_id(auction_id)
        participants = await self.auction_participant_repository.get_all_by_auction_id(auction_id)

        # Get all winning bids
        winning_bid_ids = [lot.winning_bid_id for lot in lots if lot.winning_bid_id]
        winning_bids = await self.bid_repository.get_all_by_ids(winning_bid_ids) if winning_bid_ids else []

        # Get all teams for lots
        team_ids = [lot.team_id for lot in lots]
        teams = await self.team_repository.get_all_by_ids(team_ids) if team_ids else []

        # Create lookup dictionaries
        winning_bids_by_id = {bid.id: bid for bid in winning_bids}
        teams_by_id = {team.id: team for team in teams}
        participants_by_id = {p.id: p for p in participants}

        # Build overview lots
        overview_lots = []
        for lot in lots:
            team = teams_by_id.get(lot.team_id)
            winning_bid = winning_bids_by_id.get(lot.winning_bid_id) if lot.winning_bid_id else None
            winning_participant = participants_by_id.get(winning_bid.participant_id) if winning_bid else None

            if team:  # Only include lots with valid team data
                overview_lot = self._build_auction_overview_lot(lot, team, winning_bid, winning_participant)
                overview_lots.append(overview_lot)

        # Build overview participants
        overview_participants = []
        for participant in participants:
            participant_lots = [
                lot
                for lot in lots
                if lot.winning_bid_id
                and winning_bids_by_id[lot.winning_bid_id].participant_id == participant.id
                and lot.status == AuctionLotStatus.CLOSED
            ]
            participant_winning_bids = [
                winning_bids_by_id.get(lot.winning_bid_id)
                for lot in participant_lots
                if lot.winning_bid_id and lot.winning_bid_id in winning_bids_by_id
            ]

            overview_participant = self._build_auction_overview_participant(
                participant, participant_lots, participant_winning_bids, teams_by_id
            )
            overview_participants.append(overview_participant)

        # Find current lot
        current_lot = None
        if auction.current_lot_id:
            current_lot_obj = next((lot for lot in lots if lot.id == auction.current_lot_id), None)
            if current_lot_obj:
                team = teams_by_id.get(current_lot_obj.team_id)
                winning_bid = (
                    winning_bids_by_id.get(current_lot_obj.winning_bid_id) if current_lot_obj.winning_bid_id else None
                )
                winning_participant = participants_by_id.get(winning_bid.participant_id) if winning_bid else None
                if team:
                    current_lot = self._build_auction_overview_lot(
                        current_lot_obj, team, winning_bid, winning_participant
                    )

        return AuctionOverview(
            id=auction.id,
            pool_id=auction.pool_id,
            season=auction.season,
            status=auction.status,
            lots=overview_lots,
            participants=overview_participants,
            current_lot=current_lot,
            started_at=auction.started_at,
            completed_at=auction.completed_at,
            max_lots_per_participant=auction.max_lots_per_participant,
            min_bid_increment=auction.min_bid_increment,
            starting_participant_budget=auction.starting_participant_budget,
        )

    @staticmethod
    def _build_auction_overview_team(team: Team) -> AuctionOverviewTeam:
        return AuctionOverviewTeam(id=team.id, name=team.name, logo_url=team.logo_url)

    @staticmethod
    def _build_auction_overview_lot(
        auction_lot: AuctionLot,
        team: Team,
        winning_bid: Optional[Bid] = None,
        winning_participant: Optional[AuctionParticipant] = None,
    ) -> AuctionOverviewLot:
        if winning_bid and winning_participant:
            winning_bid = AuctionOverviewBid(bidder_name=winning_participant.name, amount=winning_bid.amount)

        return AuctionOverviewLot(
            id=auction_lot.id,
            status=auction_lot.status,
            team=AuctionDraftService._build_auction_overview_team(team),
            winning_bid=winning_bid,
        )

    @staticmethod
    def _build_auction_overview_bid(bid: Bid, participant: AuctionParticipant) -> AuctionOverviewBid:
        return AuctionOverviewBid(bidder_name=participant.name, amount=bid.amount)

    @staticmethod
    def _build_auction_overview_participant(
        participant: AuctionParticipant, lots_won: List[AuctionLot], winning_bids: List[Bid], teams_by_id: dict
    ) -> AuctionOverviewParticipant:
        # Build lots won summary
        summary_lots_won = []
        for lot in lots_won:
            team = teams_by_id.get(lot.team_id)
            if team:
                winning_bid = next((bid for bid in winning_bids if bid and lot.winning_bid_id == bid.id), None)
                summary_lot = AuctionDraftService._build_auction_overview_lot(lot, team, winning_bid, participant)
                summary_lots_won.append(summary_lot)

        return AuctionOverviewParticipant(
            id=participant.id, name=participant.name, budget=participant.budget, lots_won=summary_lots_won
        )


def get_auction_draft_service(
    db_session: AsyncSession = Depends(get_db_session), event_broker: Broker = Depends(get_broker)
) -> AuctionDraftService:
    return AuctionDraftService(
        db_session=db_session,
        auction_repository=AuctionRepository(db_session),
        auction_lot_repository=AuctionLotRepository(db_session),
        bid_repository=BidRepository(db_session),
        pool_repository=PoolRepository(db_session),
        auction_participant_repository=AuctionParticipantRepository(db_session),
        roster_repository=RosterRepository(db_session),
        roster_slot_repository=RosterSlotRepository(db_session),
        team_repository=TeamRepository(db_session),
        event_broker=event_broker,
    )
