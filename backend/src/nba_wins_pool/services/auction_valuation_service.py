"""Service for fetching and calculating auction valuation data based on betting odds."""

import logging
from dataclasses import dataclass
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
from nba_wins_pool.utils.projections import fanduel_blend_weight

logger = logging.getLogger(__name__)


# Expected postseason wins from the odds (the pool counts playoff and play-in wins):
#   playoff wins = playoff_odds * P(make playoffs) + conf_odds * P(win conference)
#   play-in wins = play_in_odds * P(make playoffs) * (1 - P(make playoffs))
# plus title_odds * P(win title), which only the 2021-22 formula used.
@dataclass(frozen=True)
class PostseasonWinCoefficients:
    playoff_odds: float
    conf_odds: float
    play_in_odds: float = 0.0
    title_odds: float = 0.0


# Keyed by the first season each fit applies to. A season uses the latest fit keyed at or
# before it (seasons before the first key use the first). Add a fit for the upcoming season
# with backend/refit/playoff_wins_regression.py --write.
POSTSEASON_WIN_COEFFICIENTS: dict[str, PostseasonWinCoefficients] = {
    # Used for the 2021-22 auction; the only formula with a title term.
    "2021-22": PostseasonWinCoefficients(playoff_odds=4.0, conf_odds=12.0, title_odds=16.0),
    # Used for the 2022-23 through 2024-25 auctions; play-in wins not modeled.
    "2022-23": PostseasonWinCoefficients(playoff_odds=2.7086, conf_odds=20.5616),
    # Notebook fit: Jan 1 futures, proportionally de-vigged, playoff wins only (bbref)
    # 2014-15 through 2024-25; play-in wins not modeled.
    "2025-26": PostseasonWinCoefficients(playoff_odds=2.7828, conf_odds=19.7734),
    # playoff_wins_regression.py: preseason odds, Shin de-vigged, NNLS. Playoff 2014-15..2025-26 (n=359, R² 0.375); play-in 2020-21..2025-26 (n=180, R² 0.015)
    "2026-27": PostseasonWinCoefficients(playoff_odds=3.4795, conf_odds=14.6337, play_in_odds=1.3173),
}


def postseason_win_coefficients(season: Optional[str]) -> PostseasonWinCoefficients:
    """The postseason-win coefficients in effect for *season* (the newest fit if None)."""
    keys = sorted(POSTSEASON_WIN_COEFFICIENTS)
    if season is None:
        return POSTSEASON_WIN_COEFFICIENTS[keys[-1]]
    in_effect = [k for k in keys if k <= season]
    return POSTSEASON_WIN_COEFFICIENTS[in_effect[-1] if in_effect else keys[0]]


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
        3. Compute expected wins: reg_season_wins + expected playoff wins (make_playoffs_prob * coef +
           conf_prob * coef) + expected play-in wins (make_playoffs_prob * (1 - make_playoffs_prob) * coef),
           with the season's coefficients from POSTSEASON_WIN_COEFFICIENTS.
        """
        fd_projs = await self.nba_projections_repository.get_projections(
            season=season, projection_date=projection_date, source="fanduel"
        )
        espn_projs = await self.nba_projections_repository.get_projections(
            season=season, projection_date=projection_date, source="espn_bpi"
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
        espn_wins_map = {p.team_id: p.reg_season_wins for p in espn_projs}
        teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        team_map = {t.id: t for t in teams}

        # The projections' own season, so a None (current) season still gets its era's fit
        coefficients = postseason_win_coefficients(fd_projs[0].season)
        results = []
        for p in fd_projs:
            # Calculate weighting based on recency
            fd_date = p.projection_date if p.projection_date else date.today()
            fd_weight = fanduel_blend_weight(fd_date, date.today())

            # Fill missing FanDuel make_playoffs_prob with ESPN value
            make_playoffs_prob = p.make_playoffs_prob
            if make_playoffs_prob is None:
                make_playoffs_prob = espn_map.get(p.team_id)

            # Blended regular season wins
            fd_reg_wins = p.reg_season_wins or 0.0
            espn_reg_wins = espn_wins_map.get(p.team_id)

            if espn_reg_wins is not None:
                blended_reg_wins = (fd_reg_wins * fd_weight) + (espn_reg_wins * (1.0 - fd_weight))
            else:
                blended_reg_wins = fd_reg_wins

            # Use defaults of 0 for probabilities if still None
            make_playoffs_prob = make_playoffs_prob or 0.0
            win_conference_prob = p.win_conference_prob or 0.0
            win_title_prob = p.win_finals_prob or 0.0

            # Compute expected wins
            expected_wins = (
                blended_reg_wins
                + (make_playoffs_prob * coefficients.playoff_odds)
                + (win_conference_prob * coefficients.conf_odds)
                + (make_playoffs_prob * (1.0 - make_playoffs_prob) * coefficients.play_in_odds)
                + (win_title_prob * coefficients.title_odds)
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
                    "reg_season_wins": blended_reg_wins,
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
        min_bid_increment: float = 1.0,
    ) -> AuctionValuationData:
        """Calculate auction valuation values based on value over replacement of expected wins.

        Values are rounded to the nearest dollar, and no team is valued below the minimum bid increment.
        """
        df, projection_date, source = await self.get_expected_wins(season, projection_date)

        if df.empty:
            raise HTTPException(status_code=404, detail="No expected wins data found for season")

        total_budget = float(num_participants * budget_per_participant)
        total_drafted_teams = num_participants * teams_per_participant

        replacement_level = df["expected_wins"].nlargest(total_drafted_teams).min()

        value_over_replacement = df["expected_wins"] - replacement_level
        total_value_over_replacement = value_over_replacement.nlargest(total_drafted_teams).sum()

        df["auction_value"] = (value_over_replacement / total_value_over_replacement) * total_budget
        df["auction_value"] = df["auction_value"].round(0).clip(lower=min_bid_increment)
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
            min_bid_increment=float(auction.min_bid_increment),
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
