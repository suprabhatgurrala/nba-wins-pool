import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from nba_api.live.nba.endpoints import scoreboard
from nba_api.stats.endpoints import scheduleleaguev2
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.models.external_data import DataFormat, ExternalData
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.types.nba_game_status import NBAGameStatus

logger = logging.getLogger(__name__)


class NbaDataService:
    """Service for fetching and caching NBA game data.

    Uses nba_api library for scoreboard and game data.
    Implements database-backed caching with configurable TTLs.
    """
    # Cache durations (in seconds)
    SCOREBOARD_TTL = 5 * 60  # 5 minutes
    SCHEDULE_TTL = 24 * 60 * 60  # 24 hours

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.repo = ExternalDataRepository(db_session)

    async def get_scoreboard_cached(self) -> tuple[list[dict], datetime.date]:
        """Get today's scoreboard data with database caching (5 minute TTL).

        Returns:
            Tuple of (game_data_list, scoreboard_date)
        """
        now = datetime.now(UTC)
        today = now.date()
        key = f"nba:scoreboard:{today.isoformat()}"

        # Check database cache
        cached = await self.repo.get_by_key(key)
        if cached and self._is_cache_valid(cached.updated_at, self.SCOREBOARD_TTL):
            logger.debug(f"Scoreboard cache hit for {today}")
            return cached.data_json["games"], date.fromisoformat(cached.data_json["date"])

        # Fetch fresh data from NBA API
        try:
            logger.info(f"Fetching fresh scoreboard data for {today}")
            game_data, scoreboard_date = await asyncio.to_thread(self._fetch_scoreboard)
            
            # Store in database
            await self._store_scoreboard(key, game_data, scoreboard_date)
            
            return game_data, scoreboard_date
        except Exception as e:
            logger.error(f"Failed to fetch scoreboard from NBA API: {e}")
            # Return stale data if available
            if cached:
                logger.warning(f"Returning stale scoreboard data from {cached.updated_at}")
                return cached.data_json["games"], date.fromisoformat(cached.data_json["date"])
            raise

    async def get_schedule_cached(self, scoreboard_date: date, season: str) -> tuple[list[dict], str]:
        """Get schedule data up to scoreboard_date with database caching (24 hour TTL).

        Args:
            scoreboard_date: Date to fetch schedule up to (exclusive)
            season: Season string (YYYY-YY)

        Returns:
            Tuple of (game_data_list, current_season_year)
        """
        key = f"nba:schedule:{season}"

        # Check database cache
        cached = await self.repo.get_by_key(key)
        if cached and self._is_cache_valid(cached.updated_at, self.SCHEDULE_TTL):
            logger.debug(f"Schedule cache hit for season {season}")
            return cached.data_json["games"], cached.data_json["season"]

        # Fetch fresh data from NBA API
        try:
            logger.info(f"Fetching fresh schedule data for season {season}")
            game_data, season_year = await asyncio.to_thread(
                self._fetch_schedule, scoreboard_date, season
            )
            
            # Store in database
            await self._store_schedule(key, game_data, season_year)
            
            return game_data, season_year
        except Exception as e:
            logger.error(f"Failed to fetch schedule from NBA API: {e}")
            # Return stale data if available
            if cached:
                logger.warning(f"Returning stale schedule data from {cached.updated_at}")
                return cached.data_json["games"], cached.data_json["season"]
            raise

    def _fetch_scoreboard(self) -> tuple[list[dict], date]:
        """Fetch today's scoreboard data using nba_api.

        Returns:
            Tuple of (list of game dicts, scoreboard_date)
        """
        game_data = []

        # Fetch scoreboard from nba_api
        board = scoreboard.ScoreBoard()
        scoreboard_dict = board.get_dict()

        # Extract game date
        scoreboard_date = pd.to_datetime(scoreboard_dict["scoreboard"]["gameDate"]).date()

        # Parse each game
        for game in scoreboard_dict["scoreboard"]["games"]:
            game_data.append(self._parse_live_game_data(game))

        return game_data, scoreboard_date

    def _fetch_schedule(self, scoreboard_date: date, season_year: str) -> tuple[list[dict], str]:
        """Fetch historical game data up to scoreboard_date using nba_api.

        Args:
            scoreboard_date: Date to stop fetching games (exclusive)
            season_year: Season string in format YYYY-YY

        Returns:
            Tuple of (list of game dicts, current_season_year)
        """
        game_data: list[dict] = []

        schedule = scheduleleaguev2.ScheduleLeagueV2(
            season=season_year,
            league_id="00",
        )

        games_df = schedule.season_games.get_data_frame()

        if games_df.empty:
            return game_data, season_year

        games_df["gameDateTimeUTC"] = pd.to_datetime(
            games_df["gameDateTimeUTC"], errors="coerce", utc=True
        )
        games_df["gameDateUTC"] = pd.to_datetime(
            games_df["gameDateUTC"], errors="coerce", utc=True
        )

        games_df = games_df.dropna(subset=["homeTeam_teamId", "awayTeam_teamId"])

        games_df["gameStatus"] = (
            pd.to_numeric(games_df["gameStatus"], errors="coerce")
            .fillna(0)
            .astype(int)
        )

        games_df["normalized_date_time"] = games_df["gameDateTimeUTC"].fillna(games_df["gameDateUTC"])
        games_df = games_df.dropna(subset=["normalized_date_time"])

        # Filter for completed games before scoreboard date
        games_df = games_df[
            (games_df["normalized_date_time"].dt.date < scoreboard_date)
            & (games_df["gameStatus"] == NBAGameStatus.FINAL.value)
        ]

        if games_df.empty:
            return game_data, season_year

        games_df = games_df.sort_values("normalized_date_time")

        for _, row in games_df.iterrows():
            status_value = int(row["gameStatus"])
            try:
                status_enum = NBAGameStatus(status_value)
            except ValueError:
                status_enum = (
                    NBAGameStatus.FINAL
                    if status_value >= NBAGameStatus.FINAL.value
                    else NBAGameStatus.PREGAME
                )

            home_team_raw = pd.to_numeric(row["homeTeam_teamId"], errors="coerce")
            away_team_raw = pd.to_numeric(row["awayTeam_teamId"], errors="coerce")

            if pd.isna(home_team_raw) or pd.isna(away_team_raw):
                continue

            home_score = pd.to_numeric(row["homeTeam_score"], errors="coerce")
            away_score = pd.to_numeric(row["awayTeam_score"], errors="coerce")

            date_time = row["normalized_date_time"]
            date_time_iso = date_time.isoformat() if pd.notna(date_time) else ""

            status_text = row.get("gameStatusText", "")
            if isinstance(status_text, float) and pd.isna(status_text):
                status_text = ""
            
            game_label = row.get("gameLabel", "")
            if isinstance(game_label, float) and pd.isna(game_label):
                game_label = ""

            game_id = row.get("gameId") or row.get("game_id")
            game_dict = {
                "game_id": str(game_id) if game_id else self._build_game_identifier(date_time_iso, int(home_team_raw), int(away_team_raw)),
                "date_time": date_time_iso,
                "home_team": int(home_team_raw),
                "home_score": int(home_score) if not pd.isna(home_score) else 0,
                "away_team": int(away_team_raw),
                "away_score": int(away_score) if not pd.isna(away_score) else 0,
                "status_text": status_text,
                "status": status_enum,
                "game_label": game_label,
            }
            game_data.append(game_dict)

        return game_data, season_year


    def _parse_live_game_data(self, game: dict) -> dict:
        """Parse game data from nba_api scoreboard format.

        Args:
            game: Dict representing a single game from nba_api scoreboard

        Returns:
            Dict containing parsed game information
        """
        # Map game status codes to our enum
        # nba_api gameStatus: 1=scheduled/pregame, 2=live, 3=finished
        game_status = game.get("gameStatus", 1)
        status_enum = NBAGameStatus(game_status)
        
        game_id = game.get("gameId") or game.get("game_id")
        return {
            "game_id": str(game_id) if game_id else self._build_game_identifier(
                game.get("gameTimeUTC", ""), int(game["homeTeam"]["teamId"]), int(game["awayTeam"]["teamId"])
            ),
            "date_time": game.get("gameTimeUTC", ""),
            "home_team": int(game["homeTeam"]["teamId"]),
            "home_score": game["homeTeam"].get("score", 0),
            "away_team": int(game["awayTeam"]["teamId"]),
            "away_score": game["awayTeam"].get("score", 0),
            "status_text": game.get("gameStatusText", ""),
            "status": status_enum,
            "game_label": game.get("gameLabel", ""),
        }

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
            external_data = ExternalData(
                key=key,
                data_format=DataFormat.JSON,
                data_json=data
            )
            await self.repo.save(external_data)
            logger.debug(f"Created cache for {key}")

    async def _store_scoreboard(self, key: str, game_data: list[dict], scoreboard_date: date) -> None:
        """Store scoreboard data in database.
        
        Args:
            key: Cache key
            game_data: List of game dictionaries
            scoreboard_date: Date of the scoreboard
        """
        data = {
            "games": game_data,
            "date": scoreboard_date.isoformat()
        }
        await self._store_data(key, data)

    async def _store_schedule(self, key: str, game_data: list[dict], season: str) -> None:
        """Store schedule data in database.
        
        Args:
            key: Cache key
            game_data: List of game dictionaries
            season: Season string
        """
        data = {
            "games": game_data,
            "season": season
        }
        await self._store_data(key, data)

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
        games, season_year = await self.get_schedule_cached(
            scoreboard_date=scoreboard_date,
            season=season
        )
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
async def get_nba_data_service(db: AsyncSession) -> NbaDataService:
    """Get NbaDataService instance for dependency injection.
    
    Args:
        db: Database session
        
    Returns:
        NbaDataService instance
    """
    return NbaDataService(db)
