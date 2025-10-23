import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import requests
from fastapi import Depends
from nba_api.live.nba.endpoints import scoreboard
from nba_api.stats.endpoints import scheduleleaguev2
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.external_data import DataFormat, ExternalData
from nba_wins_pool.repositories.external_data_repository import (
    ExternalDataRepository,
    get_external_data_repository,
)
from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.utils.cache import ttl_cache

logger = logging.getLogger(__name__)


class NbaDataService:
    """Service for fetching and caching NBA game data.

    Uses nba_api library for scoreboard and game data.
    Implements database-backed caching with configurable TTLs.
    """

    # Cache durations (in seconds)
    SCOREBOARD_TTL = 5  # 5 seconds
    SCHEDULE_TTL = 24 * 60 * 60  # 24 hours
    CURRENT_SEASON_SCHEDULE_CDN_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
    SCOREBOARD_GAME_TIME_KEY = "gameTimeUTC"
    SCHEDULE_GAME_TIME_KEY = "gameDateTimeUTC"

    def __init__(self, db_session: AsyncSession, external_data_repository: ExternalDataRepository):
        self.db_session = db_session
        self.repo = external_data_repository

    async def get_scoreboard_cached(self, bypass: bool = False) -> tuple[list[dict], datetime.date]:
        """Get today's scoreboard data with database caching.

        Returns:
            Tuple of (game_data_list, scoreboard_date)
        """
        cached = None
        if not bypass:
            key = "nba:scoreboard:live"
            cached = await self.repo.get_by_key(key)
        
        if cached and self._is_cache_valid(cached.updated_at, self.SCOREBOARD_TTL):
            logger.debug(f"Scoreboard cache hit for {key}")
            return self._parse_scoreboard_from_cache(cached.data_json)

        try:
            raw_response = await asyncio.to_thread(self._fetch_scoreboard_raw)
            logger.debug(f"Updating cached scoreboard data for {key}")
            await self._store_scoreboard_raw(key, raw_response)
        except Exception as e:
            logger.error(f"Failed to fetch scoreboard from NBA API: {e}")
            if cached:
                logger.warning(f"Returning stale scoreboard data from {cached.updated_at}")
                return self._parse_scoreboard_from_cache(cached.data_json)
            raise

        # If the game date has changed, refresh the schedule
        if cached:
            cached_game_date = cached.data_json.get("scoreboard", {}).get("gameDate")
            current_game_date = raw_response.get("scoreboard", {}).get("gameDate")
            if current_game_date != cached_game_date:
                logger.info("New game date detected in scoreboard, refreshing schedule")
                asyncio.create_task(self.get_schedule_cached(bypass=True))
        
        return self._parse_scoreboard_from_cache(raw_response)
    
    async def get_schedule_cached(self, scoreboard_date: date, season: str, bypass: bool = False) -> tuple[list[dict], str]:
        """Get schedule data up to scoreboard_date with database caching (24 hour TTL).

        Args:
            scoreboard_date: Date to fetch schedule up to (exclusive)
            season: Season string (YYYY-YY)

        Returns:
            Tuple of (game_data_list, current_season_year)
        """
        key = f"nba:schedule:{season}"

        if not bypass:
            cached = await self.repo.get_by_key(key)
            if cached and self._is_cache_valid(cached.updated_at, self.SCHEDULE_TTL):
                logger.debug(f"Schedule cache hit for season {season}")
                return self._parse_schedule_from_cache(cached.data_json, scoreboard_date)

        try:
            logger.info(f"Fetching fresh schedule data for season {season}")
            raw_response = await asyncio.to_thread(self._fetch_schedule_raw, season)
            await self._store_schedule_raw(key, raw_response)
        except Exception as e:
            logger.error(f"Failed to fetch schedule from NBA API: {e}")
            if cached:
                logger.warning(f"Returning stale schedule data from {cached.updated_at}")
                return self._parse_schedule_from_cache(cached.data_json, scoreboard_date)
            raise

        return self._parse_schedule_from_cache(raw_response, scoreboard_date)

    def _fetch_scoreboard_raw(self) -> dict:
        """Fetch raw scoreboard data from nba_api.

        Returns:
            Raw scoreboard dictionary from NBA API
        """
        # Fetch scoreboard from nba_api and return raw response
        board = scoreboard.ScoreBoard()
        return board.get_dict()

    def _fetch_schedule_raw(self, season_year: str) -> dict:
        """Fetch raw schedule data from nba_api.

        Args:
            season_year: Season string in format YYYY-YY

        Returns:
            Raw schedule dictionary from NBA API
        """
        schedule = scheduleleaguev2.ScheduleLeagueV2(
            season=season_year,
            league_id="00",
        )

        # Return raw API response, just like scoreboard
        return schedule.get_dict()

    def _fetch_schedule_raw_cdn(self) -> dict:
        """Fetch the raw schedule from the current season using the fast CDN endpoint.

        Returns:
            Raw schedule dictionary from NBA API
        """
        response = requests.get(self.CURRENT_SEASON_SCHEDULE_CDN_URL)
        response.raise_for_status()
        return response.json()

    @ttl_cache(ttl_seconds=86400)
    def get_current_season(self) -> str:
        """Fetch the current seasonYear string

        Returns:
            string in format YYYY-YY
        """
        schedule = self._fetch_schedule_raw_cdn()
        return schedule.get("leagueSchedule", {}).get("seasonYear")

    def _parse_game_data(self, game: dict, game_timestamp: str) -> dict:
        """Helper method to parse game data from one item

        Args:
            game: a dict, one element of the NBA.com API response that represents a single game
            game_timestamp: a str representing the start time of the game.
                Needs to be an arg since the scoreboard and schedule responses use different keys for this

        Returns:
            a dict containing relevant information
        """
        # TODO: Set status as final when it says something like 4Q 0:00
        return {
            "date_time": pd.to_datetime(game_timestamp, utc=True).astimezone(tz="US/Eastern"),
            "game_id": game.get("gameId"),
            "home_team": game.get("homeTeam", {}).get("teamId"),
            "home_tricode": game.get("homeTeam", {}).get("teamTricode"),
            "home_score": game.get("homeTeam", {}).get("score"),
            "away_team": game.get("awayTeam", {}).get("teamId"),
            "away_tricode": game.get("awayTeam", {}).get("teamTricode"),
            "away_score": game.get("awayTeam", {}).get("score"),
            "status_text": game.get("gameStatusText"),
            "game_clock": game.get("gameClock"),
            "status": NBAGameStatus(game.get("gameStatus")),
        }

    def _parse_scoreboard_from_cache(self, raw_response: dict) -> tuple[list[dict], date]:
        """Parse scoreboard data from cached raw API response.

        Args:
            raw_response: Raw scoreboard dictionary from NBA API

        Returns:
            Tuple of (list of game dicts, scoreboard_date)
        """
        game_data = []

        # Extract game date
        scoreboard_date = pd.to_datetime(raw_response["scoreboard"]["gameDate"]).date()

        # Parse each game
        for game in raw_response["scoreboard"]["games"]:
            game_data.append(self._parse_game_data(game, game.get(self.SCOREBOARD_GAME_TIME_KEY)))

        return game_data, scoreboard_date

    def _parse_schedule_from_cache(self, raw_response: dict, scoreboard_date: date) -> tuple[list[dict], str]:
        """Parse schedule data from cached raw API response.

        Args:
            raw_response: Raw schedule data dictionary from NBA API (scheduleleaguev2 format)
            scoreboard_date: Date to filter games up to (exclusive)

        Returns:
            Tuple of (list of game dicts, season_year)
        """
        # Extract season from leagueSchedule
        league_schedule = raw_response.get("leagueSchedule", {})
        season_year = league_schedule.get("seasonYear", "")

        game_data: list[dict] = []
        for game_date in league_schedule.get("gameDates", []):
            date = pd.to_datetime(game_date["gameDate"]).date()
            if date < scoreboard_date:
                for game in game_date["games"]:
                    # Filter out preseason games using both gameLabel and seriesText
                    # gameLabel is used in newer API responses, seriesText in older ones
                    game_label = str(game.get("gameLabel", "")).lower()
                    series_text = str(game.get("seriesText", "")).lower()
                    if "preseason" not in game_label and "preseason" not in series_text:
                        game_data.append(self._parse_game_data(game, game[self.SCHEDULE_GAME_TIME_KEY]))
        logger.info(f"Parsed {len(game_data)} games for season {season_year}")
        return game_data, season_year

    def _build_game_identifier(self, date_time_iso: str, home_team_id: int, away_team_id: int) -> str:
        """Build a deterministic fallback identifier when the NBA API omits gameId."""
        return f"{date_time_iso or 'unknown'}-{home_team_id}-vs-{away_team_id}"

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

    async def _store_data(self, key: str, data: dict) -> None:
        """Store data in database cache (generic helper).

        Args:
            key: Cache key
            data: Data dictionary to store
        """
        existing = await self.repo.get_by_key(key)
        if existing:
            existing.data_json = data
            await self.repo.update(existing)
            logger.debug(f"Updated cache for {key}")
        else:
            external_data = ExternalData(key=key, data_format=DataFormat.JSON, data_json=data)
            await self.repo.save(external_data)
            logger.debug(f"Created cache for {key}")

    async def _store_scoreboard_raw(self, key: str, raw_response: dict) -> None:
        """Store raw scoreboard API response in database.

        Args:
            key: Cache key
            raw_response: Raw scoreboard dictionary from NBA API
        """
        await self._store_data(key, raw_response)

    async def _store_schedule_raw(self, key: str, raw_response: dict) -> None:
        """Store raw schedule API response in database.

        Args:
            key: Cache key
            raw_response: Raw schedule data dictionary from NBA API
        """
        # Store the raw response as-is (season is already in parameters)
        await self._store_data(key, raw_response)

    async def cleanup_old_scoreboards(self, keep_days: int = 365) -> int:
        """Delete old scoreboard data to prevent database bloat.

        Args:
            keep_days: Number of days of scoreboard data to keep (default: 1 year)

        Returns:
            Number of records deleted
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=keep_days)

        # Get all scoreboard keys
        scoreboards = await self.repo.get_by_key_prefix("nba:scoreboard:", limit=1000)

        deleted = 0
        for record in scoreboards:
            if record.created_at < cutoff_date:
                await self.repo.delete(record)
                deleted += 1

        logger.info(f"Cleaned up {deleted} old scoreboard records")
        return deleted

    # Public methods for background jobs

    async def update_scoreboard(self):
        """Fetch and cache scoreboard data (called by background job).

        This method is designed to be called by the scheduler. It fetches
        the latest scoreboard data and caches it in the database.

        Note: This simply calls get_scoreboard_cached() which handles all
        the caching logic. The method exists to provide a clear entry point
        for background jobs and to log the update.
        """
        games, scoreboard_date = await self.get_scoreboard_cached()
        logger.info(f"Scoreboard updated: {len(games)} games on {scoreboard_date}")

    async def update_schedule(self, season: str, scoreboard_date: date):
        """Fetch and cache schedule data (called by background job).

        Args:
            season: Season string in format YYYY-YY
            scoreboard_date: Date to fetch schedule up to (exclusive)

        This method is designed to be called by the scheduler. It fetches
        the full season schedule and caches it in the database.

        Note: This simply calls get_schedule_cached() which handles all
        the caching logic. The method exists to provide a clear entry point
        for background jobs and to log the update.
        """
        games, season_year = await self.get_schedule_cached(scoreboard_date=scoreboard_date, season=season)
        logger.info(f"Schedule updated: {len(games)} games for season {season_year}")

    def has_active_games(self, games: list[dict]) -> bool:
        """Check if there are any live or upcoming games.

        Args:
            games: List of game dictionaries

        Returns:
            True if any games are live or upcoming today
        """
        for game in games:
            status = game.get("status")
            if status in (NBAGameStatus.PREGAME, NBAGameStatus.INGAME):
                return True
        return False


# Dependency injection
def get_nba_data_service(
    db: AsyncSession = Depends(get_db_session),
    external_repo: ExternalDataRepository = Depends(get_external_data_repository),
) -> NbaDataService:
    """Get NbaDataService instance for dependency injection or manual usage."""
    if isinstance(external_repo, ExternalDataRepository):
        repo = external_repo
    else:
        repo = ExternalDataRepository(db)
    return NbaDataService(db_session=db, external_data_repository=repo)
