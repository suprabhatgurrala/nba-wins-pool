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


class NBAEspnProjectionsService:
    """Service for fetching and parsing NBA projections from ESPN BPI."""

    # ESPN team abbreviation to NBA tricode mapping
    ESPN_TO_TRICODE = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}

    def __init__(
        self,
        db_session: AsyncSession,
        team_repository: TeamRepository,
        nba_projections_repository: NBAProjectionsRepository,
    ):
        self.db_session = db_session
        self.team_repository = team_repository
        self.nba_projections_repository = nba_projections_repository

    def _fetch_espn_bpi_data(self):
        url = "https://site.api.espn.com/apis/fitt/v3/sports/basketball/nba/powerindex"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    def _parse_espn_bpi_response(
        self, bpi_response: dict, team_by_abbrev: dict[str, Team]
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
            fetched_at = datetime.fromisoformat(last_updated).replace(tzinfo=None)

            records.append(
                NBAProjectionsCreate(
                    season=bpi_response["currentSeason"]["displayName"],
                    team_id=team.id,
                    team_name=team_info.get("displayName"),
                    fetched_at=fetched_at,
                    projection_date=fetched_at.date(),
                    reg_season_wins=float(proj_vals[w_idx]),
                    make_playoffs_prob=float(proj_vals[p_idx]) / 100.0
                    if p_idx is not None and len(proj_vals) > p_idx
                    else None,
                    win_conference_prob=float(play_vals[conf_idx]) / 100.0
                    if conf_idx is not None and len(play_vals) > conf_idx
                    else None,
                    win_finals_prob=float(play_vals[title_idx]) / 100.0
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
        nba_teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        team_by_abbrev = {team.abbreviation: team for team in nba_teams}

        # Parse and build records
        records = self._parse_espn_bpi_response(response, team_by_abbrev)

        # Persist to database using repository upsert
        for record in records:
            await self.nba_projections_repository.upsert(record, update_if_exists=True)

        await self.db_session.commit()

        print(f"Successfully wrote {len(records)} ESPN BPI projections to the database")
        return len(records)


# Dependency injection
def get_nba_espn_projections_service(
    db_session: AsyncSession = Depends(get_db_session),
    team_repository: TeamRepository = Depends(get_team_repository),
    nba_projections_repository: NBAProjectionsRepository = Depends(get_nba_projections_repository),
) -> NBAEspnProjectionsService:
    """Get NBAEspnProjectionsService instance for dependency injection.

    Args:
        db_session: Database session

    Returns:
        NBAEspnProjectionsService instance with injected repositories
    """
    return NBAEspnProjectionsService(db_session, team_repository, nba_projections_repository)
