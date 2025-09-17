#!/usr/bin/env python3
"""
Script to seed data into the NBA Wins Pool database.
This script can seed NBA teams, team ownerships, or both.
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
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import engine
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.models.roster import Roster
from nba_wins_pool.models.roster_slot import RosterSlot
from nba_wins_pool.models.team import LeagueSlug, Team
from nba_wins_pool.repositories.pool_repository import PoolRepository
from nba_wins_pool.repositories.roster_repository import RosterRepository
from nba_wins_pool.repositories.roster_slot_repository import RosterSlotRepository
from nba_wins_pool.repositories.team_repository import TeamRepository

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("seed_data")


async def load_nba_teams() -> List[Dict]:
    """
    Load NBA team data from JSON file.

    Returns:
        List[Dict]: List of team data dictionaries
    """
    data_file = Path(__file__).parent / "data" / "nba_teams.json"

    if not data_file.exists():
        raise FileNotFoundError(f"NBA teams data file not found: {data_file}")

    with open(data_file, "r", encoding="utf-8") as f:
        teams = json.load(f)

    logger.info(f"Loaded {len(teams)} NBA teams from data file")
    return teams


async def load_team_ownerships() -> List[Dict]:
    """
    Load team ownership data from CSV file.

    Returns:
        List[Dict]: List of team ownership dictionaries
    """
    data_file = Path(__file__).parent / "data" / "team_owner.csv"

    if not data_file.exists():
        raise FileNotFoundError(f"Team ownership data file not found: {data_file}")

    ownerships = []
    with open(data_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ownerships.append(
                {
                    "pool_slug": row["pool_slug"],
                    "season": row["season"],
                    "owner_name": row["owner"],
                    "team_slug": row["team"],
                    "auction_price": Decimal(row["auction_price"]),
                }
            )

    logger.info(f"Loaded {len(ownerships)} team ownerships from data file")
    return ownerships


async def seed_nba_teams(force: bool = False) -> Dict[str, str]:
    """
    Seed NBA team data into the database.

    Args:
        force: If True, delete existing teams before seeding

    Returns:
        Dict[str, str]: Mapping of team slug (from data) to team ID
    """
    logger.info("🏀 Starting NBA teams seeding...")

    try:
        # Load team data
        teams_data = await load_nba_teams()
    except Exception as e:
        logger.error(f"❌ Error loading NBA team data: {e}")
        return {}

    team_map = {}  # Maps team slug from data to team ID

    # Create database session and repository
    async with AsyncSession(engine) as session:
        team_repo = TeamRepository(session)

        try:
            # Check if teams already exist
            existing_teams = await team_repo.get_all_by_league_slug(LeagueSlug.NBA)
            existing_count = len(existing_teams)

            if existing_count > 0:
                if not force:
                    logger.warning(f"⚠️  Found {existing_count} existing teams. Use --force to overwrite.")

                    # Return mapping of existing teams - match by external_id to slug
                    for team in existing_teams:
                        # Find matching team data by external_id
                        for team_data in teams_data:
                            if str(team_data["nba_id"]) == team.external_id:
                                team_map[team_data["slug"]] = team.id
                                break

                    return team_map
                else:
                    logger.info(f"🗑️  Deleting {existing_count} existing teams...")
                    for team in existing_teams:
                        await team_repo.delete(team)

            # Insert teams
            logger.info("📝 Inserting NBA teams...")
            teams_created = 0

            for team_data in teams_data:
                team = Team(
                    external_id=str(team_data["nba_id"]),
                    name=team_data["name"],
                    logo_url=team_data["logo_url"],
                    league_slug=LeagueSlug.NBA,
                )
                created_team = await team_repo.save(team)

                team_map[team_data["slug"]] = created_team.id
                teams_created += 1
                logger.info(f"✅ Created team: {created_team.name} (ID: {created_team.id})")

            logger.info(f"🎉 Successfully seeded {teams_created} NBA teams!")
            return team_map

        except Exception as e:
            logger.error(f"❌ Error seeding NBA teams: {e}")
            raise


async def seed_pools(force: bool = False) -> Dict[str, str]:
    """
    Seed pool data into the database.

    Args:
        force: If True, delete existing pools before seeding

    Returns:
        Dict[str, str]: Mapping of pool slug to pool ID
    """
    logger.info("🏊 Starting pools seeding...")

    try:
        # Load team ownership data to extract pool information
        ownership_data = await load_team_ownerships()
    except Exception as e:
        logger.error(f"❌ Error loading team ownership data: {e}")
        return {}

    # Extract unique pool slugs from ownership data
    pool_data = {}
    for ownership in ownership_data:
        pool_slug = ownership["pool_slug"]
        if pool_slug not in pool_data:
            pool_data[pool_slug] = {
                "slug": pool_slug,
                "name": pool_slug.upper(),  # Default name based on slug
            }

    pool_map = {}

    # Create database session and repository
    async with AsyncSession(engine) as session:
        pool_repo = PoolRepository(session)

        try:
            # Check if pools already exist
            for pool_slug, pool_info in pool_data.items():
                existing_pool = await pool_repo.get_by_slug(pool_slug)

                if existing_pool:
                    logger.info(f"⏭️  Pool already exists: {pool_slug}")
                    pool_map[pool_slug] = existing_pool.id
                    continue

                # Create new pool
                pool = Pool(slug=pool_info["slug"], name=pool_info["name"])
                new_pool = await pool_repo.save(pool)

                pool_map[pool_slug] = new_pool.id
                logger.info(f"✅ Created pool: {new_pool.name} ({new_pool.slug})")

            logger.info(f"🎉 Successfully seeded {len(pool_map)} pools!")
            return pool_map

        except Exception as e:
            logger.error(f"❌ Error seeding pools: {e}")
            raise


async def seed_roster_slots(
    pool_slug: Optional[str] = None, force: bool = False, team_map: Optional[Dict[str, str]] = None
) -> None:
    """
    Seed roster slot data into the database.

    Args:
        pool_slug: Specific pool to seed roster slots for (if None, seeds for all pools in data)
        force: If True, delete existing roster slots before seeding
        team_map: Optional mapping of team slug to team ID (to avoid redundant queries)
    """
    logger.info("👥 Starting roster slot seeding...")

    # Load team ownership data
    try:
        ownership_data = await load_team_ownerships()
    except Exception as e:
        logger.error(f"❌ Error loading team ownership data: {e}")
        return

    # Filter data by pool if specified
    if pool_slug:
        ownership_data = [o for o in ownership_data if o["pool_slug"] == pool_slug]
        if not ownership_data:
            logger.error(f"❌ No ownership data found for pool '{pool_slug}'")
            return
        logger.info(f"🎯 Filtered to {len(ownership_data)} roster slots for pool '{pool_slug}'")

    # Create database session and repositories
    async with AsyncSession(engine) as session:
        pool_repo = PoolRepository(session)
        roster_repo = RosterRepository(session)
        roster_slot_repo = RosterSlotRepository(session)
        team_repo = TeamRepository(session)
        try:
            # Get unique pool slugs from the data
            pool_slugs = set(o["pool_slug"] for o in ownership_data)

            # If team_map wasn't provided, build it
            if team_map is None:
                logger.info("🔍 Building team reference map...")
                teams = await team_repo.get_all_by_league_slug(LeagueSlug.NBA)
                team_map = {}

                # Load team data to map external_id back to slug
                try:
                    teams_data = await load_nba_teams()
                    external_id_to_slug = {str(td["nba_id"]): td["slug"] for td in teams_data}

                    for team in teams:
                        if team.external_id in external_id_to_slug:
                            slug = external_id_to_slug[team.external_id]
                            team_map[slug] = team.id
                except Exception as e:
                    logger.error(f"❌ Error loading team data for mapping: {e}")
                    return

                if not team_map:
                    logger.error("❌ No NBA teams found in database. Run with --teams flag first.")
                    return

            for current_pool_slug in pool_slugs:
                logger.info(f"\n🏊 Processing pool: {current_pool_slug}")

                # Get the pool
                pool = await pool_repo.get_by_slug(current_pool_slug)

                if not pool:
                    logger.error(f"  ❌ Pool '{current_pool_slug}' not found. Skipping...")
                    continue

                # Get pool-specific ownership data
                pool_ownerships = [o for o in ownership_data if o["pool_slug"] == current_pool_slug]

                # Get existing rosters for this pool
                existing_rosters = await roster_repo.get_all(pool_id=pool.id)
                roster_map = {(roster.name, roster.season): roster.id for roster in existing_rosters}

                # Check if roster slots already exist for this pool
                existing_slots = []
                for roster in existing_rosters:
                    slots = await roster_slot_repo.get_all_by_roster_id(roster.id)
                    existing_slots.extend(slots)
                existing_count = len(existing_slots)

                if existing_count > 0 and not force:
                    logger.warning(f"  ⚠️  Found {existing_count} existing roster slots. Use --force to overwrite.")
                    continue

                if force and existing_count > 0:
                    logger.info(f"  🗑️  Deleting {existing_count} existing roster slots...")
                    for slot in existing_slots:
                        await roster_slot_repo.delete(slot)

                # Get or create rosters for this pool
                logger.info("  👤 Processing rosters...")
                # Get unique combinations of owner and season
                unique_roster_combos = set((o["owner_name"], o["season"]) for o in pool_ownerships)

                # Store pool_id to avoid accessing it multiple times
                pool_id = pool.id

                for owner_name, season in unique_roster_combos:
                    roster_key = (owner_name, season)
                    # Check if roster exists
                    if roster_key not in roster_map:
                        # Create new roster
                        roster = Roster(name=owner_name, pool_id=pool_id, season=season)
                        created_roster = await roster_repo.save(roster)
                        roster_map[roster_key] = created_roster.id
                        logger.info(f"    ✅ Created roster: {owner_name} ({season})")
                    else:
                        logger.info(f"    ⏭️  Roster exists: {owner_name} ({season})")

                # Commit session to ensure all rosters are persisted
                await session.commit()

                # Insert roster slots
                logger.info("  📝 Inserting roster slots...")
                slots_created = 0

                for ownership_info in pool_ownerships:
                    team_slug = ownership_info["team_slug"]

                    # Check if team exists in our map
                    if team_slug not in team_map:
                        logger.error(f"    ❌ Team '{team_slug}' not found in database. Skipping...")
                        continue

                    # Get the team ID from our map (ensure it's UUID)
                    team_id = team_map[team_slug]
                    if isinstance(team_id, str):
                        team_id = uuid.UUID(team_id)

                    # Get the roster ID using owner name and season
                    roster_key = (ownership_info["owner_name"], ownership_info["season"])
                    roster_id = roster_map.get(roster_key)
                    if not roster_id:
                        logger.error(
                            f"    ❌ Roster '{ownership_info['owner_name']}' for season '{ownership_info['season']}' not found. Skipping..."
                        )
                        continue

                    # Ensure roster_id is a UUID
                    if isinstance(roster_id, str):
                        roster_id = uuid.UUID(roster_id)

                    roster_slot = RosterSlot(
                        roster_id=roster_id,
                        team_id=team_id,
                        auction_price=ownership_info["auction_price"],
                    )
                    await roster_slot_repo.save(roster_slot)
                    slots_created += 1
                    logger.info(
                        f"    ✅ {ownership_info['owner_name']} -> {team_slug} (${ownership_info['auction_price']})"
                    )

                logger.info(f"  🎉 Successfully seeded {slots_created} roster slots for pool '{current_pool_slug}'!")

        except Exception as e:
            logger.error(f"❌ Error seeding roster slots: {e}")
            raise


async def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Seed NBA Wins Pool database with teams and/or team ownerships")

    # Action group - what to seed
    action_group = parser.add_argument_group("Seeding Actions")
    action_group.add_argument("--teams", action="store_true", help="Seed NBA teams")
    action_group.add_argument("--roster-slots", action="store_true", help="Seed roster slots")
    action_group.add_argument(
        "--pools", action="store_true", help="Seed pools (automatically done with --roster-slots)"
    )

    # Optional arguments
    parser.add_argument("--pool", help="Specific pool slug to seed roster slots for (only used with --roster-slots)")
    parser.add_argument("--force", action="store_true", help="Force overwrite existing data")

    args = parser.parse_args()

    # If no action specified, default to all
    if not args.teams and not getattr(args, "roster_slots", False) and not args.pools:
        args.teams = True
        args.roster_slots = True
        args.pools = True
        logger.info("No action specified, defaulting to seeding teams, pools, and roster slots")

    try:
        team_map = None

        if args.teams:
            team_map = await seed_nba_teams(force=args.force)

        # Always seed pools if we're seeding roster slots or explicitly asked to
        if args.pools or getattr(args, "roster_slots", False):
            await seed_pools(force=args.force)

        if getattr(args, "roster_slots", False):
            await seed_roster_slots(pool_slug=args.pool, force=args.force, team_map=team_map)

        logger.info("✅ Seeding completed successfully!")

    except Exception as e:
        logger.error(f"❌ Script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
