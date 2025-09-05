#!/usr/bin/env python3
"""
Script to seed data into the NBA Wins Pool database.
This script can seed NBA teams, team ownerships, or both.
"""

import asyncio
import argparse
import csv
import json
import sys
import logging
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import engine
from nba_wins_pool.models.team import Team
from nba_wins_pool.models.team_ownership import TeamOwnership
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.models.member import Member

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
        Dict[str, str]: Mapping of team slug to team ID
    """
    logger.info("🏀 Starting NBA teams seeding...")

    try:
        # Load team data
        teams_data = await load_nba_teams()
    except Exception as e:
        logger.error(f"❌ Error loading NBA team data: {e}")
        return {}

    team_map = {}

    # Create database session
    async with AsyncSession(engine) as session:
        try:
            # Check if teams already exist
            existing_teams_result = await session.execute(select(Team))
            existing_teams = existing_teams_result.scalars().all()
            existing_count = len(existing_teams)

            if existing_count > 0:
                if not force:
                    logger.warning(f"⚠️  Found {existing_count} existing teams. Use --force to overwrite.")

                    # Return mapping of existing teams
                    for team in existing_teams:
                        team_map[team.slug] = team.id

                    return team_map
                else:
                    logger.info(f"🗑️  Deleting {existing_count} existing teams...")
                    for team in existing_teams:
                        await session.delete(team)
                    await session.commit()

            # Insert teams
            logger.info("📝 Inserting NBA teams...")
            teams_created = 0

            for team_data in teams_data:
                team = Team(
                    slug=team_data["slug"],
                    external_id=str(team_data["nba_id"]),
                    name=team_data["name"],
                    logo_url=team_data["logo_url"],
                )
                session.add(team)
                await session.flush()  # Get the ID

                team_map[team.slug] = team.id
                teams_created += 1
                logger.info(f"✅ Created team: {team.name} ({team.slug})")

            # Commit changes
            await session.commit()
            logger.info(f"🎉 Successfully seeded {teams_created} NBA teams!")

            return team_map

        except Exception as e:
            await session.rollback()
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

    # Extract unique pool slugs and seasons from ownership data
    pool_data = {}
    for ownership in ownership_data:
        pool_slug = ownership["pool_slug"]
        season = ownership["season"]
        if pool_slug not in pool_data:
            pool_data[pool_slug] = {
                "slug": pool_slug,
                "name": pool_slug.upper(),  # Default name based on slug
                "season": season,
            }

    pool_map = {}

    # Create database session
    async with AsyncSession(engine) as session:
        try:
            # Check if pools already exist
            for pool_slug, pool_info in pool_data.items():
                pool_result = await session.execute(select(Pool).where(Pool.slug == pool_slug))
                existing_pool = pool_result.scalars().first()

                if existing_pool:
                    logger.info(f"⏭️  Pool already exists: {pool_slug}")
                    pool_map[pool_slug] = existing_pool.id
                    continue

                # Create new pool
                new_pool = Pool(slug=pool_info["slug"], name=pool_info["name"], season=pool_info["season"])
                session.add(new_pool)
                await session.flush()  # Get the ID

                pool_map[pool_slug] = new_pool.id
                logger.info(f"✅ Created pool: {new_pool.name} ({new_pool.slug}) for season {new_pool.season}")

            # Commit changes
            await session.commit()
            logger.info(f"🎉 Successfully seeded {len(pool_map)} pools!")

            return pool_map

        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Error seeding pools: {e}")
            raise


async def seed_team_ownerships(
    pool_slug: Optional[str] = None, force: bool = False, team_map: Optional[Dict[str, str]] = None
) -> None:
    """
    Seed team ownership data into the database.

    Args:
        pool_slug: Specific pool to seed team owners for (if None, seeds for all pools in data)
        force: If True, delete existing team ownerships before seeding
        team_map: Optional mapping of team slug to team ID (to avoid redundant queries)
    """
    logger.info("👥 Starting team ownership seeding...")

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
        logger.info(f"🎯 Filtered to {len(ownership_data)} ownerships for pool '{pool_slug}'")

    # Create database session
    async with AsyncSession(engine) as session:
        try:
            # Get unique pool slugs from the data
            pool_slugs = set(o["pool_slug"] for o in ownership_data)

            # If team_map wasn't provided, build it
            if team_map is None:
                logger.info("🔍 Building team reference map...")
                teams_result = await session.execute(select(Team))
                teams = teams_result.scalars().all()
                team_map = {team.slug: team.id for team in teams}

                if not team_map:
                    logger.error("❌ No NBA teams found in database. Run with --teams flag first.")
                    return

            for current_pool_slug in pool_slugs:
                logger.info(f"\n🏊 Processing pool: {current_pool_slug}")

                # Get the pool
                pool_result = await session.execute(select(Pool).where(Pool.slug == current_pool_slug))
                pool = pool_result.scalars().first()

                if not pool:
                    logger.error(f"  ❌ Pool '{current_pool_slug}' not found. Skipping...")
                    continue

                # Get pool-specific ownership data
                pool_ownerships = [o for o in ownership_data if o["pool_slug"] == current_pool_slug]

                # Check if team ownerships already exist for this pool
                existing_ownerships_result = await session.execute(
                    select(TeamOwnership).where(TeamOwnership.pool_id == pool.id)
                )
                existing_ownerships = existing_ownerships_result.scalars().all()
                existing_count = len(existing_ownerships)

                if existing_count > 0 and not force:
                    logger.warning(f"  ⚠️  Found {existing_count} existing team ownerships. Use --force to overwrite.")
                    continue

                if force and existing_count > 0:
                    logger.info(f"  🗑️  Deleting {existing_count} existing team ownerships...")
                    for ownership in existing_ownerships:
                        await session.delete(ownership)
                    await session.commit()

                # Get or create members for this pool
                logger.info("  👤 Processing members...")
                unique_owners = set(o["owner_name"] for o in pool_ownerships)
                member_map = {}

                for owner_name in unique_owners:
                    # Check if member exists
                    member_result = await session.execute(
                        select(Member).where((Member.name == owner_name) & (Member.pool_id == pool.id))
                    )
                    member = member_result.scalars().first()

                    if not member:
                        # Create new member
                        member = Member(
                            name=owner_name,
                            pool_id=pool.id,
                        )
                        session.add(member)
                        await session.flush()  # Get the ID
                        logger.info(f"    ✅ Created member: {owner_name}")
                    else:
                        logger.info(f"    ⏭️  Member exists: {owner_name}")

                    member_map[owner_name] = member

                # Insert team ownerships
                logger.info("  📝 Inserting team ownerships...")
                ownerships_created = 0

                for ownership_info in pool_ownerships:
                    team_slug = ownership_info["team_slug"]

                    # Check if team exists in our map
                    if team_slug not in team_map:
                        logger.error(f"    ❌ Team '{team_slug}' not found in database. Skipping...")
                        continue

                    # Get the team ID from our map
                    team_id = team_map[team_slug]

                    # Get the member
                    member = member_map.get(ownership_info["owner_name"])
                    if not member:
                        logger.error(f"    ❌ Member '{ownership_info['owner_name']}' not found. Skipping...")
                        continue

                    ownership = TeamOwnership(
                        pool_id=pool.id,
                        team_id=team_id,
                        owner_id=member.id,
                        auction_price=ownership_info["auction_price"],
                    )
                    session.add(ownership)
                    ownerships_created += 1
                    logger.info(
                        f"    ✅ {ownership_info['owner_name']} -> {team_slug} (${ownership_info['auction_price']})"
                    )

                # Commit changes for this pool
                await session.commit()
                logger.info(
                    f"  🎉 Successfully seeded {ownerships_created} team ownerships for pool '{current_pool_slug}'!"
                )

        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Error seeding team ownerships: {e}")
            raise


async def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Seed NBA Wins Pool database with teams and/or team ownerships")

    # Action group - what to seed
    action_group = parser.add_argument_group("Seeding Actions")
    action_group.add_argument("--teams", action="store_true", help="Seed NBA teams")
    action_group.add_argument("--ownerships", action="store_true", help="Seed team ownerships")
    action_group.add_argument("--pools", action="store_true", help="Seed pools (automatically done with --ownerships)")

    # Optional arguments
    parser.add_argument("--pool", help="Specific pool slug to seed team owners for (only used with --ownerships)")
    parser.add_argument("--force", action="store_true", help="Force overwrite existing data")

    args = parser.parse_args()

    # If no action specified, default to all
    if not args.teams and not args.ownerships and not args.pools:
        args.teams = True
        args.ownerships = True
        args.pools = True
        logger.info("No action specified, defaulting to seeding teams, pools, and ownerships")

    try:
        team_map = None

        if args.teams:
            team_map = await seed_nba_teams(force=args.force)

        # Always seed pools if we're seeding ownerships or explicitly asked to
        if args.pools or args.ownerships:
            await seed_pools(force=args.force)

        if args.ownerships:
            await seed_team_ownerships(pool_slug=args.pool, force=args.force, team_map=team_map)

        logger.info("✅ Seeding completed successfully!")

    except Exception as e:
        logger.error(f"❌ Script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
