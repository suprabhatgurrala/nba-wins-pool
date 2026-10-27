import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.projection import ProjectionMarket, QuoteCreate
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.projection_repository import (
    ESPN_BPI,
    ProjectionRepository,
    get_projection_repository,
)
from nba_wins_pool.repositories.team_repository import TeamRepository, get_team_repository

logger = logging.getLogger(__name__)


@dataclass
class ParsedEspnProjections:
    """One ESPN BPI update: its season, ESPN's own update time, and its quotes."""

    season: str
    fetched_at: datetime
    quotes: list[QuoteCreate]


class NBAEspnProjectionsService:
    """Service for fetching and parsing NBA projections from ESPN BPI."""

    # ESPN team abbreviation to NBA tricode mapping
    ESPN_TO_TRICODE = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}

    def __init__(
        self,
        db_session: AsyncSession,
        team_repository: TeamRepository,
        projection_repository: ProjectionRepository,
    ):
        self.db_session = db_session
        self.team_repository = team_repository
        self.projection_repository = projection_repository

    def _fetch_espn_bpi_data(self):
        url = "https://site.api.espn.com/apis/fitt/v3/sports/basketball/nba/powerindex"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    def _parse_espn_bpi_response(self, bpi_response: dict, team_by_abbrev: dict[str, Team]) -> ParsedEspnProjections:
        """Parse an ESPN BPI response into quotes, using its category labels to find each value."""
        cat_labels = {cat["name"]: cat.get("labels", []) for cat in bpi_response.get("categories", [])}
        b_labels = cat_labels.get("bpi", [])
        p_labels, ply_labels = cat_labels.get("projections", []), cat_labels.get("playoffs", [])
        columns = [
            (ProjectionMarket.ESPN_BPI, "bpi", b_labels, "BPI", "line"),
            (ProjectionMarket.ESPN_PLAYOFF_BPI, "bpi", b_labels, "PBPI", "line"),
            (ProjectionMarket.MAKE_PLAYOFFS, "projections", p_labels, "Playoffs%", "prob"),
            (ProjectionMarket.WIN_CONF, "playoffs", ply_labels, "Finals%", "prob"),
            (ProjectionMarket.WIN_TITLE, "playoffs", ply_labels, "WinTitle%", "prob"),
        ]
        w_idx = p_labels.index("ProjW") if "ProjW" in p_labels else None

        quotes = []
        for team_entry in bpi_response.get("teams", []):
            team_info = team_entry.get("team", {})
            espn_abbrev = team_info.get("abbreviation")
            team = team_by_abbrev.get(self.ESPN_TO_TRICODE.get(espn_abbrev, espn_abbrev))
            if not team:
                continue

            team_values = {cat["name"]: cat.get("values", []) for cat in team_entry.get("categories", [])}
            proj_vals = team_values.get("projections", [])
            if w_idx is None or len(proj_vals) <= w_idx:
                continue
            quotes.append(QuoteCreate(team_id=team.id, market=ProjectionMarket.ESPN_WINS, line=float(proj_vals[w_idx])))
            for market, category, labels, label, field in columns:
                vals = team_values.get(category, [])
                idx = labels.index(label) if label in labels else None
                if idx is None or len(vals) <= idx or vals[idx] is None:
                    continue
                value = float(vals[idx]) / 100.0 if field == "prob" else float(vals[idx])
                quotes.append(QuoteCreate(team_id=team.id, market=market, **{field: value}))

        updated = datetime.fromisoformat(bpi_response["lastUpdated"].replace("Z", "+00:00"))
        if updated.tzinfo is not None:
            updated = updated.astimezone(timezone.utc).replace(tzinfo=None)
        return ParsedEspnProjections(
            season=bpi_response["currentSeason"]["displayName"], fetched_at=updated, quotes=quotes
        )

    async def write_projections(self, use_cached_data: dict = None):
        """Fetch ESPN BPI and store it as a fetch, unless this ESPN update is already stored."""
        response = use_cached_data or self._fetch_espn_bpi_data()

        nba_teams = await self.team_repository.get_all_by_league_slug(LeagueSlug.NBA)
        team_by_abbrev = {team.abbreviation: team for team in nba_teams}
        parsed = self._parse_espn_bpi_response(response, team_by_abbrev)

        if await self.projection_repository.has_fetch(ESPN_BPI, parsed.season, parsed.fetched_at):
            logger.info("ESPN BPI update from %s already stored", parsed.fetched_at)
            return 0
        await self.projection_repository.add_fetch(ESPN_BPI, parsed.season, parsed.fetched_at, parsed.quotes)
        await self.db_session.commit()

        logger.info("Wrote %d ESPN BPI quotes", len(parsed.quotes))
        return len(parsed.quotes)


# Dependency injection
def get_nba_espn_projections_service(
    db_session: AsyncSession = Depends(get_db_session),
    team_repository: TeamRepository = Depends(get_team_repository),
    projection_repository: ProjectionRepository = Depends(get_projection_repository),
) -> NBAEspnProjectionsService:
    """Get NBAEspnProjectionsService instance for dependency injection.

    Args:
        db_session: Database session

    Returns:
        NBAEspnProjectionsService instance with injected repositories
    """
    return NBAEspnProjectionsService(db_session, team_repository, projection_repository)
