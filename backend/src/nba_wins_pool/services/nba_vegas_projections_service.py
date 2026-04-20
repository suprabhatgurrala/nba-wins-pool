import logging
from datetime import datetime

import pandas as pd
import requests
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.nba_projections import NBAProjectionsCreate
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.nba_projections_repository import (
    NBAProjectionsRepository,
    get_nba_projections_repository,
)
from nba_wins_pool.repositories.team_repository import TeamRepository, get_team_repository
from nba_wins_pool.utils.time import utc_now

logger = logging.getLogger(__name__)


class NBAVegasProjectionsService:
    """Service for fetching NBA win projections from FanDuel."""

    # Constants for odds parsing
    MAKE_PLAYOFFS_SUFFIX = "To Make Playoffs"
    REG_SEASON_WINS_SUFFIX = "Regular Season Wins"
    CHAMPIONSHIP_SUFFIX = "NBA Finals Winner"
    CONF_FINALS_SUBSTR = "Conference Finals"
    CONF_SEMIS_SUBSTR = "Conference Semifinals"

    # Default vig (2%), used to infer probabilities when only one side is provided
    DEFAULT_VIG = 0.02

    # Team name to NBA tricode mapping (handles naming variations)
    TEAM_NAME_TO_TRICODE = {
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

    def __init__(
        self,
        db_session: AsyncSession,
        team_repository: TeamRepository,
        nba_projections_repository: NBAProjectionsRepository,
    ):
        self.db_session = db_session
        self.team_repository = team_repository
        self.nba_projections_repository = nba_projections_repository

    def _fetch_fanduel_data(self):
        """Fetches raw odds from FanDuel API"""
        response = requests.get(
            "https://api.sportsbook.fanduel.com/sbapi/content-managed-page",
            params={
                "page": "CUSTOM",
                "customPageId": "nba",
                "pbHorizontal": "false",
                "_ak": "FhMFpcPWXMeyZxOx",
                "timezone": "America/New_York",
            },
            headers={
                "X-Sportsbook-Region": "NJ",
                "sec-ch-ua-platform": '"Windows"',
                "Referer": "https://sportsbook.fanduel.com/",
                "sec-ch-ua": '"Not;A=Brand";v="99", "Brave";v="139", "Chromium";v="139"',
                "sec-ch-ua-mobile": "?0",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _fetch_fanduel_futures_data(self):
        """Fetches raw futures odds from FanDuel competition-page API."""
        response = requests.get(
            "https://api.sportsbook.fanduel.com/sbapi/competition-page",
            params={
                "_ak": "FhMFpcPWXMeyZxOx",
                "eventTypeId": "7522",
                "competitionId": "12739957",
                "tabId": "FUTURES",
            },
            headers={
                "accept": "application/json",
                "accept-language": "en-US,en;q=0.8",
                "origin": "https://sportsbook.fanduel.com",
                "referer": "https://sportsbook.fanduel.com/",
                "sec-ch-ua": '"Brave";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "sec-gpc": "1",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                "x-sportsbook-region": "NJ",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _convert_american_to_probability(self, american_odds: int) -> float:
        """Convert American odds to raw probability (including vig)."""
        if american_odds > 0:
            return 100 / (american_odds + 100)
        else:
            return abs(american_odds) / (abs(american_odds) + 100)

    def _active_runners(self, market: dict) -> list[tuple[str, int, float]]:
        """Return (team_name, american_odds, raw_prob) for each active runner in a market."""
        result = []
        for r in market.get("runners", []):
            if r.get("runnerStatus") != "ACTIVE":
                continue
            odds = r["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"]
            result.append((r["runnerName"], odds, self._convert_american_to_probability(odds)))
        return result

    def _collect_markets(
        self,
        markets: dict,
        team_data: dict[str, dict],
        playoff_round_lookup: dict[frozenset, int] | None = None,
    ) -> str | None:
        """Populate team_data in-place from a markets dict.

        Returns the season string if found, else None.
        Markets already in team_data are overwritten, so call with the
        higher-priority source last.
        """
        season = None

        for market in markets.values():
            market_type = market.get("marketType", "")
            market_name = market.get("marketName", "")

            if market_type == "NBA_REGULAR_SEASON_WINS_SGP":
                team_name = market_name.split(self.REG_SEASON_WINS_SUFFIX)[0].strip()
                team_data.setdefault(team_name, {})
                over_prob = under_prob = None
                for name, odds, raw_prob in self._active_runners(market):
                    n = name.lower()
                    if "over" in n:
                        win_total = float(n.removeprefix("over").removesuffix("wins").strip())
                        team_data[team_name]["reg_season_wins"] = win_total
                        team_data[team_name]["over_wins_odds"] = odds
                        over_prob = raw_prob
                    elif "under" in n:
                        win_total = float(n.removeprefix("under").removesuffix("wins").strip())
                        team_data[team_name].setdefault("reg_season_wins", win_total)
                        team_data[team_name]["under_wins_odds"] = odds
                        under_prob = raw_prob
                if over_prob is not None and under_prob is not None:
                    team_data[team_name]["over_wins_prob"] = over_prob / (over_prob + under_prob)

            elif market_type == "NBA_TO_MAKE_PLAYOFFS":
                team_name = market_name.split(self.MAKE_PLAYOFFS_SUFFIX)[0].strip()
                team_data.setdefault(team_name, {})
                yes_prob = no_prob = None
                for name, odds, raw_prob in self._active_runners(market):
                    if name == "Yes":
                        team_data[team_name]["make_playoffs_odds"] = odds
                        yes_prob = raw_prob
                    elif name == "No":
                        team_data[team_name]["miss_playoffs_odds"] = odds
                        no_prob = raw_prob
                if yes_prob is not None and no_prob is None:
                    no_prob = max(0.0, 1 + self.DEFAULT_VIG - yes_prob)
                elif no_prob is not None and yes_prob is None:
                    yes_prob = max(0.0, 1 + self.DEFAULT_VIG - no_prob)
                if yes_prob is not None and no_prob is not None and (yes_prob + no_prob) > 0:
                    team_data[team_name]["make_playoffs_prob"] = yes_prob / (yes_prob + no_prob)

            elif market_type == "NBA_ADVANCE_TO_X_ROUND":
                if self.CONF_SEMIS_SUBSTR in market_name:
                    odds_key, prob_key, n_winners = "reach_conf_semis_odds", "reach_conf_semis_prob", 4
                elif self.CONF_FINALS_SUBSTR in market_name:
                    odds_key, prob_key, n_winners = "reach_conf_finals_odds", "reach_conf_finals_prob", 2
                else:
                    continue
                runners = self._active_runners(market)
                if runners:
                    total = sum(p for _, _, p in runners)
                    for team_name, odds, raw_prob in runners:
                        team_data.setdefault(team_name, {})[odds_key] = odds
                        team_data[team_name][prob_key] = raw_prob / total * n_winners

            elif market_type in (
                "TO_ADVANCE_TO_CONFERENCE_SEMIFINALS_-_EAST",
                "TO_ADVANCE_TO_CONFERENCE_SEMIFINALS_-_WEST",
            ):
                runners = self._active_runners(market)
                if runners:
                    total = sum(p for _, _, p in runners)
                    for team_name, odds, raw_prob in runners:
                        team_data.setdefault(team_name, {})["reach_conf_semis_odds"] = odds
                        team_data[team_name]["reach_conf_semis_prob"] = raw_prob / total * 4

            elif market_type in (
                "TO_ADVANCE_TO_CONFERENCE_FINALS_-_EAST",
                "TO_ADVANCE_TO_CONFERENCE_FINALS_-_WEST",
            ):
                runners = self._active_runners(market)
                if runners:
                    total = sum(p for _, _, p in runners)
                    for team_name, odds, raw_prob in runners:
                        team_data.setdefault(team_name, {})["reach_conf_finals_odds"] = odds
                        team_data[team_name]["reach_conf_finals_prob"] = raw_prob / total * 2

            elif market_type == "NBA_CONFERENCE_WINNER":
                runners = self._active_runners(market)
                if runners:
                    total = sum(p for _, _, p in runners)
                    for team_name, odds, raw_prob in runners:
                        team_data.setdefault(team_name, {})["win_conference_odds"] = odds
                        team_data[team_name]["win_conference_prob"] = raw_prob / total

            elif market_type == "NBA_CHAMPIONSHIP":
                season = market_name.removesuffix(self.CHAMPIONSHIP_SUFFIX).strip() or season
                runners = self._active_runners(market)
                if runners:
                    total = sum(p for _, _, p in runners)
                    for team_name, odds, raw_prob in runners:
                        team_data.setdefault(team_name, {})["win_finals_odds"] = odds
                        team_data[team_name]["win_finals_prob"] = raw_prob / total

            elif market_type == "SERIES_BETTING_OBP" and playoff_round_lookup:
                runners = self._active_runners(market)
                if len(runners) != 2:
                    continue
                tricode_a = self.TEAM_NAME_TO_TRICODE.get(runners[0][0])
                tricode_b = self.TEAM_NAME_TO_TRICODE.get(runners[1][0])
                if not tricode_a or not tricode_b:
                    continue
                round_num = playoff_round_lookup.get(frozenset([tricode_a, tricode_b]))
                fields = (
                    {
                        1: ("reach_conf_semis_odds", "reach_conf_semis_prob"),
                        2: ("reach_conf_finals_odds", "reach_conf_finals_prob"),
                        3: ("win_conference_odds", "win_conference_prob"),
                        4: ("win_finals_odds", "win_finals_prob"),
                    }.get(round_num)
                    if round_num
                    else None
                )
                if not fields:
                    continue
                odds_key, prob_key = fields
                total = sum(p for _, _, p in runners)
                for team_name, odds, raw_prob in runners:
                    team_data.setdefault(team_name, {})[odds_key] = odds
                    team_data[team_name][prob_key] = raw_prob / total

        return season

    def _build_records(
        self,
        team_data: dict[str, dict],
        season: str | None,
        fetched_at: datetime,
        team_by_abbrev: dict[str, Team],
    ) -> list[NBAProjectionsCreate]:
        """Build NBAProjectionsCreate records from a merged team_data dict."""
        records = []
        for team_name, data in team_data.items():
            tricode = self.TEAM_NAME_TO_TRICODE.get(team_name)
            if not tricode:
                logger.warning("No tricode mapping for team: %s", team_name)
                continue
            team = team_by_abbrev.get(tricode)
            if not team:
                logger.warning("No team in database for tricode: %s", tricode)
                continue
            records.append(
                NBAProjectionsCreate(
                    season=season,
                    projection_date=fetched_at.date(),
                    team_id=team.id,
                    team_name=team_name,
                    fetched_at=fetched_at,
                    reg_season_wins=data.get("reg_season_wins"),
                    over_wins_odds=data.get("over_wins_odds"),
                    under_wins_odds=data.get("under_wins_odds"),
                    make_playoffs_odds=data.get("make_playoffs_odds"),
                    miss_playoffs_odds=data.get("miss_playoffs_odds"),
                    reach_conf_semis_odds=data.get("reach_conf_semis_odds"),
                    reach_conf_finals_odds=data.get("reach_conf_finals_odds"),
                    win_conference_odds=data.get("win_conference_odds"),
                    win_finals_odds=data.get("win_finals_odds"),
                    over_wins_prob=data.get("over_wins_prob"),
                    make_playoffs_prob=data.get("make_playoffs_prob"),
                    reach_conf_semis_prob=data.get("reach_conf_semis_prob"),
                    reach_conf_finals_prob=data.get("reach_conf_finals_prob"),
                    win_conference_prob=data.get("win_conference_prob"),
                    win_finals_prob=data.get("win_finals_prob"),
                    source="fanduel",
                )
            )
        return records

    def parse_fanduel_responses(
        self,
        standard_response: dict,
        futures_response: dict,
        fetched_at: datetime,
        team_by_abbrev: dict[str, Team],
        playoff_round_lookup: dict[frozenset, int] | None = None,
    ) -> list[NBAProjectionsCreate]:
        """Merge and parse both FanDuel API responses into one set of records.

        Standard response is processed first (regular season + make playoffs odds).
        Futures response is processed second and overwrites overlapping playoff fields
        with the more specific futures-page odds.
        """
        team_data: dict[str, dict] = {}
        season = self._collect_markets(
            standard_response.get("attachments", {}).get("markets", {}),
            team_data,
        )
        season = (
            self._collect_markets(
                futures_response.get("attachments", {}).get("markets", {}),
                team_data,
                playoff_round_lookup=playoff_round_lookup,
            )
            or season
        )
        return self._build_records(team_data, season, fetched_at, team_by_abbrev)

    def get_game_win_probabilities(self, odds_response: dict | None = None) -> pd.DataFrame:
        """Parse MONEY_LINE markets from FanDuel and return vig-adjusted win probabilities.

        Args:
            odds_response: Raw FanDuel API response. Fetches fresh data if not provided.

        Returns:
            DataFrame with columns: game_date, away_tricode, home_tricode,
            away_win_prob, home_win_prob
        """
        if odds_response is None:
            odds_response = self._fetch_fanduel_data()

        markets = odds_response.get("attachments", {}).get("markets", {})

        rows = []
        for market in markets.values():
            if market.get("marketType") != "MONEY_LINE":
                continue

            runners = [r for r in market.get("runners", []) if r.get("runnerStatus") == "ACTIVE"]
            if len(runners) != 2:
                continue

            home_runner = next((r for r in runners if r.get("result", {}).get("type") == "HOME"), None)
            away_runner = next((r for r in runners if r.get("result", {}).get("type") == "AWAY"), None)
            if not home_runner or not away_runner:
                continue

            home_tricode = self.TEAM_NAME_TO_TRICODE.get(home_runner["runnerName"])
            away_tricode = self.TEAM_NAME_TO_TRICODE.get(away_runner["runnerName"])
            if not home_tricode or not away_tricode:
                continue

            home_odds = home_runner["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"]
            away_odds = away_runner["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"]

            home_raw = self._convert_american_to_probability(home_odds)
            away_raw = self._convert_american_to_probability(away_odds)
            total = home_raw + away_raw

            game_date = datetime.fromisoformat(market["marketTime"].replace("Z", "+00:00")).date()

            gamecode = f"{game_date.strftime('%Y%m%d')}/{away_tricode}{home_tricode}"

            rows.append(
                {
                    "game_date": game_date,
                    "gamecode": gamecode,
                    "away_tricode": away_tricode,
                    "home_tricode": home_tricode,
                    "away_win_prob": away_raw / total,
                    "home_win_prob": home_raw / total,
                }
            )

        return pd.DataFrame(
            rows, columns=["game_date", "gamecode", "away_tricode", "home_tricode", "away_win_prob", "home_win_prob"]
        )

    async def write_projections(self):
        """Fetch both FanDuel endpoints, merge into one record per team, and persist."""
        standard_response = self._fetch_fanduel_data()
        futures_response = self._fetch_fanduel_futures_data()

        fetched_at = utc_now()
        nba_teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        team_by_abbrev = {team.abbreviation: team for team in nba_teams}

        records = self.parse_fanduel_responses(standard_response, futures_response, fetched_at, team_by_abbrev)
        logger.info("Parsed %d FanDuel projection records", len(records))

        for record in records:
            await self.nba_projections_repository.upsert(record, update_if_exists=True)

        await self.db_session.commit()
        logger.info("FanDuel write complete: %d records", len(records))
        return len(records)


# Dependency injection
def get_nba_vegas_projections_service(
    db_session: AsyncSession = Depends(get_db_session),
    team_repository: TeamRepository = Depends(get_team_repository),
    nba_projections_repository: NBAProjectionsRepository = Depends(get_nba_projections_repository),
) -> NBAVegasProjectionsService:
    return NBAVegasProjectionsService(db_session, team_repository, nba_projections_repository)
