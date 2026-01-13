"""Service for fetching and calculating auction valuation data based on betting odds."""

import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import Depends, HTTPException
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.auction_valuation import AuctionValuationData, TeamValuation
from nba_wins_pool.models.team import LeagueSlug
from nba_wins_pool.repositories.auction_participant_repository import (
    AuctionParticipantRepository,
    get_auction_participant_repository,
)
from nba_wins_pool.repositories.auction_repository import (
    AuctionRepository,
    get_auction_repository,
)
from nba_wins_pool.repositories.external_data_repository import (
    ExternalDataRepository,
    get_external_data_repository,
)
from nba_wins_pool.repositories.nba_projections_repository import (
    NBAProjectionsRepository,
    get_nba_projections_repository,
)
from nba_wins_pool.repositories.pool_season_repository import (
    PoolSeasonRepository,
    get_pool_season_repository,
)
from nba_wins_pool.repositories.team_repository import (
    TeamRepository,
    get_team_repository,
)
from nba_wins_pool.types.season_str import SeasonStr

logger = logging.getLogger(__name__)


# Linear regression coefficients for playoff wins estimation
PLAYOFF_ODDS_COEFFICIENT = 2.7828
CONF_ODDS_COEFFICIENT = 19.7734


class AuctionValuationService:
    """Service for calculating auction valuations based on projections."""

    def __init__(
        self,
        db_session: AsyncSession,
        external_data_repository: ExternalDataRepository,
        team_repository: TeamRepository,
        auction_repository: AuctionRepository,
        auction_participant_repository: AuctionParticipantRepository,
        nba_projections_repository: NBAProjectionsRepository,
        pool_season_repository: PoolSeasonRepository,
    ):
        self.db_session = db_session
        self.external_data_repository = external_data_repository
        self.team_repository = team_repository
        self.auction_repository = auction_repository
        self.auction_participant_repository = auction_participant_repository
        self.nba_projections_repository = nba_projections_repository
        self.pool_season_repository = pool_season_repository

    async def get_expected_wins(
        self, season: Optional[SeasonStr] = None, projection_date: Optional[date] = None
    ) -> tuple[pd.DataFrame, date, str]:
        """Calculate expected wins for each team in the given season.

        Logic:
        1. Uses most recently fetched FanDuel projections.
        2. Fill missing 'make_playoffs_prob' values with most recently fetched ESPN projections.
        3. Compute expected wins: reg_season_wins + (make_playoffs_prob * coef) + (conf_prob * coef).
        """
        fd_projs = await self.nba_projections_repository.get_projections(
            season=season, projection_date=projection_date, source="fanduel"
        )
        espn_projs = await self.nba_projections_repository.get_projections(
            season=season, projection_date=projection_date, source="espn"
        )

        if not fd_projs:
            logger.warning(f"No FanDuel projections found for season {season}, trying DraftKings")
            fd_projs = await self.nba_projections_repository.get_projections(
                season=season, projection_date=projection_date, source="draftkings"
            )
            if not fd_projs:
                logger.warning(f"No projections found for season {season}")
                return pd.DataFrame(), date.today(), "unknown"

        # Create mappings for quick lookup
        espn_map = {p.team_id: p.make_playoffs_prob for p in espn_projs}
        teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        team_map = {t.id: t for t in teams}

        results = []
        for p in fd_projs:
            # Fill missing FanDuel make_playoffs_prob with ESPN value
            make_playoffs_prob = p.make_playoffs_prob
            if make_playoffs_prob is None:
                make_playoffs_prob = espn_map.get(p.team_id)

            # Use defaults of 0 for probabilities if still None
            make_playoffs_prob = make_playoffs_prob or 0.0
            win_conference_prob = p.win_conference_prob or 0.0
            reg_season_wins = p.reg_season_wins or 0.0

            # Compute expected wins
            expected_wins = (
                reg_season_wins
                + (make_playoffs_prob * PLAYOFF_ODDS_COEFFICIENT)
                + (win_conference_prob * CONF_ODDS_COEFFICIENT)
            )

            # Lookup team info
            team = team_map.get(p.team_id)

            # Combine all data into a row
            row = p.model_dump()
            row.update(
                {
                    "make_playoffs_prob": make_playoffs_prob,
                    "expected_wins": expected_wins,
                    "logo_url": team.logo_url if team else None,
                    "conference": team.conference if team else None,
                    "abbreviation": team.abbreviation if team else None,
                }
            )
            results.append(row)

        df = pd.DataFrame(results).sort_values(by="expected_wins", ascending=False)
        p_date = fd_projs[0].projection_date if fd_projs else date.today()
        p_source = fd_projs[0].source if fd_projs else "unknown"
        return df, p_date, p_source

    async def get_valuation_data(
        self,
        season: SeasonStr,
        num_participants: int,
        budget_per_participant: int,
        teams_per_participant: int,
        projection_date: Optional[date] = None,
    ) -> AuctionValuationData:
        """Calculate auction valuation values based on value over replacement of expected wins."""
        df, projection_date, source = await self.get_expected_wins(season, projection_date)

        if df.empty:
            raise HTTPException(status_code=404, detail="No expected wins data found for season")

        total_budget = float(num_participants * budget_per_participant)
        total_drafted_teams = num_participants * teams_per_participant

        replacement_level = df["expected_wins"].nlargest(total_drafted_teams).min()

        value_over_replacement = df["expected_wins"] - replacement_level
        total_value_over_replacement = value_over_replacement.nlargest(total_drafted_teams).sum()

        df["auction_value"] = (value_over_replacement / total_value_over_replacement) * total_budget
        df["auction_value"] = df["auction_value"].clip(lower=1).round(0)
        df = df.replace(np.nan, None)

        # Convert to TeamValuation objects
        team_valuations = TypeAdapter(list[TeamValuation]).validate_python(df.to_dict(orient="records"))

        return AuctionValuationData(
            data=team_valuations,
            num_participants=num_participants,
            budget_per_participant=budget_per_participant,
            teams_per_participant=teams_per_participant,
            projection_date=projection_date,
            source=source,
        )

    async def get_valuation_data_for_auction(self, auction_id) -> AuctionValuationData:
        # Get auction configuration
        auction = await self.auction_repository.get_by_id(auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")

        participants = await self.auction_participant_repository.get_all_by_auction_id(auction_id)
        num_participants = len(participants)

        if num_participants == 0:
            raise HTTPException(status_code=400, detail="Cannot calculate valuations: auction has no participants")

        pool_season = await self.pool_season_repository.get_by_pool_and_season(auction.pool_id, auction.season)
        projection_date = pool_season.auction_projection_date if pool_season else None

        return await self.get_valuation_data(
            season=auction.season,
            num_participants=num_participants,
            budget_per_participant=int(auction.starting_participant_budget),
            teams_per_participant=auction.max_lots_per_participant,
            projection_date=projection_date,
        )


# Dependency injection
def get_auction_valuation_service(
    external_data_repository: ExternalDataRepository = Depends(get_external_data_repository),
    team_repository: TeamRepository = Depends(get_team_repository),
    auction_repository: AuctionRepository = Depends(get_auction_repository),
    auction_participant_repository: AuctionParticipantRepository = Depends(get_auction_participant_repository),
    nba_projections_repository: NBAProjectionsRepository = Depends(get_nba_projections_repository),
    pool_season_repository: PoolSeasonRepository = Depends(get_pool_season_repository),
    db_session: AsyncSession = Depends(get_db_session),
) -> AuctionValuationService:
    """Get AuctionValuationService instance for dependency injection.

    Args:
        db_session: Database session

    Returns:
        AuctionValuationService instance with injected repositories
    """
    return AuctionValuationService(
        db_session=db_session,
        external_data_repository=external_data_repository,
        team_repository=team_repository,
        auction_repository=auction_repository,
        auction_participant_repository=auction_participant_repository,
        nba_projections_repository=nba_projections_repository,
        pool_season_repository=pool_season_repository,
    )
