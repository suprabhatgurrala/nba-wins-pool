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
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import engine
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.models.pool_season import PoolSeason
from nba_wins_pool.models.roster import Roster
from nba_wins_pool.models.roster_slot import RosterSlot
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.pool_repository import PoolRepository
from nba_wins_pool.repositories.pool_season_repository import PoolSeasonRepository
from nba_wins_pool.repositories.roster_repository import RosterRepository
from nba_wins_pool.repositories.roster_slot_repository import RosterSlotRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_data_service import NbaDataService

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed_data")


class SeedData:
    """Centralized data loader and cache."""

    def __init__(self):
        self.data_dir = Path(__file__).parent / "data"
        self._teams = None
        self._roster_slots = None
        self._team_abbr_to_id = {}

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
                    self._roster_slots.append({
                        "pool": row["pool"],
                        "season": row["season"],
                        "roster": row["roster"],
                        "team": row["team"],
                        "price": Decimal(row["auction_price"]),
                    })
            logger.info(f"Loaded {len(self._roster_slots)} roster slots")
        return self._roster_slots

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

    def set_team_mapping(self, mapping: Dict[str, uuid.UUID]):
        """Cache team abbreviation to ID mapping."""
        self._team_abbr_to_id = mapping

    def get_team_id(self, abbreviation: str) -> uuid.UUID:
        """Get team ID by abbreviation."""
        return self._team_abbr_to_id.get(abbreviation)


async def seed_teams(data: SeedData, force: bool) -> bool:
    """Seed NBA teams."""
    logger.info("Seeding teams...")
    teams_data = data.load_teams()

    async with AsyncSession(engine) as session:
        repo = TeamRepository(session)
        existing = await repo.get_all_by_league_slug(LeagueSlug.NBA)

        if existing and not force:
            logger.info(f"Found {len(existing)} teams (use --force to overwrite)")
            # Build mapping from existing
            team_map = {}
            for team in existing:
                for td in teams_data:
                    if str(td["nba_id"]) == team.external_id:
                        team_map[td["abbreviation"]] = team.id
                        break
            data.set_team_mapping(team_map)
            return True

        if force and existing:
            logger.info(f"Deleting {len(existing)} teams...")
            for team in existing:
                await repo.delete(team)

        # Create teams
        team_map = {}
        for td in teams_data:
            team = Team(
                external_id=str(td["nba_id"]),
                name=td["name"],
                abbreviation=td["abbreviation"],
                logo_url=td["logo_url"],
                league_slug=LeagueSlug.NBA,
            )
            created = await repo.save(team)
            team_map[td["abbreviation"]] = created.id

        data.set_team_mapping(team_map)
        logger.info(f"Created {len(team_map)} teams")
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
    """Seed pool seasons (idempotent)."""
    logger.info("Seeding seasons...")
    seasons_data = data.get_seasons()

    async with AsyncSession(engine) as session:
        repo = PoolSeasonRepository(session)

        for season_data in seasons_data:
            pool_id = pool_map.get(season_data["pool"])
            if not pool_id:
                continue

            existing = await repo.get_by_pool_and_season(pool_id, season_data["season"])
            if not existing:
                season = PoolSeason(
                    pool_id=pool_id,
                    season=season_data["season"],
                    rules=None,
                )
                await repo.create(season)
                logger.info(f"Created season: {season_data['pool']} {season_data['season']}")


async def seed_roster_slots(data: SeedData, pool_map: Dict[str, uuid.UUID], pool_filter: str = None, force: bool = False) -> None:
    """Seed roster slots."""
    logger.info("Seeding roster slots...")
    slots_data = data.load_roster_slots()

    if pool_filter:
        slots_data = [s for s in slots_data if s["pool"] == pool_filter]
        if not slots_data:
            logger.error(f"No data for pool '{pool_filter}'")
            return

    async with AsyncSession(engine) as session:
        roster_repo = RosterRepository(session)
        slot_repo = RosterSlotRepository(session)

        # Group by pool
        pools = {}
        for slot in slots_data:
            pool_slug = slot["pool"]
            if pool_slug not in pools:
                pools[pool_slug] = []
            pools[pool_slug].append(slot)

        for pool_slug, pool_slots in pools.items():
            pool_id = pool_map.get(pool_slug)
            if not pool_id:
                logger.warning(f"Pool '{pool_slug}' not found")
                continue

            # Check existing
            existing_rosters = await roster_repo.get_all(pool_id=pool_id)
            existing_slots = []
            for roster in existing_rosters:
                existing_slots.extend(await slot_repo.get_all_by_roster_id(roster.id))

            if existing_slots and not force:
                logger.info(f"Pool '{pool_slug}' has {len(existing_slots)} slots (use --force)")
                continue

            if force and existing_slots:
                logger.info(f"Deleting {len(existing_slots)} slots...")
                for slot in existing_slots:
                    await slot_repo.delete(slot)
                # Refresh rosters after deletion to get fresh data
                existing_rosters = await roster_repo.get_all(pool_id=pool_id)

            # Build roster map
            roster_map = {(r.name, r.season): r.id for r in existing_rosters}
            
            for slot in pool_slots:
                key = (slot["roster"], slot["season"])
                if key not in roster_map:
                    roster = Roster(name=slot["roster"], pool_id=pool_id, season=slot["season"])
                    created = await roster_repo.save(roster)
                    roster_map[key] = created.id

            await session.commit()

            # Create slots
            count = 0
            for slot in pool_slots:
                team_id = data.get_team_id(slot["team"])
                if not team_id:
                    logger.warning(f"Team '{slot['team']}' not found")
                    continue

                roster_id = roster_map[(slot["roster"], slot["season"])]
                slot_obj = RosterSlot(
                    roster_id=roster_id,
                    team_id=team_id,
                    auction_price=slot["price"],
                )
                await slot_repo.save(slot_obj)
                count += 1

            logger.info(f"Created {count} slots for pool '{pool_slug}'")


async def seed_nba_cache(data: SeedData, force: bool) -> bool:
    """Pre-load NBA schedule data for all pool seasons.
    
    Args:
        data: SeedData instance with loaded data
        force: If True, refresh existing cache entries
        
    Returns:
        True if successful
    """
    logger.info("Seeding NBA schedule cache...")
    
    seasons_data = data.get_seasons()
    unique_seasons = set(s["season"] for s in seasons_data)
    
    logger.info(f"Found {len(unique_seasons)} unique seasons to cache: {sorted(unique_seasons)}")
    
    async with AsyncSession(engine) as session:
        nba_service = NbaDataService(session)
        external_repo = ExternalDataRepository(session)
        
        # Get current scoreboard date for filtering
        scoreboard_games, scoreboard_date = await nba_service.get_scoreboard_cached()
        logger.info(f"Using scoreboard date: {scoreboard_date}")
        
        for season in sorted(unique_seasons):
            cache_key = f"nba:schedule:{season}"
            
            # Check if cache exists
            existing = await external_repo.get_by_key(cache_key)
            
            if existing and not force:
                logger.info(f"Season {season} already cached (use --force to refresh)")
                continue
            
            if existing and force:
                logger.info(f"Refreshing cache for season {season}...")
                await external_repo.delete(existing)
            else:
                logger.info(f"Caching season {season}...")
            
            try:
                # Fetch and cache the schedule
                games, season_year = await nba_service.get_schedule_cached(scoreboard_date, season)
                logger.info(f"  ✓ Cached {len(games)} games for season {season}")
            except Exception as e:
                logger.error(f"  ✗ Failed to cache season {season}: {e}")
                continue
        
        await session.commit()
    
    logger.info("NBA schedule cache seeding completed")
    return True


async def main():
    parser = argparse.ArgumentParser(description="Seed NBA Wins Pool database")
    parser.add_argument("--teams", action="store_true", help="Seed teams")
    parser.add_argument("--roster-slots", action="store_true", help="Seed roster slots")
    parser.add_argument("--pools", action="store_true", help="Seed pools")
    parser.add_argument("--nba-cache", action="store_true", help="Pre-load NBA schedule cache")
    parser.add_argument("--pool", help="Specific pool slug")
    parser.add_argument("--force", action="store_true", help="Force overwrite")
    args = parser.parse_args()

    # Default to all if nothing specified
    if not (args.teams or args.roster_slots or args.pools or args.nba_cache):
        args.teams = args.roster_slots = args.pools = args.nba_cache = True

    data = SeedData()

    try:
        if args.teams:
            await seed_teams(data, args.force)

        pool_map = None
        if args.pools or args.roster_slots:
            pool_map = await seed_pools(data)

        if args.pools or args.roster_slots:
            await seed_seasons(data, pool_map)

        if args.roster_slots:
            await seed_roster_slots(data, pool_map, args.pool, args.force)

        if args.nba_cache:
            await seed_nba_cache(data, args.force)

        logger.info("Seeding completed")

    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
