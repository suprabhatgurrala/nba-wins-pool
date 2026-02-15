import asyncio
import logging
import os
from datetime import date

import pandas as pd
import requests
from fastapi import Depends
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
    SCOREBOARD_TTL = 10  # seconds
    SCHEDULE_TTL = 24 * 60 * 60  # 24 hours
    CURRENT_SEASON_SCHEDULE_CDN_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
    GAMECARDFEED_URL = "https://core-api.nba.com/cp/api/v1.9/feeds/gamecardfeed"
    SCOREBOARD_GAME_TIME_KEY = "gameTimeUTC"
    GAMECARDFEED_GAME_TIME_KEY = "gameTimeUtc"
    SCHEDULE_GAME_TIME_KEY = "gameDateTimeUTC"
    NBA_API_KEY = os.environ.get("NBA_API_KEY")
    EXCLUDE_SEASON_TYPES = ["Preseason", "All-Star"]

    def __init__(self, db_session: AsyncSession, external_data_repository: ExternalDataRepository):
        self.db_session = db_session
        self.repo = external_data_repository

    async def get_historical_schedule_cached(self, season: str) -> list[dict]:
        """Get historical schedule data for a given season.

        Args:
            season: Season string in format YYYY-YY

        Returns:
            List of game dictionaries
        """
        key = f"nba:schedule:{season}"
        cached = await self.repo.get_by_key(key)
        if cached:
            return self._parse_schedule(cached.data_json)
        else:
            try:
                logger.info(f"Fetching fresh schedule data for season {season}")
                raw_response = await asyncio.to_thread(self._fetch_schedule_raw, season)
                await self._store_data(key, raw_response)
            except Exception as e:
                logger.error(f"Failed to fetch schedule from NBA API: {e}")
                if cached:
                    logger.warning(f"Returning stale schedule data from {cached.updated_at}")
                    return self._parse_schedule(cached.data_json)
                raise

            return self._parse_schedule(raw_response)

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

    def _fetch_gamecardfeed_raw(self, game_date: str | None = None) -> dict:
        """Fetch the raw gamecardfeed from NBA.com

        Args:
            game_date: optional date in the format MM/DD/YYYY to fetch game data for

        Returns:
            Raw gamecardfeed dictionary from NBA.com API
        """
        if game_date:
            params = {
                "gameDate": game_date,
            }
        else:
            params = {}

        headers = {"ocp-apim-subscription-key": self.NBA_API_KEY}

        response = requests.get(self.GAMECARDFEED_URL, params=params, headers=headers)
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

        status = NBAGameStatus(game.get("gameStatus"))
        home_score = game.get("homeTeam", {}).get("score")
        away_score = game.get("awayTeam", {}).get("score")

        if status == NBAGameStatus.INGAME:
            period = game.get("period", 0)
            seconds_remaining = pd.Timedelta(game.get("gameClock", "PT12M00.00S")).seconds
            if period >= 4 and seconds_remaining == 0 and home_score - away_score != 0:
                status = NBAGameStatus.FINAL

        return {
            "date_time": pd.to_datetime(game_timestamp, utc=True).astimezone(tz="US/Eastern"),
            "game_id": game.get("gameId"),
            "home_team": game.get("homeTeam", {}).get("teamId"),
            "home_tricode": game.get("homeTeam", {}).get("teamTricode"),
            "home_score": home_score,
            "away_team": game.get("awayTeam", {}).get("teamId"),
            "away_tricode": game.get("awayTeam", {}).get("teamTricode"),
            "away_score": away_score,
            "status_text": game.get("gameStatusText"),
            "game_clock": game.get("gameClock"),
            "status": status,
        }

    def _parse_gamecardfeed(self, raw_response: dict) -> tuple[list[dict], set]:
        """Parse gamecardfeed data from API response.

        Args:
            raw_response: Raw gamecardfeed dictionary from NBA.com

        Returns:
            Tuple of (list of game dicts, set of game IDs)
        """
        game_data = []
        gameIds = set()
        scoreboard_date = None

        for module in raw_response.get("modules", []):
            for card in module.get("cards", []):
                if card.get("cardType") == "game" and card.get("cardData"):
                    if scoreboard_date is None:
                        scoreboard_date = (
                            pd.to_datetime(card["cardData"].get("gameTimeUtc"), utc=True)
                            .astimezone(tz="US/Eastern")
                            .date()
                        )
                    season_type = card["cardData"].get("seasonType")
                    if season_type in self.EXCLUDE_SEASON_TYPES:
                        continue
                    gameId = card["cardData"].get("gameId")
                    if gameId:
                        gameIds.add(gameId)
                    game_data.append(
                        self._parse_game_data(card["cardData"], card["cardData"].get(self.GAMECARDFEED_GAME_TIME_KEY))
                    )

        return game_data, gameIds, scoreboard_date

    def _parse_schedule(
        self, raw_response: dict, scoreboard_gameids: set | None = None, scoreboard_date: date | None = None
    ) -> list[dict]:
        """Parse schedule data from cached raw API response.

        Args:
            raw_response: Raw schedule data dictionary from NBA API (scheduleleaguev2 format)
            scoreboard_gameids: Optional set of game IDs from scoreboard to stop parsing when reached
            scoreboard_date: Optional date of scoreboard to stop parsing when reached. Only used if scoreboard_gameids is not provided

        Returns:
            List of game dictionaries
        """
        if scoreboard_gameids is None:
            scoreboard_gameids = set()

        # Extract season from leagueSchedule
        league_schedule = raw_response.get("leagueSchedule", {})
        season_year = league_schedule.get("seasonYear", "")

        game_data: list[dict] = []
        for game_date in league_schedule.get("gameDates", []):
            if (
                len(scoreboard_gameids) == 0
                and scoreboard_date
                and pd.to_datetime(game_date["gameDate"]).date() > scoreboard_date
            ):
                break
            for game in game_date["games"]:
                # Filter out preseason games using both gameLabel and seriesText
                # gameLabel is used in newer API responses, seriesText in older ones
                game_label = str(game.get("gameLabel", "")).lower()
                series_text = str(game.get("seriesText", "")).lower()
                game_id = game.get("gameId")
                game_in_scoreboard = game_id in scoreboard_gameids
                if "preseason" not in game_label and "preseason" not in series_text and not game_in_scoreboard:
                    game_data.append(self._parse_game_data(game, game[self.SCHEDULE_GAME_TIME_KEY]))
            if game_in_scoreboard:
                break
        logger.info(f"Parsed {len(game_data)} games for season {season_year}")
        return game_data

    @ttl_cache(ttl_seconds=10)
    async def get_game_data(self, season_year: str) -> pd.DataFrame:
        """Get game data for a given season, combining current season live games with schedule if necessary.

        Args:
            season_year: Season string in format YYYY-YY

        Returns:
            DataFrame with game data including winning_team and losing_team columns
        """
        if season_year == self.get_current_season():
            # combine CDN schedule and gamecardfeed
            live_games, game_ids, scoreboard_date = self._parse_gamecardfeed(self._fetch_gamecardfeed_raw())
            schedule = self._parse_schedule(
                self._fetch_schedule_raw_cdn(), scoreboard_gameids=game_ids, scoreboard_date=scoreboard_date
            )
            schedule.extend(live_games)
            game_df = pd.DataFrame(schedule)
        else:
            game_df = pd.DataFrame(await self.get_historical_schedule_cached(season_year))

        game_df["winning_team"] = game_df["home_team"].where(
            (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score > game_df.away_score),
            other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
        )
        game_df["losing_team"] = game_df["home_team"].where(
            (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score < game_df.away_score),
            other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
        )
        return game_df

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
