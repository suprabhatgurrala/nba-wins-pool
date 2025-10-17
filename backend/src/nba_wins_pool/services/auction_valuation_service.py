"""Service for fetching and calculating auction valuation data based on betting odds."""

import asyncio
import logging
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import requests
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.auction_valuation import AuctionValuationData, TeamValuation
from nba_wins_pool.models.external_data import DataFormat, ExternalData
from nba_wins_pool.models.team import LeagueSlug
from nba_wins_pool.repositories.auction_participant_repository import (
    AuctionParticipantRepository,
)
from nba_wins_pool.repositories.auction_repository import AuctionRepository
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.team_repository import TeamRepository

logger = logging.getLogger(__name__)

# Constants for odds parsing
MAKE_PLAYOFFS_SUFFIX = "To Make Playoffs"
REG_SEASON_WINS_SUFFIX = "Regular Season Wins"

# Linear regression coefficients for playoff wins estimation
PLAYOFF_ODDS_COEFFICIENT = 2.7828
CONF_ODDS_COEFFICIENT = 19.7734

# Cache configuration
FANDUEL_ODDS_TTL = 60 * 60  # 1 hour cache
FANDUEL_ODDS_CACHE_KEY = "fanduel:nba_odds"

# FanDuel team name to NBA tricode mapping (handles naming variations)
FANDUEL_TO_TRICODE = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}


class AuctionValuationService:
    """Service for calculating auction valuations based on FanDuel odds.
    
    Fetches odds from FanDuel's API, calculates expected wins, and computes
    auction values using value-over-replacement methodology.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        external_data_repository: ExternalDataRepository,
        team_repository: TeamRepository,
        auction_repository: AuctionRepository,
        auction_participant_repository: AuctionParticipantRepository,
    ):
        self.db_session = db_session
        self.external_data_repository = external_data_repository
        self.team_repository = team_repository
        self.auction_repository = auction_repository
        self.auction_participant_repository = auction_participant_repository

    async def get_valuation_data_for_auction(self, auction_id) -> AuctionValuationData:
        """Get auction valuation data for a specific auction.
        
        Fetches the auction configuration and calculates valuations based on:
        - Number of participants (from auction_participants table)
        - Budget per participant (from auction.starting_participant_budget)
        - Teams per participant (from auction.max_lots_per_participant)
        
        Args:
            auction_id: UUID of the auction
            
        Returns:
            AuctionValuationData with team valuations and metadata
            
        Raises:
            HTTPException: If auction not found or has no participants
        """
        # Get auction configuration
        auction = await self.auction_repository.get_by_id(auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")
        
        # Count participants
        participants = await self.auction_participant_repository.get_all_by_auction_id(auction_id)
        num_participants = len(participants)
        
        if num_participants == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot calculate valuations: auction has no participants"
            )
        
        # Calculate valuations using auction configuration
        return await self.get_valuation_data(
            num_participants=num_participants,
            budget_per_participant=int(auction.starting_participant_budget),
            teams_per_participant=auction.max_lots_per_participant,
        )

    async def get_valuation_data(
        self,
        num_participants: int,
        budget_per_participant: int | float,
        teams_per_participant: int,
    ) -> AuctionValuationData:
        """Get auction valuation data with caching.
        
        Args:
            num_participants: Number of auction participants
            budget_per_participant: Budget allocated to each participant
            teams_per_participant: Number of teams each participant will draft
            
        Returns:
            AuctionValuationData with team valuations and metadata
        """
        # Get cached odds data
        odds_data, cached_at = await self._get_odds_cached()
        
        # Calculate valuations
        df = await self._calculate_valuations(
            odds_data,
            num_participants,
            budget_per_participant,
            teams_per_participant,
        )
        
        # Convert to response model
        team_valuations = [
            TeamValuation(**row)
            for row in df.to_dict(orient="records")
        ]
        
        return AuctionValuationData(
            data=team_valuations,
            num_participants=num_participants,
            budget_per_participant=int(budget_per_participant),
            teams_per_participant=teams_per_participant,
            cached_at=cached_at.isoformat(),
        )

    async def _get_odds_cached(self) -> tuple[dict, datetime]:
        """Get odds data with caching.
        
        Returns:
            Tuple of (odds_data, cached_at timestamp)
        """
        # Try to get from cache
        cached = await self.external_data_repository.get_by_key(FANDUEL_ODDS_CACHE_KEY)
        if cached and self._is_cache_valid(cached.updated_at, FANDUEL_ODDS_TTL):
            logger.debug("FanDuel odds cache hit")
            return cached.data_json, cached.updated_at
        
        # Fetch fresh data from FanDuel API
        now = datetime.now(UTC)
        try:
            logger.info("Fetching fresh FanDuel odds data")
            odds_data = await asyncio.to_thread(self._fetch_fanduel_odds)
            
            # Store in database
            await self._store_odds(odds_data)
            
            return odds_data, now
        except Exception as e:
            logger.error(f"Failed to fetch FanDuel odds: {e}")
            # Return stale data if available
            if cached:
                logger.warning(f"Returning stale odds data from {cached.updated_at}")
                return cached.data_json, cached.updated_at
            raise

    def _fetch_fanduel_odds(self) -> dict:
        """Fetch NBA odds from FanDuel's sportsbook API.
        
        Returns:
            Dict containing parsed odds data for all teams
        """
        url = "https://api.sportsbook.fanduel.com/sbapi/content-managed-page"
        
        params = {
            "page": "CUSTOM",
            "customPageId": "nba",
            "pbHorizontal": "false",
            "_ak": "FhMFpcPWXMeyZxOx",
            "timezone": "America/New_York",
        }
        
        headers = {
            "X-Sportsbook-Region": "NJ",
            "sec-ch-ua-platform": '"Windows"',
            "Referer": "https://sportsbook.fanduel.com/",
            "sec-ch-ua": '"Not;A=Brand";v="99", "Brave";v="139", "Chromium";v="139"',
            "sec-ch-ua-mobile": "?0",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Parse the response
        odds_response = response.json()
        return self._parse_fanduel_response(odds_response)

    def _parse_fanduel_response(self, odds_response: dict) -> dict:
        """Parse FanDuel API response into structured odds data.
        
        Args:
            odds_response: Raw response from FanDuel API
            
        Returns:
            Dict with parsed odds data by team
        """
        markets = odds_response.get("attachments", {}).get("markets", {})
        
        playoffs_data = []
        reg_season_wins_data = []
        conf_data = []
        title_data = []
        
        for market in markets.values():
            market_type = market["marketType"]
            
            if market_type == "NBA_REGULAR_SEASON_WINS_SGP":
                reg_season_wins_data.append(self._parse_reg_season_wins(market))
            elif market_type == "NBA_TO_MAKE_PLAYOFFS":
                playoffs_data.append(self._parse_playoff_odds(market))
            elif market_type == "NBA_CONFERENCE_WINNER":
                conf_data.extend(self._parse_conference_odds(market))
            elif market_type == "NBA_CHAMPIONSHIP":
                title_data.extend(self._parse_title_odds(market))
        
        return {
            "playoffs": playoffs_data,
            "reg_season_wins": reg_season_wins_data,
            "conference": conf_data,
            "title": title_data,
        }

    def _parse_playoff_odds(self, market: dict) -> dict:
        """Parse playoff odds from a FanDuel market.
        
        Args:
            market: Market dict from FanDuel API
            
        Returns:
            Dict with team and playoff odds
        """
        yes_odds = None
        no_odds = None
        
        for runner in market["runners"]:
            odds = runner["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"]
            if runner["runnerName"] == "Yes":
                yes_odds = odds
            elif runner["runnerName"] == "No":
                no_odds = odds
        
        return {
            "team": market["marketName"].split(MAKE_PLAYOFFS_SUFFIX)[0].strip(),
            "make_playoffs": yes_odds,
            "miss_playoffs": no_odds,
        }

    def _parse_reg_season_wins(self, market: dict) -> dict:
        """Parse regular season win totals from a FanDuel market.
        
        Args:
            market: Market dict from FanDuel API
            
        Returns:
            Dict with team and win total odds
        """
        win_total = None
        over_odds = None
        under_odds = None
        
        for runner in market["runners"]:
            if runner["runnerStatus"] != "ACTIVE":
                continue
            
            name = runner["runnerName"].lower()
            odds = runner["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"]
            win_total_str = name.removesuffix("wins")
            
            if "over" in name:
                win_total_str = win_total_str.removeprefix("over").strip()
                over_odds = odds
            elif "under" in name:
                win_total_str = win_total_str.removeprefix("under").strip()
                under_odds = odds
            
            if win_total is not None:
                assert win_total == float(win_total_str), f"Mismatched win totals: {win_total} vs {win_total_str}"
            else:
                win_total = float(win_total_str)
        
        return {
            "team": market["marketName"].split(REG_SEASON_WINS_SUFFIX)[0].strip(),
            "reg_season_wins": win_total,
            "over_reg_season_wins": over_odds,
            "under_reg_season_wins": under_odds,
        }

    def _parse_conference_odds(self, market: dict) -> list[dict]:
        """Parse conference winner odds from a FanDuel market.
        
        Args:
            market: Market dict from FanDuel API
            
        Returns:
            List of dicts with team and conference odds
        """
        conf = "East" if "east" in market["marketName"].lower() else "West"
        
        return [
            {
                "team": runner["runnerName"],
                "conf_odds": runner["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"],
                "conf": conf,
            }
            for runner in market["runners"]
        ]

    def _parse_title_odds(self, market: dict) -> list[dict]:
        """Parse championship odds from a FanDuel market.
        
        Args:
            market: Market dict from FanDuel API
            
        Returns:
            List of dicts with team and title odds
        """
        return [
            {
                "team": runner["runnerName"],
                "title_odds": runner["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"],
            }
            for runner in market["runners"]
        ]

    async def _calculate_valuations(
        self,
        odds_data: dict,
        num_participants: int,
        budget_per_participant: int | float,
        teams_per_participant: int,
    ) -> pd.DataFrame:
        """Calculate auction valuations from odds data.
        
        Args:
            odds_data: Parsed odds data from FanDuel
            num_participants: Number of auction participants
            budget_per_participant: Budget per participant
            teams_per_participant: Teams per participant
            
        Returns:
            DataFrame with team valuations
        """
        # Fetch NBA teams from database
        nba_teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        
        # Create mapping from abbreviation (tricode) to Team model
        team_by_abbrev = {team.abbreviation: team for team in nba_teams}
        logger.info(f"Loaded {len(nba_teams)} teams from database")
        
        # Convert to DataFrames
        playoffs_df = pd.DataFrame(odds_data["playoffs"]).set_index("team")
        reg_season_df = pd.DataFrame(odds_data["reg_season_wins"]).set_index("team")
        conf_df = pd.DataFrame(odds_data["conference"]).set_index("team")
        title_df = pd.DataFrame(odds_data["title"]).set_index("team")
        
        # Combine all data
        df = pd.concat([playoffs_df, reg_season_df, conf_df, title_df], axis=1)
        
        # Add logo URLs and team IDs from database using tricode lookup
        def get_logo_url(fanduel_name: str) -> str | None:
            """Get team logo URL from database using FanDuel name -> tricode -> Team lookup."""
            tricode = FANDUEL_TO_TRICODE.get(fanduel_name)
            if not tricode:
                logger.warning(f"No tricode mapping for FanDuel team: {fanduel_name}")
                return None
            
            team = team_by_abbrev.get(tricode)
            if team:
                return team.logo_url
            
            logger.warning(f"Team not found in database for tricode: {tricode}")
            return None
        
        def get_team_id(fanduel_name: str) -> str | None:
            """Get team ID from database using FanDuel name -> tricode -> Team lookup."""
            tricode = FANDUEL_TO_TRICODE.get(fanduel_name)
            if not tricode:
                return None
            
            team = team_by_abbrev.get(tricode)
            if team:
                return str(team.id)
            
            return None
        
        df["logo_url"] = df.index.map(get_logo_url)
        df["team_id"] = df.index.map(get_team_id)
        
        # Calculate probabilities
        df = self._calculate_probabilities(df)
        
        # Calculate auction values
        df = self._calculate_auction_values(
            df,
            num_participants,
            budget_per_participant,
            teams_per_participant,
        )
        
        # Clean up and prepare for response
        # Reset index to make 'team' a column (it's currently the index with FanDuel names)
        # The index was named 'team' when we did set_index("team"), so reset_index preserves that name
        df = df.reset_index()
        
        # Rename 'index' column to 'team' if it exists (pandas sometimes does this)
        if 'index' in df.columns and 'team' not in df.columns:
            df = df.rename(columns={'index': 'team'})
        
        df = df.replace({np.nan: None})
        
        return df

    def _calculate_probabilities(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate probabilities from decimal odds.
        
        Args:
            df: DataFrame with odds data
            
        Returns:
            DataFrame with added probability columns
        """
        # Playoff probabilities (vig-adjusted)
        df["make_playoffs_prob"] = self._get_vig_adjusted_probabilities(
            df["make_playoffs"], df["miss_playoffs"]
        )
        
        # Regular season win probabilities (vig-adjusted)
        df["over_reg_season_wins_prob"] = self._get_vig_adjusted_probabilities(
            df["over_reg_season_wins"], df["under_reg_season_wins"]
        )
        
        # Conference probabilities (normalized within conference)
        east_conf_sum = (1 / df.where(df["conf"] == "East")["conf_odds"]).sum()
        west_conf_sum = (1 / df.where(df["conf"] == "West")["conf_odds"]).sum()
        df["conf_prob"] = np.where(
            df["conf"] == "East",
            (1 / df["conf_odds"]) / east_conf_sum,
            (1 / df["conf_odds"]) / west_conf_sum,
        )
        
        # Title probabilities (normalized across all teams)
        raw_title_prob = 1 / df["title_odds"]
        df["title_prob"] = raw_title_prob / raw_title_prob.sum()
        
        # Calculate total expected wins
        df["total_expected_wins"] = (
            df["reg_season_wins"]
            + (df["make_playoffs_prob"] * PLAYOFF_ODDS_COEFFICIENT)
            + (df["conf_prob"] * CONF_ODDS_COEFFICIENT)
        )
        
        return df.sort_values(by="total_expected_wins", ascending=False)

    def _get_vig_adjusted_probabilities(
        self,
        outcome_a: pd.Series,
        outcome_b: pd.Series,
        vig: float = 0.02,
    ) -> pd.Series:
        """Convert decimal odds to vig-adjusted probabilities.
        
        Args:
            outcome_a: Decimal odds for outcome A
            outcome_b: Decimal odds for outcome B
            vig: Bookmaker's margin (default 2%)
            
        Returns:
            Series with adjusted probabilities for outcome A
        """
        raw_prob_a = 1 / outcome_a
        raw_prob_b = 1 / outcome_b
        total_raw_prob = (raw_prob_a + raw_prob_b).fillna(1 + vig)
        raw_prob_a = raw_prob_a.fillna(total_raw_prob - raw_prob_b)
        return raw_prob_a / total_raw_prob

    def _calculate_auction_values(
        self,
        df: pd.DataFrame,
        num_participants: int,
        budget_per_participant: int | float,
        teams_per_participant: int,
    ) -> pd.DataFrame:
        """Calculate auction values using value-over-replacement.
        
        Args:
            df: DataFrame with expected wins
            num_participants: Number of auction participants
            budget_per_participant: Budget per participant
            teams_per_participant: Teams per participant
            
        Returns:
            DataFrame with auction_value column added
        """
        # Convert to float to handle Decimal types from database
        total_budget = float(num_participants * budget_per_participant)
        total_drafted_teams = num_participants * teams_per_participant
        
        # Determine replacement level (worst team that gets drafted)
        replacement_level = df["total_expected_wins"].nlargest(total_drafted_teams).min()
        
        # Calculate value over replacement
        value_over_replacement = df["total_expected_wins"] - replacement_level
        total_value_over_replacement = value_over_replacement.nlargest(total_drafted_teams).sum()
        
        # Allocate budget proportionally to value over replacement
        df["auction_value"] = (value_over_replacement / total_value_over_replacement) * total_budget
        
        # Ensure minimum value of $1 and round to whole dollars
        df["auction_value"] = df["auction_value"].clip(lower=1).round(0)
        
        return df

    def _is_cache_valid(self, updated_at: datetime, ttl_seconds: int) -> bool:
        """Check if cached data is still valid based on TTL.
        
        Args:
            updated_at: When the cache was last updated
            ttl_seconds: Time-to-live in seconds
            
        Returns:
            True if cache is still valid
        """
        now = datetime.now(UTC)
        # Ensure updated_at is timezone-aware
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        age_seconds = (now - updated_at).total_seconds()
        return age_seconds < ttl_seconds

    async def _store_odds(self, odds_data: dict) -> None:
        """Store odds data in database cache.
        
        Args:
            odds_data: Parsed odds data to store
        """
        existing = await self.external_data_repository.get_by_key(FANDUEL_ODDS_CACHE_KEY)
        if existing:
            existing.data_json = odds_data
            await self.external_data_repository.update(existing)
            logger.debug("Updated FanDuel odds cache")
        else:
            external_data = ExternalData(
                key=FANDUEL_ODDS_CACHE_KEY,
                data_format=DataFormat.JSON,
                data_json=odds_data,
            )
            await self.external_data_repository.save(external_data)
            logger.debug("Created FanDuel odds cache")

    # Public method for background jobs
    async def update_odds(self):
        """Fetch and cache FanDuel odds data (called by background job).
        
        This method is designed to be called by the scheduler. It fetches
        the latest odds data and caches it in the database.
        """
        odds_data, _ = await self._get_odds_cached()
        logger.info(f"FanDuel odds updated: {len(odds_data.get('title', []))} teams")


# Dependency injection
def get_auction_valuation_service(
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
        external_data_repository=ExternalDataRepository(db_session),
        team_repository=TeamRepository(db_session),
        auction_repository=AuctionRepository(db_session),
        auction_participant_repository=AuctionParticipantRepository(db_session),
    )
