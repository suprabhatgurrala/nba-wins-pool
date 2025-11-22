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
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import engine
from nba_wins_pool.models.nba_vegas_data import NBAVegasDataCreate
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.models.pool_season import PoolSeason
from nba_wins_pool.models.roster import Roster
from nba_wins_pool.models.roster_slot import RosterSlot
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.nba_vegas_repository import NBAVegasRepository
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
        self._vegas_data = None

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

    @staticmethod
    def get_optional_int(value: str) -> Optional[int]:
        # Convert empty strings to None for optional fields
        return int(value) if value and value.strip() else None

    async def load_vegas_odds(self) -> List[NBAVegasDataCreate]:
        """Load Vegas odds data from CSV (cached)."""
        if self._vegas_data is None:
            file_path = self.data_dir / "nba_vegas_data.csv"
            self._vegas_data = []

            await seed_teams(self, force=False)

            with open(file_path, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    self._vegas_data.append(
                        NBAVegasDataCreate(
                            season=row["season"],
                            team_id=self.get_team_id(row["abbreviation"]),
                            team_name=row["abbreviation"],
                            fetched_at=datetime.fromisoformat(row["fetched_at"])
                            .astimezone(timezone.utc)
                            .replace(tzinfo=None),
                            reg_season_wins=Decimal(row["reg_season_wins"]),
                            over_wins_odds=self.get_optional_int(row.get("over_wins_odds")),
                            under_wins_odds=self.get_optional_int(row.get("under_wins_odds")),
                            make_playoffs_odds=self.get_optional_int(row.get("make_playoffs_odds")),
                            miss_playoffs_odds=self.get_optional_int(row.get("miss_playoffs_odds")),
                            win_conference_odds=self.get_optional_int(row.get("win_conference_odds")),
                            win_finals_odds=self.get_optional_int(row.get("win_finals_odds")),
                            source=row.get("source", "unknown") or "unknown",
                        )
                    )
            logger.info(f"Loaded {len(self._vegas_data)} Vegas odds records")
        return self._vegas_data


async def seed_teams(data: SeedData, force: bool) -> bool:
    """Seed NBA teams."""
    logger.info("Seeding teams...")
    teams_data = data.load_teams()

    async with AsyncSession(engine) as session:
        repo = TeamRepository(session)
        existing = await repo.get_all_by_league_slug(LeagueSlug.NBA)
        existing_by_external_id = {team.external_id: team for team in existing}

        if existing and not force:
            logger.info(f"Found {len(existing)} teams (use --force to update)")
            team_map = {team.abbreviation: team.id for team in existing}
            data.set_team_mapping(team_map)
            return True

        if force and existing:
            logger.info(f"Updating {len(existing)} teams...")
        else:
            logger.info("Creating teams...")

        # Create or update teams
        team_map = {}
        teams_to_save = []
        for td in teams_data:
            external_id = str(td["nba_id"])
            team = existing_by_external_id.get(external_id)

            if team:  # Update existing team
                team.name = td["name"]
                team.abbreviation = td["abbreviation"]
                team.logo_url = td["logo_url"]
            else:  # Create new team
                team = Team(
                    external_id=external_id,
                    name=td["name"],
                    abbreviation=td["abbreviation"],
                    logo_url=td["logo_url"],
                    league_slug=LeagueSlug.NBA,
                )
            teams_to_save.append(team)
            team_map[td["abbreviation"]] = team.id  # Use the ID before commit

        for team in teams_to_save:
            await repo.save(team, commit=False)
        await session.commit()

        # Refresh objects to get final DB state (especially for new objects)
        for team in teams_to_save:
            await session.refresh(team)
            team_map[team.abbreviation] = team.id

        data.set_team_mapping(team_map)
        logger.info(f"Upserted {len(team_map)} teams")
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


async def seed_roster_slots(
    data: SeedData, pool_map: Dict[str, uuid.UUID], pool_filter: str = None, force: bool = False
) -> None:
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
        external_repo = ExternalDataRepository(session)
        nba_service = NbaDataService(session, external_repo)

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
                games = await nba_service.get_historical_schedule_cached(season)
                logger.info(f"Cached {len(games)} games for season {season}")
            except Exception as e:
                logger.error(f"Failed to cache season {season}: {e}")
                continue

        await session.commit()

    logger.info("NBA schedule cache seeding completed")
    return True


async def seed_vegas_data(data: SeedData, force: bool = False):
    """Seed NBA Vegas Data."""
    logger.info("Seeding Vegas Data...")
    vegas_data = await data.load_vegas_odds()

    async with AsyncSession(engine) as session:
        repo = NBAVegasRepository(session)
        count = 0
        for row in vegas_data:
            row_updated = await repo.upsert(row, update_if_exists=force)
            if row_updated:
                count += 1

        await session.commit()
        logger.info(f"Upserted {count} rows of Vegas data")
        return True


async def main():
    parser = argparse.ArgumentParser(description="Seed NBA Wins Pool database")
    parser.add_argument("--teams", action="store_true", help="Seed teams")
    parser.add_argument("--roster-slots", action="store_true", help="Seed roster slots")
    parser.add_argument("--pools", action="store_true", help="Seed pools")
    parser.add_argument("--nba-cache", action="store_true", help="Pre-load NBA schedule cache")
    parser.add_argument("--vegas-data", action="store_true", help="Seed Vegas data")
    parser.add_argument("--pool", help="Specific pool slug")
    parser.add_argument("--force", action="store_true", help="Force overwrite")
    args = parser.parse_args()

    # Default to all if nothing specified
    if not (args.teams or args.roster_slots or args.pools or args.nba_cache or args.vegas_data):
        args.teams = args.roster_slots = args.pools = args.nba_cache = args.vegas_data = True

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

        if args.vegas_data:
            await seed_vegas_data(data, args.force)

        logger.info("Seeding completed")

    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
