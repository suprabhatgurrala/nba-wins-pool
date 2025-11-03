import logging
import os
from datetime import date

import pandas as pd
import requests
from fastapi import Depends
from nba_api.live.nba.endpoints import scoreboard
from nba_api.stats.endpoints import scheduleleaguev2
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
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
    SCOREBOARD_TTL = 10  # 5 seconds
    SCHEDULE_TTL = 24 * 60 * 60  # 24 hours
    HISTORICAL_SCHEDULE_TTL = 365 * 24 * 60 * 60  # 1 year
    CURRENT_SEASON_SCHEDULE_CDN_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
    GAMECARD_FEED_URL = "https://core-api.nba.com/cp/api/v1.9/feeds/gamecardfeed"
    SCOREBOARD_GAME_TIME_KEY = "gameTimeUTC"
    SCHEDULE_GAME_TIME_KEY = "gameDateTimeUTC"
    GAMECARDFEED_GAME_TIME_KEY = "gameTimeUtc"
    NBA_API_KEY = os.getenv("NBA_API_KEY")

    def __init__(self, db_session: AsyncSession, external_data_repository: ExternalDataRepository):
        self.db_session = db_session
        self.repo = external_data_repository

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

    def _fetch_gamefeed_raw(self, game_date: str = None) -> dict:
        """Fetch raw gamefeed data from NBA.com.

        Returns:
            Raw gamefeed dictionary from NBA.com API
        """
        headers = {"ocp-apim-subscription-key": self.NBA_API_KEY}

        if game_date:
            params = {"gamedate": game_date}
        else:
            params = {}

        response = requests.get(self.GAMECARD_FEED_URL, headers=headers, params=params)
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

    @ttl_cache(ttl_seconds=10)
    def get_current_game_date(self) -> str:
        scoreboard = self._fetch_scoreboard_raw()
        return scoreboard.get("scoreboard", {}).get("gameDate")

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
        date_time_str = game.get(game_timestamp)
        if date_time_str is not None:
            date_time = pd.to_datetime(date_time_str, utc=True).astimezone(tz="US/Eastern")
        else:
            print("Date time str: ", game[game_timestamp], "Parsed date was None")
            date_time = None

        return {
            "date_time": date_time,
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

    def _parse_gamecardfeed(self, raw_response: dict) -> list[dict]:
        """Parse gamecardfeed data from cached raw API response.

        Args:
            raw_response: Raw gamecardfeed dictionary from NBA.
        """
        game_data = []

        for module in raw_response.get("modules", []):
            for card in module.get("cards", []):
                if card.get("cardType") == "game" and card.get("cardData"):
                    game_data.append(self._parse_game_data(card["cardData"], self.GAMECARDFEED_GAME_TIME_KEY))

        return game_data

    def _parse_schedule(self, raw_response: dict, scoreboard_date: date) -> tuple[list[dict], str]:
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
                        game_data.append(self._parse_game_data(game, self.SCHEDULE_GAME_TIME_KEY))
        logger.info(f"Parsed {len(game_data)} games for season {season_year}")
        return game_data

    async def get_game_data(self, season_year: str) -> pd.DataFrame:
        """
        Get game data for a given season.

        Args:
            season_year: Season string in format YYYY-YY

        Returns:
            DataFrame containing game data for the given season
        """
        if season_year == self.get_current_season():
            # Combine with gamecardfeed data to have up-to-date info
            scoreboard_date = pd.to_datetime(self._fetch_scoreboard_raw()["scoreboard"]["gameDate"]).date()
            schedule_data = self._fetch_schedule_raw_cdn()
            gamecardfeed_data = self._fetch_gamefeed_raw()
            schedule_parsed = self._parse_schedule(schedule_data, scoreboard_date)
            gamecardfeed_parsed = self._parse_gamecardfeed(gamecardfeed_data)
            schedule_parsed.extend(gamecardfeed_parsed)
            game_df = pd.DataFrame(schedule_parsed)
        else:
            schedule_data = self._fetch_schedule_raw(season_year)
            game_df = pd.DataFrame(self._parse_schedule(schedule_data, date.today()))

        if not game_df.empty:
            game_df["winning_team"] = game_df["home_team"].where(
                (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score > game_df.away_score),
                other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
            )
            game_df["losing_team"] = game_df["home_team"].where(
                (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score < game_df.away_score),
                other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
            )

        return game_df


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
