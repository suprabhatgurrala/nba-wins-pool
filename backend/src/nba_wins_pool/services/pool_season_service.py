from __future__ import annotations

from dataclasses import dataclass
from typing import List
from uuid import UUID

import pandas as pd
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.team import LeagueSlug
from nba_wins_pool.repositories.pool_season_repository import (
    PoolSeasonRepository,
    get_pool_season_repository,
)
from nba_wins_pool.repositories.roster_repository import (
    RosterRepository,
    get_roster_repository,
)
from nba_wins_pool.repositories.roster_slot_repository import (
    RosterSlotRepository,
    get_roster_slot_repository,
)
from nba_wins_pool.repositories.team_repository import (
    TeamRepository,
    get_team_repository,
)
from nba_wins_pool.types.season_str import SeasonStr


@dataclass
class TeamRosterMappings:
    """Team metadata for efficient pandas operations."""

    teams_df: pd.DataFrame
    """
    DataFrame indexed by team_external_id (int) with columns:
    - roster_name: str - Name of the roster that owns this team
    - auction_price: float | None - Price paid in auction (None if undrafted)
    - logo_url: str - URL to team logo
    - team_name: str - Display name of the team
    - abbreviation: str - Team abbreviation (e.g., 'LAL', 'BOS')
    """

    roster_names: List[str]
    """List of unique roster names in the pool (excluding undrafted)"""


class PoolSeasonService:
    """Service for pool-season-specific operations."""

    def __init__(
        self,
        db_session: AsyncSession,
        pool_season_repository: PoolSeasonRepository,
        roster_repository: RosterRepository,
        roster_slot_repository: RosterSlotRepository,
        team_repository: TeamRepository,
    ):
        self.db_session = db_session
        self.pool_season_repository = pool_season_repository
        self.roster_repository = roster_repository
        self.roster_slot_repository = roster_slot_repository
        self.team_repository = team_repository

    async def get_team_roster_mappings(
        self, pool_id: UUID, season: SeasonStr, undrafted_name: str = "Undrafted"
    ) -> TeamRosterMappings:
        """Build mappings between NBA team external IDs and pool roster metadata.

        Args:
            pool_id: Pool UUID
            season: Season string
            undrafted_name: Name to use for undrafted teams

        Returns:
            TeamRosterMappings containing all team-roster relationship data
        """
        # Fetch rosters for this pool and season
        rosters = await self.roster_repository.get_all(pool_id=pool_id, season=season)
        roster_ids = [r.id for r in rosters]
        roster_name_by_id = {r.id: r.name for r in rosters}
        roster_names = sorted({r.name for r in rosters if r.name != undrafted_name})

        # Fetch roster slots
        if roster_ids:
            roster_slots = await self.roster_slot_repository.get_all_by_roster_id_in(roster_ids)
        else:
            roster_slots = []

        # Fetch all NBA teams
        all_nba_teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        team_by_id = {team.id: team for team in all_nba_teams}

        # Build list of team records
        team_records = []
        drafted_team_ids = set()

        # Add drafted teams with roster and price info
        for slot in roster_slots:
            team = team_by_id.get(slot.team_id)
            if team:
                team_external_id = int(team.external_id)
                drafted_team_ids.add(team_external_id)
                team_records.append(
                    {
                        "team_external_id": team_external_id,
                        "roster_name": roster_name_by_id.get(slot.roster_id, undrafted_name),
                        "auction_price": float(slot.auction_price) if slot.auction_price is not None else None,
                        "logo_url": team.logo_url,
                        "team_name": team.name,
                        "abbreviation": team.abbreviation,
                    }
                )

        # Add undrafted teams
        for team in all_nba_teams:
            team_external_id = int(team.external_id)
            if team_external_id not in drafted_team_ids:
                team_records.append(
                    {
                        "team_external_id": team_external_id,
                        "roster_name": undrafted_name,
                        "auction_price": None,
                        "logo_url": team.logo_url,
                        "team_name": team.name,
                        "abbreviation": team.abbreviation,
                    }
                )

        # Create DataFrame indexed by team_external_id
        # Handle empty case by explicitly defining columns
        if team_records:
            teams_df = pd.DataFrame(team_records).set_index("team_external_id")
        else:
            # Create empty DataFrame with correct schema
            teams_df = pd.DataFrame(
                columns=["team_external_id", "roster_name", "auction_price", "logo_url", "team_name", "abbreviation"]
            ).set_index("team_external_id")

        return TeamRosterMappings(teams_df=teams_df, roster_names=roster_names)


def get_pool_season_service(
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
    roster_repo: RosterRepository = Depends(get_roster_repository),
    roster_slot_repo: RosterSlotRepository = Depends(get_roster_slot_repository),
    team_repo: TeamRepository = Depends(get_team_repository),
    db_session: AsyncSession = Depends(get_db_session),
) -> PoolSeasonService:
    """Dependency to get PoolSeasonService with all required repositories."""
    return PoolSeasonService(
        db_session=db_session,
        pool_season_repository=pool_season_repo,
        roster_repository=roster_repo,
        roster_slot_repository=roster_slot_repo,
        team_repository=team_repo,
    )
