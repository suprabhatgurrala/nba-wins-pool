import asyncio
import concurrent.futures
import logging
import os
from datetime import date, datetime

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
from nba_wins_pool.types.nba_game_type import NBAGameType
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
    ESPN_SEASON_URL = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{year}"
    SCOREBOARD_GAME_TIME_KEY = "gameTimeUTC"
    GAMECARDFEED_GAME_TIME_KEY = "gameTimeUtc"
    SCHEDULE_GAME_TIME_KEY = "gameDateTimeUTC"
    NBA_API_KEY = os.environ.get("NBA_API_KEY")
    EXCLUDE_SEASON_TYPES = ["Preseason", "All-Star"]
    # Keywords matched as substrings against gameLabel in the schedule endpoint.
    # Using substrings makes this robust to label renames (e.g. "NBA Rising Stars ...").
    EXCLUDE_GAME_LABEL_KEYWORDS = ["Preseason", "All-Star", "Rising Stars"]
    # ESPN season type ID -> NBAGameType
    ESPN_SEASON_TYPE_MAP: dict[int, NBAGameType] = {
        1: NBAGameType.PRESEASON,
        2: NBAGameType.REGULAR_SEASON,
        3: NBAGameType.PLAYOFFS,
        5: NBAGameType.PLAY_IN,
    }
    # NBA.com gamecardfeed seasonType string -> NBAGameType
    GAMECARDFEED_SEASON_TYPE_MAP: dict[str, NBAGameType] = {
        "Regular Season": NBAGameType.REGULAR_SEASON,
        "PlayIn": NBAGameType.PLAY_IN,
        "Play-In Tournament": NBAGameType.PLAY_IN,
        "Playoffs": NBAGameType.PLAYOFFS,
        "Pre Season": NBAGameType.PRESEASON,
        "Preseason": NBAGameType.PRESEASON,
    }

    def __init__(self, db_session: AsyncSession, external_data_repository: ExternalDataRepository):
        self.db_session = db_session
        self.repo = external_data_repository

    def _get_espn_season_type_dates(self, season_year: str) -> list[tuple[NBAGameType, datetime, datetime]] | None:
        """Fetch ESPN season type date ranges, returning None on failure.

        Args:
            season_year: Season string in format YYYY-YY (e.g. '2025-26').

        Returns:
            List of (game_type, start_dt, end_dt) tuples, or None if the fetch fails.
        """
        try:
            espn_year = self._espn_year_from_season(season_year)
            return self._fetch_espn_season_type_dates(espn_year)
        except Exception:
            logger.warning(
                "Failed to fetch ESPN season type dates for %s; game_type will default to REGULAR_SEASON",
                season_year,
                exc_info=True,
            )
            return None

    async def get_historical_schedule_cached(
        self,
        season: str,
        season_type_dates: list[tuple[NBAGameType, datetime, datetime]] | None = None,
    ) -> list[dict]:
        """Get historical schedule data for a given season.

        Args:
            season: Season string in format YYYY-YY
            season_type_dates: Optional ESPN season type date ranges for game labelling.

        Returns:
            List of game dictionaries
        """
        key = f"nba:schedule:{season}"
        cached = await self.repo.get_by_key(key)
        if cached:
            return self._parse_schedule(cached.data_json, season_type_dates=season_type_dates)
        else:
            try:
                logger.info(f"Fetching fresh schedule data for season {season}")
                raw_response = await asyncio.to_thread(self._fetch_schedule_raw, season)
                await self._store_data(key, raw_response)
            except Exception as e:
                logger.error(f"Failed to fetch schedule from NBA API: {e}")
                if cached:
                    logger.warning(f"Returning stale schedule data from {cached.updated_at}")
                    return self._parse_schedule(cached.data_json, season_type_dates=season_type_dates)
                raise

            return self._parse_schedule(raw_response, season_type_dates=season_type_dates)

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

    @ttl_cache(ttl_seconds=10)
    def _fetch_current_season_raw(self) -> tuple[dict, dict]:
        """Fetch gamecardfeed and CDN schedule atomically in parallel.

        Returns:
            Tuple of (gamecardfeed_raw, schedule_raw)
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f_gamecardfeed = executor.submit(self._fetch_gamecardfeed_raw)
            f_schedule = executor.submit(self._fetch_schedule_raw_cdn)
            return f_gamecardfeed.result(), f_schedule.result()

    @ttl_cache(ttl_seconds=86400)
    def get_current_season(self) -> str:
        """Fetch the current seasonYear string

        Returns:
            string in format YYYY-YY
        """
        _, schedule = self._fetch_current_season_raw()
        return schedule.get("leagueSchedule", {}).get("seasonYear")

    @ttl_cache(ttl_seconds=86400)
    def _fetch_espn_season_type_dates(self, espn_year: int) -> list[tuple[NBAGameType, datetime, datetime]]:
        """Fetch season type date boundaries from the ESPN core API.

        Args:
            espn_year: The ending calendar year of the season (e.g. 2026 for the 2025-26 season).

        Returns:
            List of (game_type, start_dt, end_dt) tuples sorted by start date, with UTC-aware datetimes.
        """
        url = self.ESPN_SEASON_URL.format(year=espn_year)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        ranges = []
        for item in data.get("types", {}).get("items", []):
            type_id = item.get("type")
            game_type = self.ESPN_SEASON_TYPE_MAP.get(type_id)
            if game_type is None:
                continue
            start = datetime.fromisoformat(item["startDate"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(item["endDate"].replace("Z", "+00:00"))
            ranges.append((game_type, start, end))

        return sorted(ranges, key=lambda x: x[1])

    @staticmethod
    def _classify_game_date(
        game_dt: datetime,
        season_type_dates: list[tuple[NBAGameType, datetime, datetime]],
    ) -> NBAGameType:
        """Classify a game's UTC datetime into an NBAGameType using ESPN season date ranges.

        Args:
            game_dt: UTC-aware datetime of the game start time.
            season_type_dates: Output of ``_fetch_espn_season_type_dates``.

        Returns:
            The matching NBAGameType, or REGULAR_SEASON as a fallback.
        """
        if season_type_dates is None:
            raise ValueError("season_type_dates cannot be None")
        if len(season_type_dates) == 0:
            raise ValueError("season_type_dates cannot be empty")
        for game_type, start, end in season_type_dates:
            if start <= game_dt <= end:
                return game_type
        return NBAGameType.REGULAR_SEASON

    @staticmethod
    def _espn_year_from_season(season_year: str) -> int:
        """Convert a season string like '2025-26' or '2025' to the ESPN API year (2026).

        Args:
            season_year: Season string in format YYYY-YY or YYYY.

        Returns:
            Four-digit ending calendar year.
        """
        # Both "2025" and "2025-26" represent the season starting in 2025 and ending in 2026.
        # ESPN API uses the ending year.
        start_year_str = season_year.split("-")[0]
        return int(start_year_str) + 1

    @staticmethod
    def _get_all_star_date_from_schedule(raw_schedule: dict) -> str | None:
        """Find the last regular-season game date before the All-Star break.

        Detects the break by watching for a run of game dates that contain only
        All-Star/Rising Stars events (no regular games). Returns the last date
        before that run that had at least one regular game. Does not rely on the
        weeks[] array, which may use different names across seasons.

        Args:
            raw_schedule: Raw schedule dict from NBA API (scheduleleaguev2 format).

        Returns:
            Date string in YYYY-MM-DD format, or None if no All-Star break is detected.
        """
        exclude_keywords = ["All-Star", "Rising Stars"]
        last_regular_date: date | None = None
        in_all_star_break = False

        for game_date_entry in raw_schedule.get("leagueSchedule", {}).get("gameDates", []):
            raw_date = game_date_entry.get("gameDate", "")
            try:
                game_dt = datetime.strptime(raw_date[:10], "%m/%d/%Y").date()
            except ValueError:
                continue

            games = game_date_entry.get("games", [])
            has_regular_game = any(not any(kw in (g.get("gameLabel") or "") for kw in exclude_keywords) for g in games)
            has_all_star_game = any(any(kw in (g.get("gameLabel") or "") for kw in exclude_keywords) for g in games)

            if in_all_star_break and has_regular_game:
                break

            if has_all_star_game and not has_regular_game:
                in_all_star_break = True

            if has_regular_game:
                last_regular_date = game_dt

        return last_regular_date.strftime("%Y-%m-%d") if in_all_star_break and last_regular_date else None

    @staticmethod
    def _get_regular_season_end_date(season_type_dates: list[tuple[NBAGameType, datetime, datetime]]) -> str | None:
        """Extract the Regular Season end date from ESPN season type date ranges.

        Args:
            season_type_dates: Output of ``_fetch_espn_season_type_dates``.

        Returns:
            Date string in YYYY-MM-DD format, or None if Regular Season is not found.
        """
        for game_type, _start, end in season_type_dates:
            if game_type == NBAGameType.REGULAR_SEASON:
                return end.strftime("%Y-%m-%d")
        return None

    async def _get_raw_schedule_cached(self, season_year: str) -> dict:
        """Get the raw schedule dict for a season, using the DB cache when available.

        Args:
            season_year: Season string in format YYYY-YY.

        Returns:
            Raw schedule dictionary from NBA API.
        """
        if season_year == self.get_current_season():
            _, raw_schedule = await asyncio.to_thread(self._fetch_current_season_raw)
            return raw_schedule
        key = f"nba:schedule:{season_year}"
        cached = await self.repo.get_by_key(key)
        if cached:
            return cached.data_json
        raw = await asyncio.to_thread(self._fetch_schedule_raw, season_year)
        await self._store_data(key, raw)
        return raw

    async def get_season_milestones(self, season_year: str) -> list[dict]:
        """Build milestone markers for the wins race chart for a given season.

        Derives the All-Star Break date from the NBA schedule and the Playoffs start
        date from the ESPN Regular Season end date. Returns an empty list on failure.

        Args:
            season_year: Season string in format YYYY-YY.

        Returns:
            List of milestone dicts with slug, date (YYYY-MM-DD), and description keys,
            sorted chronologically.
        """
        milestones = []

        try:
            raw_schedule = await self._get_raw_schedule_cached(season_year)
            all_star_date = self._get_all_star_date_from_schedule(raw_schedule)
            if all_star_date:
                milestones.append({"slug": "all_star_break", "date": all_star_date, "description": "All-Star Break"})
        except Exception:
            logger.warning("Failed to extract All-Star date for %s", season_year, exc_info=True)

        try:
            season_type_dates = self._get_espn_season_type_dates(season_year)
            if season_type_dates:
                reg_end = self._get_regular_season_end_date(season_type_dates)
                if reg_end:
                    milestones.append({"slug": "playoffs_start", "date": reg_end, "description": "Playoffs"})
        except Exception:
            logger.warning("Failed to extract Playoffs date for %s", season_year, exc_info=True)

        return sorted(milestones, key=lambda m: m["date"])

    def _parse_game_data(
        self, game: dict, game_timestamp: str, game_type: NBAGameType = NBAGameType.REGULAR_SEASON
    ) -> dict:
        """Helper method to parse game data from one item

        Args:
            game: a dict, one element of the NBA.com API response that represents a single game
            game_timestamp: a str representing the start time of the game.
                Needs to be an arg since the scoreboard and schedule responses use different keys for this

        Returns:
            a dict containing relevant information
        """

        status = NBAGameStatus(game.get("gameStatus"))
        home_score = (game.get("homeTeam") or {}).get("score")
        away_score = (game.get("awayTeam") or {}).get("score")

        if status == NBAGameStatus.INGAME:
            period = game.get("period", 0)
            seconds_remaining = pd.Timedelta(game.get("gameClock", "PT12M00.00S")).seconds
            if period >= 4 and seconds_remaining == 0 and home_score - away_score != 0:
                status = NBAGameStatus.FINAL

        national_broadcasters = game.get("broadcasters", {}).get("nationalBroadcasters", [])
        national_broadcaster_logos = [
            b["broadcasterLogoUrlDarkSvg"] for b in national_broadcasters if b.get("broadcasterLogoUrlDarkSvg")
        ]

        home_team = game.get("homeTeam") or {}
        away_team = game.get("awayTeam") or {}

        # Seed: gamecardfeed uses specialInfoPrefix (string), schedule uses seed (int)
        raw_home_seed = home_team.get("specialInfoPrefix") or home_team.get("seed")
        raw_away_seed = away_team.get("specialInfoPrefix") or away_team.get("seed")
        try:
            home_seed: int | None = int(raw_home_seed) if raw_home_seed is not None else None
        except (ValueError, TypeError):
            home_seed = None
        try:
            away_seed: int | None = int(raw_away_seed) if raw_away_seed is not None else None
        except (ValueError, TypeError):
            away_seed = None

        # Series info: gamecardfeed uses info/subInfo, schedule uses gameSubLabel/seriesText
        game_label = game.get("gameLabel") or None
        series_game_text = game.get("info") or game.get("gameSubLabel") or None
        series_status_text = game.get("subInfo") or game.get("seriesText") or None
        raw_if_necessary = game.get("ifNecessary", False)
        if_necessary = raw_if_necessary is True or str(raw_if_necessary).lower() == "true"

        return {
            "date_time": game_timestamp,
            "game_id": game.get("gameId"),
            "game_code": game.get("gameCode"),
            "game_url": game.get("shareUrl"),
            "national_broadcaster_logos": national_broadcaster_logos or None,
            "home_team": home_team.get("teamId"),
            "home_tricode": home_team.get("teamTricode"),
            "home_score": home_score,
            "home_seed": home_seed,
            "away_team": away_team.get("teamId"),
            "away_tricode": away_team.get("teamTricode"),
            "away_score": away_score,
            "away_seed": away_seed,
            "game_label": game_label,
            "series_game_text": series_game_text,
            "series_status_text": series_status_text,
            "if_necessary": if_necessary,
            "status_text": game.get("gameStatusText"),
            "game_clock": game.get("gameClock"),
            "status": status,
            "game_type": game_type,
            "arena_name": game.get("arenaName"),
            "arena_city": game.get("arenaCity"),
            "arena_state": game.get("arenaState"),
        }

    def _parse_gamecardfeed(self, raw_response: dict) -> tuple[list[dict], set[str], date]:
        """Parse gamecardfeed data from API response.

        Args:
            raw_response: Raw gamecardfeed dictionary from NBA.com

        Returns:
            Tuple of (list of game dicts, set of game IDs, scoreboard date)
        """
        game_data = []
        gameIds = set()
        scoreboard_date = None

        for module in raw_response.get("modules", []):
            for card in module.get("cards", []):
                if card.get("cardType") == "game" and card.get("cardData"):
                    if scoreboard_date is None:
                        scoreboard_date = (
                            pd.to_datetime(card["cardData"].get("gameTimeUtc"), format="ISO8601", utc=True)
                            .astimezone(tz="US/Eastern")
                            .date()
                        )
                    season_type = card["cardData"].get("seasonType")
                    if season_type in self.EXCLUDE_SEASON_TYPES:
                        continue
                    game_type = self.GAMECARDFEED_SEASON_TYPE_MAP.get(season_type, NBAGameType.REGULAR_SEASON)
                    gameId = card["cardData"].get("gameId")
                    if gameId:
                        gameIds.add(gameId)
                    game_data.append(
                        self._parse_game_data(
                            card["cardData"],
                            card["cardData"].get(self.GAMECARDFEED_GAME_TIME_KEY),
                            game_type=game_type,
                        )
                    )

        if scoreboard_date is None:
            scoreboard_date = date.today()

        return game_data, gameIds, scoreboard_date

    def _parse_schedule(
        self,
        raw_response: dict,
        scoreboard_gameids: set | None = None,
        scoreboard_date: date | None = None,
        season_type_dates: list[tuple[NBAGameType, datetime, datetime]] | None = None,
    ) -> list[dict]:
        """Parse schedule data from cached raw API response.

        Args:
            raw_response: Raw schedule data dictionary from NBA API (scheduleleaguev2 format)
            scoreboard_gameids: Optional set of game IDs from scoreboard to stop parsing when reached
            scoreboard_date: Optional date of scoreboard to stop parsing when reached. Only used if scoreboard_gameids is not provided
            season_type_dates: Optional ESPN season type date ranges from ``_fetch_espn_season_type_dates``.
                When provided, each game is labelled with its NBAGameType. Defaults to REGULAR_SEASON when absent.

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
                and pd.to_datetime(game_date["gameDate"], format="mixed").date() > scoreboard_date
            ):
                break
            for game in game_date["games"]:
                game_label = game.get("gameLabel", "")
                game_id = game.get("gameId")
                game_in_scoreboard = game_id in scoreboard_gameids
                if not any(kw in game_label for kw in self.EXCLUDE_GAME_LABEL_KEYWORDS) and not game_in_scoreboard:
                    if season_type_dates:
                        raw_ts = game[self.SCHEDULE_GAME_TIME_KEY]
                        game_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                        game_type = self._classify_game_date(game_dt, season_type_dates)
                    else:
                        game_type = NBAGameType.REGULAR_SEASON
                    if game_type == NBAGameType.PRESEASON:
                        continue
                    game_data.append(
                        self._parse_game_data(game, game[self.SCHEDULE_GAME_TIME_KEY], game_type=game_type)
                    )
            if game_in_scoreboard:
                break
        logger.info(f"Parsed {len(game_data)} games for season {season_year}")
        return game_data

    def _build_current_schedule_df(self) -> pd.DataFrame:
        """Fetch current season schedule with live gamecardfeed status/score overlay.

        Single source of truth for current-season game data used by both the leaderboard
        and the simulator. Overlays the gamecardfeed (real-time) on top of the static CDN
        schedule so that status changes (e.g. INGAME → FINAL) are reflected immediately.

        Returns:
            Finalized DataFrame with winning_team/losing_team reflecting the latest scores.
        """
        raw_gamecardfeed, raw_schedule = self._fetch_current_season_raw()
        season_year = raw_schedule.get("leagueSchedule", {}).get("seasonYear", "")
        season_type_dates = self._get_espn_season_type_dates(season_year) if season_year else None
        live_games, _, scoreboard_date = self._parse_gamecardfeed(raw_gamecardfeed)

        schedule = self._parse_schedule(raw_schedule, season_type_dates=season_type_dates)
        game_df = pd.DataFrame(schedule)

        game_df = self._apply_live_overlay(game_df, live_games)
        return self._finalize_game_df(game_df)

    LIVE_OVERLAY_COLS = [
        "status",
        "status_text",
        "game_clock",
        "home_score",
        "away_score",
        "game_url",
        "national_broadcaster_logos",
    ]

    def _apply_live_overlay(self, game_df: pd.DataFrame, live_games: list[dict]) -> pd.DataFrame:
        """Overlay live gamecardfeed columns onto game_df in-place (or replace if game_df is empty)."""
        if not live_games:
            return game_df
        if game_df.empty:
            return pd.DataFrame(live_games)
        live_df = pd.DataFrame(live_games).set_index("game_id")[self.LIVE_OVERLAY_COLS]
        mask = game_df["game_id"].isin(live_df.index)
        for col in self.LIVE_OVERLAY_COLS:
            live_values = game_df.loc[mask, "game_id"].map(live_df[col])
            game_df.loc[mask, col] = live_values.where(live_values.notna(), game_df.loc[mask, col])
        return game_df

    @ttl_cache(ttl_seconds=30)
    def _fetch_gamecardfeed_for_date(self, game_date_str: str) -> dict:
        """Fetch gamecardfeed for a specific date, cached per date at 30s TTL."""
        return self._fetch_gamecardfeed_raw(game_date=game_date_str)

    def apply_gamecardfeed_overlay_for_date(self, game_df: pd.DataFrame, game_date: date) -> pd.DataFrame:
        """Fetch the gamecardfeed for game_date and overlay live data onto the given DataFrame slice."""
        game_date_str = game_date.strftime("%m/%d/%Y")
        raw = self._fetch_gamecardfeed_for_date(game_date_str)
        live_games, _, _ = self._parse_gamecardfeed(raw)
        return self._apply_live_overlay(game_df, live_games)

    def get_scoreboard_date(self, season_year: str) -> date:
        """Return the current scoreboard date (today's NBA game date in Eastern time).

        For the current season this comes from the gamecardfeed; for historical seasons
        it falls back to date.today() since all games are already final.
        """
        if season_year == self.get_current_season():
            raw_gamecardfeed, _ = self._fetch_current_season_raw()
            _, _, scoreboard_date = self._parse_gamecardfeed(raw_gamecardfeed)
            return scoreboard_date
        return date.today()

    @ttl_cache(ttl_seconds=10)
    async def get_game_data(self, season_year: str) -> pd.DataFrame:
        """Get game data for a given season, combining current season live games with schedule if necessary.

        Args:
            season_year: Season string in format YYYY-YY

        Returns:
            DataFrame with game data including winning_team and losing_team columns
        """
        if season_year == self.get_current_season():
            return await asyncio.to_thread(self._build_current_schedule_df)
        else:
            season_type_dates = self._get_espn_season_type_dates(season_year)
            game_df = pd.DataFrame(await self.get_historical_schedule_cached(season_year, season_type_dates))
            return self._finalize_game_df(game_df)

    def _finalize_game_df(self, game_df: pd.DataFrame) -> pd.DataFrame:
        """Convert date_time to Eastern and add winning_team/losing_team columns."""
        game_df["date_time"] = pd.to_datetime(game_df["date_time"], format="ISO8601", utc=True).dt.tz_convert(
            "US/Eastern"
        )
        game_df["winning_team"] = game_df["home_team"].where(
            (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score > game_df.away_score),
            other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
        )
        game_df["losing_team"] = game_df["home_team"].where(
            (game_df.status == NBAGameStatus.FINAL) & (game_df.home_score < game_df.away_score),
            other=game_df["away_team"].where(game_df.status == NBAGameStatus.FINAL),
        )
        return game_df

    def get_fanduel_moneyline_odds(self) -> dict[str, dict[str, float]]:
        """Fetch vig-adjusted FanDuel moneyline win probabilities for today's games.

        Returns:
            Dict mapping game_id -> {"home": float, "away": float} win probabilities,
            or empty dict if the request fails.
        """
        url = "https://cdn.nba.com/static/json/liveData/odds/odds_todaysGames.json"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.warning("Failed to fetch FanDuel odds from %s", url, exc_info=True)
            return {}

        result = {}
        for game in data.get("games", []):
            game_id = str(game.get("gameId", ""))
            moneyline = next((m for m in game.get("markets", []) if m.get("name") == "2way"), None)
            if not moneyline:
                continue
            fanduel = next((b for b in moneyline.get("books", []) if b.get("name") == "FanDuel"), None)
            if not fanduel:
                continue
            outcomes = fanduel.get("outcomes", [])
            home_out = next((o for o in outcomes if o.get("type") == "home"), None)
            away_out = next((o for o in outcomes if o.get("type") == "away"), None)
            if not home_out or not away_out:
                continue
            home_odds = home_out.get("odds")
            away_odds = away_out.get("odds")
            if not home_odds or not away_odds:
                continue
            raw_home = 1 / float(home_odds)
            raw_away = 1 / float(away_odds)
            total = raw_home + raw_away
            result[game_id] = {"home": raw_home / total, "away": raw_away / total}

        return result

    @ttl_cache(ttl_seconds=10)
    def get_sportsbook_game_win_probabilities(self) -> dict[str, dict[str, float]]:
        """Fetch live vig-adjusted win probabilities from the FanDuel sportsbook API.

        Uses the sportsbook moneyline API (not CDN), so odds update during live games.

        Returns:
            Dict mapping gamecode (e.g. "20260503/ORLDET") -> {"home": float, "away": float},
            or empty dict if the request fails.
        """
        from nba_wins_pool.services.nba_vegas_projections_service import NBAVegasProjectionsService

        svc = NBAVegasProjectionsService(db_session=None, team_repository=None, nba_projections_repository=None)
        try:
            df = svc.get_game_win_probabilities()
        except Exception:
            logger.warning("Failed to fetch sportsbook game win probabilities", exc_info=True)
            return {}
        return {
            row["gamecode"]: {"home": row["home_win_prob"], "away": row["away_win_prob"]} for _, row in df.iterrows()
        }

    NBA_BRACKET_URL_TEMPLATE = "https://cdn.nba.com/static/json/staticData/brackets/{year}/{bracket}.json"

    def _fetch_bracket(self, season_year: str, bracket_name: str) -> dict:
        """Fetch a static bracket JSON from the NBA CDN."""
        year = season_year.split("-")[0]
        url = self.NBA_BRACKET_URL_TEMPLATE.format(year=year, bracket=bracket_name)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()

    def fetch_play_in_bracket(self, season_year: str) -> dict:
        """Fetch the NBA play-in bracket. *season_year* is YYYY-YY (e.g. '2024-25')."""
        return self._fetch_bracket(season_year, "PlayInBracket")

    def fetch_playoff_bracket(self, season_year: str) -> dict:
        """Fetch the NBA playoff bracket. *season_year* is YYYY-YY (e.g. '2024-25')."""
        return self._fetch_bracket(season_year, "PlayoffBracket")

    def get_schedule_with_odds(self) -> pd.DataFrame:
        """Fetch the current-season schedule with live status overlay and FanDuel CDN moneyline odds.

        Returns:
            DataFrame with all schedule columns plus home_win_prob and away_win_prob
            for games that have odds available (NaN otherwise).
        """
        game_df = self._build_current_schedule_df()

        odds = self.get_fanduel_moneyline_odds()
        if odds:
            odds_df = pd.DataFrame.from_dict(odds, orient="index").rename(
                columns={"home": "home_win_prob", "away": "away_win_prob"}
            )
            odds_df.index.name = "game_id"
            game_df = game_df.join(odds_df, on="game_id")
        else:
            game_df["home_win_prob"] = None
            game_df["away_win_prob"] = None

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
