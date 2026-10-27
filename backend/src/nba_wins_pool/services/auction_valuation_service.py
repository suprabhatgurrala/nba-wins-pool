"""Service for fetching and calculating auction valuation data based on betting odds."""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import Depends, HTTPException
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.auction_valuation import AuctionValuationData, TeamValuation
from nba_wins_pool.models.projection import ProjectionMarket
from nba_wins_pool.models.team import LeagueSlug, Team
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
from nba_wins_pool.repositories.pool_season_repository import (
    PoolSeasonRepository,
    get_pool_season_repository,
)
from nba_wins_pool.repositories.projection_repository import (
    DRAFTKINGS,
    ESPN_BPI,
    FANDUEL,
    LatestQuote,
    ProjectionRepository,
    get_projection_repository,
    quotes_by_team,
)
from nba_wins_pool.repositories.team_repository import (
    TeamRepository,
    get_team_repository,
)
from nba_wins_pool.services.nba_data_service import NbaDataService, get_nba_data_service
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.projections import fanduel_blend_weight
from nba_wins_pool.utils.time import utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PostseasonWinCoefficients:
    playoff_odds: float
    conf_odds: float
    play_in_odds: float = 0.0
    title_odds: float = 0.0


POSTSEASON_WIN_COEFFICIENTS: dict[str, PostseasonWinCoefficients] = {
    "2021-22": PostseasonWinCoefficients(playoff_odds=4.0, conf_odds=12.0, title_odds=16.0),
    "2022-23": PostseasonWinCoefficients(playoff_odds=2.7086, conf_odds=20.5616),
    "2025-26": PostseasonWinCoefficients(playoff_odds=2.7828, conf_odds=19.7734),
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
        projection_repository: ProjectionRepository,
        pool_season_repository: PoolSeasonRepository,
        nba_data_service: Optional[NbaDataService] = None,
    ):
        self.db_session = db_session
        self.nba_data_service = nba_data_service
        self.external_data_repository = external_data_repository
        self.team_repository = team_repository
        self.auction_repository = auction_repository
        self.auction_participant_repository = auction_participant_repository
        self.projection_repository = projection_repository
        self.pool_season_repository = pool_season_repository

    async def get_expected_wins(
        self,
        season: SeasonStr,
        as_of: Optional[datetime] = None,
        teams: Optional[list[Team]] = None,
    ) -> tuple[pd.DataFrame, datetime, str]:
        """Calculate expected wins for each team in the given season.

        Each market is read on its own: the team's latest quote at or before ``as_of`` (if given).

        1. FanDuel teams with a win line (DraftKings for seasons that only have it).
        2. Missing make-playoffs probabilities come from ESPN BPI; ESPN's projected wins blend with the line as
           it ages (:func:`fanduel_blend_weight`).
        3. Expected wins: blended regular-season wins + make_playoffs_prob * coef + conf_prob * coef + expected
           play-in wins (make_playoffs_prob * (1 - make_playoffs_prob) * coef) + title_prob * coef, with the
           season's coefficients from POSTSEASON_WIN_COEFFICIENTS.

        Pass the NBA ``teams`` when the caller already loaded them, to skip loading them again.
        """
        book_markets = [
            ProjectionMarket.WIN_TOTAL,
            ProjectionMarket.MAKE_PLAYOFFS,
            ProjectionMarket.WIN_CONF,
            ProjectionMarket.WIN_TITLE,
        ]
        source = FANDUEL
        book = await self._quotes_with_win_line(season, source, book_markets, as_of)
        if not book:
            logger.warning(f"No FanDuel projections found for season {season}, trying DraftKings")
            source = DRAFTKINGS
            book = await self._quotes_with_win_line(season, source, book_markets, as_of)
            if not book:
                logger.warning(f"No projections found for season {season}")
                return pd.DataFrame(), utc_now(), "unknown"

        espn = quotes_by_team(
            await self.projection_repository.get_latest_quotes(
                season, ESPN_BPI, [ProjectionMarket.ESPN_WINS, ProjectionMarket.MAKE_PLAYOFFS], as_of
            )
        )
        if teams is None:
            teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        team_by_abbrev = {t.abbreviation: t for t in teams}

        coefficients = postseason_win_coefficients(season)
        reference_date = as_of.date() if as_of else date.today()
        results = []
        for tricode, quotes in book.items():
            line = quotes[ProjectionMarket.WIN_TOTAL]
            fd_weight = fanduel_blend_weight(line.fetched_at.date(), reference_date)

            def prob(market: ProjectionMarket, quotes=quotes) -> Optional[float]:
                quote = quotes.get(market)
                return quote.prob if quote else None

            make_playoffs_prob = prob(ProjectionMarket.MAKE_PLAYOFFS)
            espn_quotes = espn.get(tricode, {})
            if make_playoffs_prob is None and ProjectionMarket.MAKE_PLAYOFFS in espn_quotes:
                make_playoffs_prob = espn_quotes[ProjectionMarket.MAKE_PLAYOFFS].prob

            espn_wins = espn_quotes.get(ProjectionMarket.ESPN_WINS)
            if espn_wins is not None:
                blended_reg_wins = line.line * fd_weight + espn_wins.line * (1.0 - fd_weight)
            else:
                blended_reg_wins = line.line

            make_playoffs_prob = make_playoffs_prob or 0.0
            win_conference_prob = prob(ProjectionMarket.WIN_CONF) or 0.0
            win_title_prob = prob(ProjectionMarket.WIN_TITLE) or 0.0

            expected_wins = (
                blended_reg_wins
                + (make_playoffs_prob * coefficients.playoff_odds)
                + (win_conference_prob * coefficients.conf_odds)
                + (make_playoffs_prob * (1.0 - make_playoffs_prob) * coefficients.play_in_odds)
                + (win_title_prob * coefficients.title_odds)
            )

            team = team_by_abbrev.get(tricode)
            results.append(
                {
                    "team_id": line.team_id,
                    "team_name": team.name if team else tricode,
                    "season": season,
                    "source": source,
                    "fetched_at": max(q.fetched_at for q in quotes.values()),
                    "reg_season_wins": blended_reg_wins,
                    "over_wins_prob": line.prob,
                    "make_playoffs_prob": make_playoffs_prob,
                    "win_conference_prob": prob(ProjectionMarket.WIN_CONF),
                    "win_finals_prob": prob(ProjectionMarket.WIN_TITLE),
                    "expected_wins": expected_wins,
                    "logo_url": team.logo_url if team else None,
                    "conference": team.conference if team else None,
                    "abbreviation": tricode,
                }
            )

        df = pd.DataFrame(results).sort_values(by="expected_wins", ascending=False)
        return df, df["fetched_at"].max().to_pydatetime(), source

    async def _quotes_with_win_line(
        self, season: SeasonStr, source: str, markets: list[ProjectionMarket], as_of: Optional[datetime]
    ) -> dict[str, dict[ProjectionMarket, LatestQuote]]:
        """Latest quotes by tricode and market, for the teams with a win line from *source*."""
        quotes = quotes_by_team(await self.projection_repository.get_latest_quotes(season, source, markets, as_of))
        return {
            tricode: by_market
            for tricode, by_market in quotes.items()
            if ProjectionMarket.WIN_TOTAL in by_market and by_market[ProjectionMarket.WIN_TOTAL].line is not None
        }

    async def get_valuation_data(
        self,
        season: SeasonStr,
        num_participants: int,
        budget_per_participant: int,
        teams_per_participant: int,
        as_of: Optional[datetime] = None,
        min_bid_increment: float = 1.0,
    ) -> AuctionValuationData:
        """Calculate auction valuation values based on value over replacement of expected wins.

        Values are rounded to the nearest dollar, and no team is valued below the minimum bid increment.
        """
        df, projection_fetched_at, source = await self.get_expected_wins(season, as_of)

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
            projection_fetched_at=projection_fetched_at,
            source=source,
        )

    async def get_valuation_data_for_auction(self, auction_id, include_records: bool = False) -> AuctionValuationData:
        """Valuations for an auction, with records as of the projection date when ``include_records``."""
        # Get auction configuration
        auction = await self.auction_repository.get_by_id(auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")

        participants = await self.auction_participant_repository.get_all_by_auction_id(auction_id)
        num_participants = len(participants)

        if num_participants == 0:
            raise HTTPException(status_code=400, detail="Cannot calculate valuations: auction has no participants")

        pool_season = await self.pool_season_repository.get_by_pool_and_season(auction.pool_id, auction.season)
        as_of = pool_season.auction_projection_date if pool_season else None

        valuation = await self.get_valuation_data(
            season=auction.season,
            num_participants=num_participants,
            budget_per_participant=int(auction.starting_participant_budget),
            teams_per_participant=auction.max_lots_per_participant,
            as_of=as_of,
            min_bid_increment=float(auction.min_bid_increment),
        )
        if include_records:
            await self._add_records(valuation, auction.season, as_of or auction.completed_at or utc_now())
        return valuation

    async def _add_records(self, valuation: AuctionValuationData, season: SeasonStr, as_of: datetime) -> None:
        """Fills in each team's wins and losses from games completed by ``as_of``; left empty before any are."""
        if self.nba_data_service is None:
            return
        try:
            games = await self.nba_data_service.get_game_data(season)
        except Exception:
            logger.exception("Failed to load games for %s; auction valuations omit records", season)
            return
        if games.empty:
            return
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        completed = games[(games["status"] == NBAGameStatus.FINAL) & (games["date_time"] <= cutoff)]
        if completed.empty:
            return
        wins = completed["winning_team"].dropna().astype(int).value_counts()
        losses = completed["losing_team"].dropna().astype(int).value_counts()
        teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        external_id_by_team_id = {t.id: int(t.external_id) for t in teams}
        for team in valuation.data:
            external_id = external_id_by_team_id.get(team.team_id)
            if external_id is None:
                continue
            team.wins = int(wins.get(external_id, 0))
            team.losses = int(losses.get(external_id, 0))


# Dependency injection
def get_auction_valuation_service(
    external_data_repository: ExternalDataRepository = Depends(get_external_data_repository),
    team_repository: TeamRepository = Depends(get_team_repository),
    auction_repository: AuctionRepository = Depends(get_auction_repository),
    auction_participant_repository: AuctionParticipantRepository = Depends(get_auction_participant_repository),
    projection_repository: ProjectionRepository = Depends(get_projection_repository),
    pool_season_repository: PoolSeasonRepository = Depends(get_pool_season_repository),
    db_session: AsyncSession = Depends(get_db_session),
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
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
        projection_repository=projection_repository,
        pool_season_repository=pool_season_repository,
        nba_data_service=nba_data_service,
    )
