#!/usr/bin/env python3
"""
Simplified seed data script for NBA Wins Pool database.
Centralized data loading with minimal redundancy.
"""

import argparse
import asyncio
import csv
import json
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import engine
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.models.pool_season import PoolSeason
from nba_wins_pool.models.projection import ProjectionMarket, QuoteCreate
from nba_wins_pool.models.roster import Roster
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.pool_repository import PoolRepository
from nba_wins_pool.repositories.pool_season_repository import PoolSeasonRepository
from nba_wins_pool.repositories.projection_repository import ProjectionRepository
from nba_wins_pool.repositories.roster_repository import RosterRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.scripts.pool_seasons import PoolSeasonRecord, is_file_owned, load_pool_seasons
from nba_wins_pool.scripts.schedule_fixtures import fixture_path, load_fixture
from nba_wins_pool.scripts.seed_auctions import SlotSpec, seed_auctions
from nba_wins_pool.services.nba_data_service import NbaDataService, schedule_cache_key

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed_data")


@dataclass
class SeedFetch:
    """One fetch's worth of rows from the projections CSV."""

    source: str
    season: str
    fetched_at: datetime
    quotes: List[QuoteCreate]


class SeedData:
    """Centralized data loader and cache."""

    def __init__(self):
        self.data_dir = Path(__file__).parent / "data"
        self._teams = None
        self._roster_slots = None
        self._team_abbr_to_id = {}
        self._team_abbr_to_name = {}
        self._nba_projections = None
        self._pool_seasons = None

    def load_teams(self) -> List[Dict]:
        """Load NBA teams from JSON (cached)."""
        if self._teams is None:
            file_path = self.data_dir / "nba_teams.json"
            with open(file_path, encoding="utf-8") as f:
                self._teams = json.load(f)
            logger.info(f"Loaded {len(self._teams)} teams")
        return self._teams

    def load_roster_slots(self) -> List[Dict]:
        """Load roster slots from CSV (cached)."""
        if self._roster_slots is None:
            file_path = self.data_dir / "rosters.csv"
            self._roster_slots = []
            with open(file_path, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    self._roster_slots.append(
                        {
                            "pool": row["pool"],
                            "season": row["season"],
                            "roster": row["roster"],
                            "team": row["team"],
                            "price": Decimal(row["auction_price"]),
                        }
                    )
            logger.info(f"Loaded {len(self._roster_slots)} roster slots")
        return self._roster_slots

    def load_pool_seasons(self) -> Dict[tuple, PoolSeasonRecord]:
        """Load per pool season history (auction time, valuation date, rules) from JSON (cached)."""
        if self._pool_seasons is None:
            self._pool_seasons = load_pool_seasons(self.data_dir / "pool_seasons.json")
            logger.info(f"Loaded {len(self._pool_seasons)} pool season records")
        return self._pool_seasons

    def get_auction_slots(self, pool_filter: Optional[str] = None) -> Dict[tuple, Dict[str, List[SlotSpec]]]:
        """Teams each owner won, by (pool, season) then roster name, with the team IDs resolved."""
        wanted: Dict[tuple, Dict[str, List[SlotSpec]]] = {}
        for slot in self.load_roster_slots():
            if pool_filter and slot["pool"] != pool_filter:
                continue
            team_id = self.get_team_id(slot["team"])
            if not team_id:
                logger.warning(f"Team '{slot['team']}' not found")
                continue
            owners = wanted.setdefault((slot["pool"], slot["season"]), {})
            owners.setdefault(slot["roster"], []).append(SlotSpec(team_id=team_id, auction_price=slot["price"]))
        return wanted

    def get_pools(self) -> List[Dict]:
        """Extract unique pools from roster data."""
        slots = self.load_roster_slots()
        pools = {}
        for slot in slots:
            slug = slot["pool"]
            if slug not in pools:
                pools[slug] = {"slug": slug, "name": slug.upper()}
        return list(pools.values())

    def get_seasons(self) -> List[Dict]:
        """Extract unique (pool, season) combinations."""
        slots = self.load_roster_slots()
        seasons = {}
        for slot in slots:
            key = (slot["pool"], slot["season"])
            if key not in seasons:
                seasons[key] = {"pool": slot["pool"], "season": slot["season"]}
        return list(seasons.values())

    def set_team_mapping(self, id_mapping: Dict[str, uuid.UUID], name_mapping: Dict[str, str]):
        """Cache team abbreviation to ID and name mapping."""
        self._team_abbr_to_id = id_mapping
        self._team_abbr_to_name = name_mapping

    def get_team_id(self, abbreviation: str) -> uuid.UUID:
        """Get team ID by abbreviation."""
        return self._team_abbr_to_id.get(abbreviation)

    def get_team_name(self, abbreviation: str) -> str:
        """Get team name by abbreviation."""
        return self._team_abbr_to_name.get(abbreviation, abbreviation)

    @staticmethod
    def get_optional_int(value: str) -> Optional[int]:
        # Convert empty strings to None for optional fields
        return int(value) if value and value.strip() else None

    @staticmethod
    def get_optional_float(value: str) -> Optional[float]:
        # Convert empty strings to None for optional fields
        return float(value) if value and value.strip() else None

    async def load_nba_projections(self) -> List[SeedFetch]:
        """Load NBA projections from CSV (cached): one fetch per source, season and date, at midnight."""
        if self._nba_projections is None:
            file_path = self.data_dir / "nba_projections.csv"
            if not self._team_abbr_to_id:
                await seed_teams(self)

            fetches: Dict[tuple, SeedFetch] = {}
            with open(file_path, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    projection_date = datetime.strptime(row["projection_date"], "%Y-%m-%d").date()
                    source = row.get("source") or "unknown"
                    fetched_at = datetime.combine(projection_date, time.min)
                    key = (source, row["season"], fetched_at)
                    fetch = fetches.setdefault(key, SeedFetch(source, row["season"], fetched_at, []))
                    fetch.quotes.extend(self._csv_quotes(row))
            self._nba_projections = list(fetches.values())
            logger.info(f"Loaded {len(self._nba_projections)} projection fetches")
        return self._nba_projections

    def _csv_quotes(self, row: Dict[str, str]) -> List[QuoteCreate]:
        """The quotes in one wide CSV row, skipping markets it leaves blank."""
        team_id = self.get_team_id(row["abbreviation"])
        quotes = []
        line = self.get_optional_float(row.get("reg_season_wins"))
        if line is not None:
            quotes.append(
                QuoteCreate(
                    team_id=team_id,
                    market=ProjectionMarket.WIN_TOTAL,
                    line=line,
                    prob=self.get_optional_float(row.get("over_wins_prob")),
                    odds=self.get_optional_int(row.get("over_wins_odds")),
                    opp_odds=self.get_optional_int(row.get("under_wins_odds")),
                )
            )
        for market, prefix, opp_column in (
            (ProjectionMarket.MAKE_PLAYOFFS, "make_playoffs", "miss_playoffs_odds"),
            (ProjectionMarket.WIN_CONF, "win_conference", None),
            (ProjectionMarket.WIN_TITLE, "win_finals", None),
        ):
            prob = self.get_optional_float(row.get(f"{prefix}_prob"))
            odds = self.get_optional_int(row.get(f"{prefix}_odds"))
            if prob is None and odds is None:
                continue
            opp_odds = self.get_optional_int(row.get(opp_column)) if opp_column else None
            quotes.append(QuoteCreate(team_id=team_id, market=market, prob=prob, odds=odds, opp_odds=opp_odds))
        return quotes


async def seed_teams(data: SeedData) -> bool:
    """Seed NBA teams, updating existing ones to match nba_teams.json."""
    logger.info("Seeding teams...")
    teams_data = data.load_teams()

    async with AsyncSession(engine) as session:
        repo = TeamRepository(session)
        existing = await repo.get_all_by_league_slug(LeagueSlug.NBA)
        existing_by_external_id = {team.external_id: team for team in existing}

        logger.info(f"{'Updating' if existing else 'Creating'} teams...")

        # Create or update teams
        teams_to_save = []
        for td in teams_data:
            external_id = str(td["nba_id"])
            team = existing_by_external_id.get(external_id)

            if team:  # Update existing team
                team.name = td["name"]
                team.abbreviation = td["abbreviation"]
                team.logo_url = td["logo_url"]
                team.conference = td["conference"]
                team.division = td.get("division")
            else:  # Create new team
                team = Team(
                    external_id=external_id,
                    name=td["name"],
                    abbreviation=td["abbreviation"],
                    conference=td["conference"],
                    division=td.get("division"),
                    logo_url=td["logo_url"],
                    league_slug=LeagueSlug.NBA,
                )
            teams_to_save.append(team)

        for team in teams_to_save:
            await repo.save(team, commit=False)
        await session.commit()

        id_map = {}
        name_map = {}
        for team in teams_to_save:
            await session.refresh(team)
            id_map[team.abbreviation] = team.id
            name_map[team.abbreviation] = team.name

        data.set_team_mapping(id_map, name_map)
        logger.info(f"Upserted {len(id_map)} teams")
        return True


async def seed_pools(data: SeedData) -> Dict[str, uuid.UUID]:
    """Seed pools (idempotent)."""
    logger.info("Seeding pools...")
    pools_data = data.get_pools()
    pool_map = {}

    async with AsyncSession(engine) as session:
        repo = PoolRepository(session)

        for pool_data in pools_data:
            existing = await repo.get_by_slug(pool_data["slug"])
            if existing:
                pool_map[pool_data["slug"]] = existing.id
            else:
                pool = Pool(slug=pool_data["slug"], name=pool_data["name"])
                created = await repo.save(pool)
                pool_map[pool_data["slug"]] = created.id
                logger.info(f"Created pool: {pool_data['slug']}")

    return pool_map


async def seed_seasons(data: SeedData, pool_map: Dict[str, uuid.UUID]) -> None:
    """Seed pool seasons, filling in rules and valuation dates from pool_seasons.json without overwriting app edits."""
    logger.info("Seeding seasons...")
    seasons_data = data.get_seasons()
    records = data.load_pool_seasons()

    async with AsyncSession(engine) as session:
        repo = PoolSeasonRepository(session)

        for season_data in seasons_data:
            pool_id = pool_map.get(season_data["pool"])
            if not pool_id:
                continue

            record = records.get((season_data["pool"], season_data["season"]))
            projection_date = (
                datetime.combine(record.projection_date, time.max) if record and record.projection_date else None
            )

            existing = await repo.get_by_pool_and_season(pool_id, season_data["season"])
            if not existing:
                season = PoolSeason(
                    pool_id=pool_id,
                    season=season_data["season"],
                    rules=record.rules if record else None,
                    auction_projection_date=projection_date,
                )
                await repo.create(season)
                logger.info(f"Created season: {season_data['pool']} {season_data['season']}")
                continue

            changed = False
            owned_by_file = is_file_owned(season_data["season"])
            if projection_date and (owned_by_file or not existing.auction_projection_date):
                if existing.auction_projection_date != projection_date:
                    existing.auction_projection_date = projection_date
                    changed = True
            if record and record.rules and not existing.rules:
                existing.rules = record.rules
                changed = True
            if changed:
                await repo.update(existing)
                logger.info(f"Updated season: {season_data['pool']} {season_data['season']}")


async def seed_rosters(data: SeedData, pool_map: Dict[str, uuid.UUID], pool_filter: Optional[str] = None) -> None:
    """Seed the rosters (owners) of every pool season in rosters.csv. Their slots come from the season's auction."""
    logger.info("Seeding rosters...")
    async with AsyncSession(engine) as session:
        roster_repo = RosterRepository(session)
        for (pool_slug, season), owners in sorted(data.get_auction_slots(pool_filter).items()):
            pool_id = pool_map.get(pool_slug)
            if not pool_id:
                logger.warning(f"Pool '{pool_slug}' not found")
                continue
            existing = {r.name for r in await roster_repo.get_all(pool_id=pool_id, season=season)}
            for name in sorted(set(owners) - existing):
                await roster_repo.save(Roster(name=name, pool_id=pool_id, season=season))
                logger.info(f"Created roster: {pool_slug} {season} {name}")


async def seed_nba_cache(data: SeedData, refresh: bool, offline: bool = False) -> bool:
    """Pre-load NBA schedule data for all pool seasons.

    A season is served from its checked-in fixture whenever one exists, because
    stats.nba.com takes minutes to return a full season schedule when it returns at all.
    `refresh` means "go ask the API", so it skips the fixture unless `offline` rules the
    API out entirely.

    A stale cache row is dropped only once a fetch is actually about to happen:
    `get_historical_schedule_cached` short-circuits on a cache hit and would never
    refetch otherwise, and dropping it any earlier would leave a season that gets
    skipped for want of a fixture with nothing at all.

    Args:
        data: SeedData instance with loaded data
        refresh: If True, refresh existing cache entries from the NBA API
        offline: If True, only seed seasons that have a checked-in fixture and never
            call the NBA API

    Returns:
        True if successful
    """
    logger.info("Seeding NBA schedule cache...")

    seasons_data = data.get_seasons()
    unique_seasons = set(s["season"] for s in seasons_data)

    logger.info(f"Found {len(unique_seasons)} unique seasons to cache: {sorted(unique_seasons)}")

    async with AsyncSession(engine) as session:
        external_repo = ExternalDataRepository(session)
        nba_service = NbaDataService(session, external_repo)

        for season in sorted(unique_seasons):
            existing = await external_repo.get_by_key(schedule_cache_key(season))

            if existing and not refresh:
                logger.info(f"Season {season} already cached (use --refresh-nba-cache to refetch)")
                continue

            logger.info(f"{'Refreshing cache for' if existing else 'Caching'} season {season}...")

            if offline or not refresh:
                raw_schedule = load_fixture(season)
                if raw_schedule is not None:
                    await nba_service.store_schedule_cache(season, raw_schedule)
                    logger.info(f"Cached season {season} from fixture {fixture_path(season).name}")
                    continue

            if offline:
                logger.warning(f"No schedule fixture for season {season} and --offline is set; skipping")
                continue

            if existing:
                await external_repo.delete(existing)

            try:
                games = await nba_service.get_historical_schedule_cached(season)
                logger.info(f"Cached {len(games)} games for season {season}")
            except Exception as e:
                logger.error(f"Failed to cache season {season}: {e}")
                continue

        await session.commit()

    logger.info("NBA schedule cache seeding completed")
    return True


async def seed_nba_projections(data: SeedData) -> bool:
    """Seed NBA projections. Fetches of seasons before the app existed are rewritten from the CSV; later ones
    are only added when missing, since the app fetches those itself."""
    logger.info("Seeding NBA Projections Data...")
    fetches = await data.load_nba_projections()

    async with AsyncSession(engine) as session:
        repo = ProjectionRepository(session)
        count = 0
        for fetch in fetches:
            if is_file_owned(fetch.season):
                await repo.delete_fetches(fetch.source, fetch.season, fetch.fetched_at)
            elif await repo.has_fetch(fetch.source, fetch.season, fetch.fetched_at):
                continue
            await repo.add_fetch(fetch.source, fetch.season, fetch.fetched_at, fetch.quotes)
            count += 1

        await session.commit()
        logger.info(f"Wrote {count} projection fetches")
        return True


async def main():
    parser = argparse.ArgumentParser(
        description="Seed the NBA Wins Pool database with everything in scripts/data, in dependency order. "
        "Safe to re-run: seasons before the app existed are brought in line with the files, and later ones "
        "are only filled in where empty."
    )
    parser.add_argument("--pool", help="Only seed this pool slug")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Seed the NBA schedule cache from checked-in fixtures only; never call the NBA API",
    )
    parser.add_argument(
        "--refresh-nba-cache",
        action="store_true",
        help="Only refetch the NBA schedule cache from the NBA API, replacing what is cached, then exit",
    )
    args = parser.parse_args()

    data = SeedData()

    try:
        if args.refresh_nba_cache:
            await seed_nba_cache(data, refresh=True)
            return

        await seed_teams(data)
        pool_map = await seed_pools(data)
        await seed_seasons(data, pool_map)
        await seed_rosters(data, pool_map, args.pool)
        await seed_nba_cache(data, refresh=False, offline=args.offline)
        await seed_nba_projections(data)
        await seed_auctions(data.load_pool_seasons(), data.get_auction_slots(args.pool), pool_filter=args.pool)

        logger.info("Seeding completed")

    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
