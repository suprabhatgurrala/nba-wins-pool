from datetime import datetime
from decimal import Decimal

import requests
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.nba_projections import NBAProjectionsCreate
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.team_repository import TeamRepository, get_team_repository
from nba_wins_pool.services.nba_data_service import NbaDataService, get_nba_data_service
from nba_wins_pool.types.season_str import SeasonStr


class NBAEspnProjectionsService:
    """Service for fetching and parsing NBA projections from ESPN BPI."""

    # ESPN team abbreviation to NBA tricode mapping
    ESPN_TO_TRICODE = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}

    def __init__(self, db_session: AsyncSession, nba_data_service: NbaDataService, team_repository: TeamRepository):
        self.db_session = db_session
        self.nba_data_service = nba_data_service
        self.team_repository = team_repository

    def _fetch_espn_bpi_data(self):
        url = "https://site.api.espn.com/apis/fitt/v3/sports/basketball/nba/powerindex"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    def _prob_to_american(self, prob: float) -> int:
        """Convert a probability (0-100) to American betting odds."""
        if prob <= 0.04:
            return 250000
        if prob >= 100:
            return -250000

        p = prob / 100.0
        if p > 0.5:
            return round(-(p / (1 - p)) * 100)
        return round(((1 - p) / p) * 100)

    def _parse_espn_bpi_response(
        self, bpi_response: dict, current_season: SeasonStr, team_by_abbrev: dict[str, Team]
    ) -> list[NBAProjectionsCreate]:
        """Parse ESPN BPI API response and build NBAVegasData records using category labels."""
        cat_labels = {cat["name"]: cat.get("labels", []) for cat in bpi_response.get("categories", [])}

        # Get indices for required labels
        p_labels, ply_labels = cat_labels.get("projections", []), cat_labels.get("playoffs", [])
        w_idx = p_labels.index("ProjW") if "ProjW" in p_labels else None
        p_idx = p_labels.index("Playoffs%") if "Playoffs%" in p_labels else None
        conf_idx = ply_labels.index("Finals%") if "Finals%" in ply_labels else None
        title_idx = ply_labels.index("WinTitle%") if "WinTitle%" in ply_labels else None

        records = []
        for team_entry in bpi_response.get("teams", []):
            team_info = team_entry.get("team", {})
            espn_abbrev = team_info.get("abbreviation")

            tricode = self.ESPN_TO_TRICODE.get(espn_abbrev, espn_abbrev)
            team = team_by_abbrev.get(tricode)
            if not team:
                continue

            team_cats = {cat["name"]: cat for cat in team_entry.get("categories", [])}
            proj_vals = team_cats.get("projections", {}).get("values", [])
            play_vals = team_cats.get("playoffs", {}).get("values", [])

            if not proj_vals or w_idx is None or len(proj_vals) <= w_idx:
                continue

            last_updated = bpi_response.get("lastUpdated")
            fetched_at = datetime.fromisoformat(last_updated)

            records.append(
                NBAProjectionsCreate(
                    season=bpi_response["currentSeason"]["displayName"],
                    team_id=team.id,
                    team_name=team_info.get("displayName"),
                    fetched_at=fetched_at,
                    projection_date=fetched_at.date(),
                    reg_season_wins=Decimal(str(proj_vals[w_idx])),
                    make_playoffs_odds=self._prob_to_american(proj_vals[p_idx])
                    if p_idx is not None and len(proj_vals) > p_idx
                    else None,
                    win_conference_odds=self._prob_to_american(play_vals[conf_idx])
                    if conf_idx is not None and len(play_vals) > conf_idx
                    else None,
                    win_finals_odds=self._prob_to_american(play_vals[title_idx])
                    if title_idx is not None and len(play_vals) > title_idx
                    else None,
                    source="espn_bpi",
                )
            )
        return records

    async def write_projections(self, use_cached_data: dict = None):
        """Fetch and write ESPN BPI projections to the database."""
        if use_cached_data:
            response = use_cached_data
        else:
            response = self._fetch_espn_bpi_data()

        # Get context data
        current_season = self.nba_data_service.get_current_season()
        nba_teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        team_by_abbrev = {team.abbreviation: team for team in nba_teams}

        # Parse and build records
        records = self._parse_espn_bpi_response(response, current_season, team_by_abbrev)

        # Persist to database
        self.db_session.add_all(records)
        await self.db_session.commit()

        print(f"Successfully wrote {len(records)} ESPN BPI projections to the database")
        return len(records)


# Dependency injection
def get_auction_valuation_service(
    db_session: AsyncSession = Depends(get_db_session),
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
    team_repository: TeamRepository = Depends(get_team_repository),
) -> NBAEspnProjectionsService:
    """Get AuctionValuationService instance for dependency injection.

    Args:
        db_session: Database session

    Returns:
        AuctionValuationService instance with injected repositories
    """
    return NBAEspnProjectionsService(db_session, nba_data_service, team_repository)
