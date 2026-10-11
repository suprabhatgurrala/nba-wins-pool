from typing import List, Optional

from fastapi import Depends, HTTPException, status

from nba_wins_pool.models.auction import Auction, AuctionStatus
from nba_wins_pool.models.roster import Roster
from nba_wins_pool.repositories.auction_participant_repository import (
    AuctionParticipantRepository,
    get_auction_participant_repository,
)
from nba_wins_pool.repositories.auction_repository import AuctionRepository, get_auction_repository
from nba_wins_pool.repositories.roster_repository import RosterRepository, get_roster_repository


class RosterService:
    """Roster changes that keep the season's auction consistent with its rosters.

    An auction is sized for a specific set of participants (budget, teams per person, one participant per
    roster), so it can't be patched up when that set changes. Adding or removing rosters therefore deletes the
    season's auction while it hasn't started, and it gets set up again with defaults for the new head count.
    Renaming only relabels the auction's participant. An auction that has started is never touched.
    """

    def __init__(
        self,
        roster_repository: RosterRepository,
        auction_repository: AuctionRepository,
        auction_participant_repository: AuctionParticipantRepository,
    ):
        self.roster_repository = roster_repository
        self.auction_repository = auction_repository
        self.auction_participant_repository = auction_participant_repository

    async def _get_auction(self, roster: Roster) -> Optional[Auction]:
        auctions = await self.auction_repository.get_all(pool_id=roster.pool_id, season=roster.season, status=None)
        return auctions[0] if auctions else None

    async def _discard_auction_before_start(self, roster: Roster) -> None:
        """Delete the season's auction (and its participants and lots) if it hasn't started."""
        auction = await self._get_auction(roster)
        if auction and auction.status == AuctionStatus.NOT_STARTED:
            await self.auction_repository.delete(auction)

    async def create_roster(self, roster: Roster) -> Roster:
        roster = await self.roster_repository.save(roster)
        await self._discard_auction_before_start(roster)
        return roster

    async def create_rosters(self, rosters: List[Roster]) -> List[Roster]:
        rosters = await self.roster_repository.save_all(rosters)
        if rosters:
            await self._discard_auction_before_start(rosters[0])
        return rosters

    async def rename_roster(self, roster: Roster, name: str) -> Roster:
        roster.name = name
        roster = await self.roster_repository.save(roster)
        auction = await self._get_auction(roster)
        if auction:
            participant = await self.auction_participant_repository.get_by_roster_id_and_auction_id(
                roster.id, auction.id
            )
            if participant and participant.name != roster.name:
                participant.name = roster.name
                await self.auction_participant_repository.save(participant)
        return roster

    async def delete_roster(self, roster: Roster) -> None:
        auction = await self._get_auction(roster)
        if auction:
            if auction.status == AuctionStatus.NOT_STARTED:
                await self.auction_repository.delete(auction)
            else:
                participant = await self.auction_participant_repository.get_by_roster_id_and_auction_id(
                    roster.id, auction.id
                )
                if participant:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Cannot delete a roster that is part of an auction that has started",
                    )
        await self.roster_repository.delete(roster)


def get_roster_service(
    roster_repository: RosterRepository = Depends(get_roster_repository),
    auction_repository: AuctionRepository = Depends(get_auction_repository),
    auction_participant_repository: AuctionParticipantRepository = Depends(get_auction_participant_repository),
) -> RosterService:
    return RosterService(roster_repository, auction_repository, auction_participant_repository)
