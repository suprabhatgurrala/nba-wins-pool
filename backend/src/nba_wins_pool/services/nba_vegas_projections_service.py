from datetime import datetime

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
from nba_wins_pool.services.nba_data_service import NbaDataService, get_nba_data_service
from nba_wins_pool.utils.time import utc_now


class NBAVegasProjectionsService:
    """Service for fetching NBA win projections from FanDuel."""

    # Constants for odds parsing
    MAKE_PLAYOFFS_SUFFIX = "To Make Playoffs"
    REG_SEASON_WINS_SUFFIX = "Regular Season Wins"
    CHAMPIONSHIP_SUFFIX = "NBA Finals Winner"

    # Default vig (2%), used to infer probabilities when only one side is provided
    DEFAULT_VIG = 0.02

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

    def __init__(
        self,
        db_session: AsyncSession,
        nba_data_service: NbaDataService,
        team_repository: TeamRepository,
        nba_projections_repository: NBAProjectionsRepository,
    ):
        self.db_session = db_session
        self.nba_data_service = nba_data_service
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

    def _convert_american_to_probability(self, american_odds: int) -> float:
        """Convert American odds to raw probability (including vig)."""
        if american_odds > 0:
            return 100 / (american_odds + 100)
        else:
            return abs(american_odds) / (abs(american_odds) + 100)

    def _parse_fanduel_response(
        self, odds_response: dict, fetched_at: datetime, team_by_abbrev: dict[str, Team]
    ) -> list[NBAProjectionsCreate]:
        """Parse FanDuel API response and directly build NBAProjectionsData records.

        Args:
            odds_response: Raw response from FanDuel API
            season: Current NBA season
            fetched_at: Timestamp when data was fetched
            team_by_abbrev: Mapping from team abbreviation to Team model

        Returns:
            List of NBAProjectionsData records ready to be persisted
        """
        attachments = odds_response.get("attachments", {})
        markets = attachments.get("markets", {})

        # Build team data map: team_name -> {field: value}
        team_data: dict[str, dict] = {}
        season = None

        for market in markets.values():
            market_type = market.get("marketType")
            market_name = market.get("marketName", "")

            if market_type == "NBA_REGULAR_SEASON_WINS_SGP":
                team_name = market_name.split(self.REG_SEASON_WINS_SUFFIX)[0].strip()
                team_data.setdefault(team_name, {})["team_name"] = team_name

                raw_probs = {}
                for runner in market.get("runners", []):
                    if runner.get("runnerStatus") != "ACTIVE":
                        continue

                    name = runner["runnerName"].lower()
                    american_odds = runner["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"]
                    raw_prob = self._convert_american_to_probability(american_odds)

                    if "over" in name:
                        win_total = float(name.removeprefix("over").removesuffix("wins").strip())
                        team_data[team_name]["reg_season_wins"] = win_total
                        team_data[team_name]["over_wins_odds"] = american_odds
                        raw_probs["over"] = raw_prob
                    elif "under" in name:
                        win_total = float(name.removeprefix("under").removesuffix("wins").strip())
                        team_data[team_name].setdefault("reg_season_wins", win_total)
                        team_data[team_name]["under_wins_odds"] = american_odds
                        raw_probs["under"] = raw_prob

                if "over" in raw_probs and "under" in raw_probs:
                    total_prob = raw_probs["over"] + raw_probs["under"]
                    team_data[team_name]["over_wins_prob"] = raw_probs["over"] / total_prob

            elif market_type == "NBA_TO_MAKE_PLAYOFFS":
                team_name = market_name.split(self.MAKE_PLAYOFFS_SUFFIX)[0].strip()
                team_data.setdefault(team_name, {})["team_name"] = team_name

                raw_probs = {}
                for runner in market.get("runners", []):
                    american_odds = runner["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"]
                    raw_prob = self._convert_american_to_probability(american_odds)

                    if runner["runnerName"] == "Yes":
                        team_data[team_name]["make_playoffs_odds"] = american_odds
                        raw_probs["yes"] = raw_prob
                    elif runner["runnerName"] == "No":
                        team_data[team_name]["miss_playoffs_odds"] = american_odds
                        raw_probs["no"] = raw_prob

                # Assume 2% vig (1.02 total raw prob) if one side is missing
                if "yes" in raw_probs and "no" not in raw_probs:
                    raw_probs["no"] = max(0, 1 + self.DEFAULT_VIG - raw_probs["yes"])
                elif "no" in raw_probs and "yes" not in raw_probs:
                    raw_probs["yes"] = max(0, 1 + self.DEFAULT_VIG - raw_probs["no"])

                if "yes" in raw_probs and "no" in raw_probs:
                    total_prob = raw_probs["yes"] + raw_probs["no"]
                    if total_prob > 0:
                        team_data[team_name]["make_playoffs_prob"] = raw_probs["yes"] / total_prob

            elif market_type == "NBA_CONFERENCE_WINNER":
                market_runners = []
                for runner in market.get("runners", []):
                    if runner.get("runnerStatus") != "ACTIVE":
                        continue
                    team_name = runner["runnerName"]
                    american_odds = runner["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"]
                    raw_prob = self._convert_american_to_probability(american_odds)
                    market_runners.append({"team_name": team_name, "raw_prob": raw_prob, "odds": american_odds})

                if market_runners:
                    total_raw_prob = sum(r["raw_prob"] for r in market_runners)
                    for r in market_runners:
                        t_name = r["team_name"]
                        team_data.setdefault(t_name, {})["team_name"] = t_name
                        team_data[t_name]["win_conference_odds"] = r["odds"]
                        team_data[t_name]["win_conference_prob"] = r["raw_prob"] / total_raw_prob

            elif market_type == "NBA_CHAMPIONSHIP":
                season = market_name.removesuffix(self.CHAMPIONSHIP_SUFFIX).strip()
                market_runners = []
                for runner in market.get("runners", []):
                    if runner.get("runnerStatus") != "ACTIVE":
                        continue
                    team_name = runner["runnerName"]
                    american_odds = runner["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"]
                    raw_prob = self._convert_american_to_probability(american_odds)
                    market_runners.append({"team_name": team_name, "raw_prob": raw_prob, "odds": american_odds})

                if market_runners:
                    total_raw_prob = sum(r["raw_prob"] for r in market_runners)
                    for r in market_runners:
                        t_name = r["team_name"]
                        team_data.setdefault(t_name, {})["team_name"] = t_name
                        team_data[t_name]["win_finals_odds"] = r["odds"]
                        team_data[t_name]["win_finals_prob"] = r["raw_prob"] / total_raw_prob

        # Build NBAProjectionsData records
        records = []
        for team_name, data in team_data.items():
            # Map team name to tricode
            tricode = self.FANDUEL_TO_TRICODE.get(team_name)
            if not tricode:
                print(f"Warning: No tricode mapping for team: {team_name}")
                continue

            # Get team from database
            team = team_by_abbrev.get(tricode)
            if not team:
                print(f"Warning: No team in database for tricode: {tricode}")
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
                    win_conference_odds=data.get("win_conference_odds"),
                    win_finals_odds=data.get("win_finals_odds"),
                    over_wins_prob=data.get("over_wins_prob"),
                    make_playoffs_prob=data.get("make_playoffs_prob"),
                    win_conference_prob=data.get("win_conference_prob"),
                    win_finals_prob=data.get("win_finals_prob"),
                    source="fanduel",
                )
            )

        return records

    async def write_projections(self):
        """Fetch and write FanDuel projections to the database."""
        response = self._fetch_fanduel_data()

        # Get context data
        fetched_at = utc_now()
        nba_teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        team_by_abbrev = {team.abbreviation: team for team in nba_teams}

        # Parse and build records
        records = self._parse_fanduel_response(response, fetched_at, team_by_abbrev)

        # Persist to database using repository upsert
        for record in records:
            await self.nba_projections_repository.upsert(record, update_if_exists=True)

        await self.db_session.commit()

        print(f"Successfully wrote {len(records)} FanDuel projections to the database")
        return len(records)


# Dependency injection
def get_nba_vegas_projections_service(
    db_session: AsyncSession = Depends(get_db_session),
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
    team_repository: TeamRepository = Depends(get_team_repository),
    nba_projections_repository: NBAProjectionsRepository = Depends(get_nba_projections_repository),
) -> NBAVegasProjectionsService:
    """Get NBAVegasProjectionsService instance for dependency injection.

    Args:
        db_session: Database session

    Returns:
        NBAVegasProjectionsService instance with injected repositories
    """
    return NBAVegasProjectionsService(db_session, nba_data_service, team_repository, nba_projections_repository)
