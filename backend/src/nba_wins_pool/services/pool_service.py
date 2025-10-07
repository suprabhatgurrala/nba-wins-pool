from typing import Dict, List
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.pool import (
    Pool,
    PoolOverview,
    PoolRosterOverview,
    PoolRosterSlotOverview,
    PoolRosterTeamOverview,
)
from nba_wins_pool.models.pool_season import PoolSeason
from nba_wins_pool.models.roster import Roster
from nba_wins_pool.models.roster_slot import RosterSlot
from nba_wins_pool.models.team import Team
from nba_wins_pool.repositories.pool_repository import PoolRepository, get_pool_repository
from nba_wins_pool.repositories.pool_season_repository import PoolSeasonRepository, get_pool_season_repository
from nba_wins_pool.repositories.roster_repository import RosterRepository, get_roster_repository
from nba_wins_pool.repositories.roster_slot_repository import RosterSlotRepository, get_roster_slot_repository
from nba_wins_pool.repositories.team_repository import TeamRepository, get_team_repository
from nba_wins_pool.types.season_str import SeasonStr


class PoolService:
    def __init__(
        self,
        db_session: AsyncSession,
        pool_repository: PoolRepository,
        pool_season_repository: PoolSeasonRepository,
        roster_repository: RosterRepository,
        roster_slot_repository: RosterSlotRepository,
        team_repository: TeamRepository,
    ):
        self.db_session = db_session
        self.pool_repository = pool_repository
        self.pool_season_repository = pool_season_repository
        self.roster_repository = roster_repository
        self.roster_slot_repository = roster_slot_repository
        self.team_repository = team_repository

    async def get_pool_season_overview(self, pool_id: UUID, season: SeasonStr) -> PoolOverview:
        pool = await self.pool_repository.get_by_id(pool_id)
        if not pool:
            raise HTTPException(status_code=404, detail="Pool not found")

        # Fetch pool season
        pool_season = await self.pool_season_repository.get_by_pool_and_season(pool_id, season)
        if not pool_season:
            raise HTTPException(status_code=404, detail="Pool season not found")

        rosters = await self.roster_repository.get_all(pool_id=pool_id, season=season)

        roster_ids = [roster.id for roster in rosters]
        roster_slots = await self.roster_slot_repository.get_all_by_roster_id_in(roster_ids)

        team_ids = [slot.team_id for slot in roster_slots]
        teams = await self.team_repository.get_all_by_ids(team_ids)

        return self._build_pool_overview(pool, pool_season, rosters, roster_slots, teams)

    @staticmethod
    def _build_pool_overview(
        pool: Pool, pool_season: PoolSeason, rosters: List[Roster], roster_slots: List[RosterSlot], teams: List[Team]
    ) -> PoolOverview:
        team_lookup = {team.id: team for team in teams}
        slots_by_roster = {}
        for slot in roster_slots:
            if slot.roster_id not in slots_by_roster:
                slots_by_roster[slot.roster_id] = []
            slots_by_roster[slot.roster_id].append(slot)

        # Build roster overviews
        roster_overviews = []
        for roster in rosters:
            roster_slots_for_roster = slots_by_roster.get(roster.id, [])
            roster_overview = PoolService._build_pool_roster_overview(roster, roster_slots_for_roster, team_lookup)
            roster_overviews.append(roster_overview)

        return PoolOverview(
            id=pool.id,
            slug=pool.slug,
            name=pool.name,
            season=pool_season.season,
            description=pool.description,
            rules=pool_season.rules,
            rosters=roster_overviews,
            created_at=pool.created_at,
        )

    @staticmethod
    def _build_pool_roster_overview(
        roster: Roster, roster_slots: List[RosterSlot], team_lookup: Dict[UUID, Team]
    ) -> PoolRosterOverview:
        # Build slot overviews for this roster
        slot_overviews = []
        for slot in roster_slots:
            team = team_lookup.get(slot.team_id)
            if team:  # Only include slots where team exists
                slot_overview = PoolService._build_pool_roster_slot_overview(slot, team)
                slot_overviews.append(slot_overview)

        return PoolRosterOverview(
            id=roster.id, season=roster.season, name=roster.name, slots=slot_overviews, created_at=roster.created_at
        )

    @staticmethod
    def _build_pool_roster_slot_overview(slot: RosterSlot, team: Team) -> PoolRosterSlotOverview:
        team_overview = PoolService._build_pool_team_overview(team)
        return PoolRosterSlotOverview(
            id=slot.id,
            name=team.name,  # Using team name as slot name
            team=team_overview,
            created_at=slot.created_at,
        )

    @staticmethod
    def _build_pool_team_overview(team: Team) -> PoolRosterTeamOverview:
        return PoolRosterTeamOverview(id=team.id, name=team.name, created_at=team.created_at)


def get_pool_service(
    pool_repo: PoolRepository = Depends(get_pool_repository),
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
    roster_repo: RosterRepository = Depends(get_roster_repository),
    roster_slot_repo: RosterSlotRepository = Depends(get_roster_slot_repository),
    team_repo: TeamRepository = Depends(get_team_repository),
    db_session=Depends(get_db_session),
) -> PoolService:
    """Dependency to get PoolService with all required repositories"""
    return PoolService(
        db_session=db_session,
        pool_repository=pool_repo,
        pool_season_repository=pool_season_repo,
        roster_repository=roster_repo,
        roster_slot_repository=roster_slot_repo,
        team_repository=team_repo,
    )
