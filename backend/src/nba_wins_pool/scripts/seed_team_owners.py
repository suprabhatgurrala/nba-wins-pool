#!/usr/bin/env python3
"""
Script to seed team ownership data into the database.
"""

import asyncio
import csv
import sys
from decimal import Decimal
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from nba_wins_pool.db.core import engine
from nba_wins_pool.models.team_ownership import TeamOwnership
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.models.member import Member
from nba_wins_pool.models.team import Team


async def load_team_owner_data() -> list[dict]:
    """Load team ownership data from CSV file."""
    data_file = Path(__file__).parent.parent / "data" / "team_owner.csv"

    if not data_file.exists():
        raise FileNotFoundError(f"Team owner data file not found: {data_file}")

    ownerships = []
    with open(data_file, "r") as f:
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

    return ownerships


async def seed_team_owners(pool_slug: str = None, force: bool = False) -> None:
    """
    Seed team ownership data into the database.

    Args:
        pool_slug: Specific pool to seed team owners for (if None, seeds for all pools in data)
        force: If True, delete existing team ownerships before seeding
    """
    print("👥 Starting team ownership seeding...")

    # Load team ownership data
    try:
        ownership_data = await load_team_owner_data()
        print(f"📊 Loaded {len(ownership_data)} team ownerships from data file")
    except Exception as e:
        print(f"❌ Error loading team ownership data: {e}")
        return

    # Filter data by pool if specified
    if pool_slug:
        ownership_data = [o for o in ownership_data if o["pool_slug"] == pool_slug]
        if not ownership_data:
            print(f"❌ No ownership data found for pool '{pool_slug}'")
            return
        print(f"🎯 Filtered to {len(ownership_data)} ownerships for pool '{pool_slug}'")

    # Create database session
    async with AsyncSession(engine) as session:
        try:
            # Get unique pool slugs from the data
            pool_slugs = list(set(o["pool_slug"] for o in ownership_data))

            for current_pool_slug in pool_slugs:
                print(f"\n🏊 Processing pool: {current_pool_slug}")

                # Get the pool
                pool_result = await session.execute(select(Pool).where(Pool.slug == current_pool_slug))
                pool = pool_result.scalars().first()

                if not pool:
                    print(f"  ❌ Pool '{current_pool_slug}' not found. Skipping...")
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
                    print(f"  ⚠️  Found {existing_count} existing team ownerships. Use --force to overwrite.")
                    continue

                if force and existing_count > 0:
                    print(f"  🗑️  Deleting {existing_count} existing team ownerships...")
                    for ownership in existing_ownerships:
                        await session.delete(ownership)
                    await session.commit()

                # Get or create members for this pool
                print("  👤 Processing members...")
                unique_owners = list(set(o["owner_name"] for o in pool_ownerships))
                member_map = {}

                for owner_name in unique_owners:
                    # Check if member exists
                    member_result = await session.execute(select(Member).where(Member.name == owner_name))
                    member = member_result.scalars().first()

                    if not member:
                        # Create new member
                        member = Member(name=owner_name)
                        session.add(member)
                        await session.flush()  # Get the ID
                        print(f"    ✅ Created member: {owner_name}")
                    else:
                        print(f"    ⏭️  Member exists: {owner_name}")

                    member_map[owner_name] = member

                # Insert team ownerships
                print("  📝 Inserting team ownerships...")
                ownerships_created = 0

                for ownership_info in pool_ownerships:
                    # Get the team
                    team_result = await session.execute(select(Team).where(Team.slug == ownership_info["team_slug"]))
                    team = team_result.scalars().first()

                    if not team:
                        print(f"    ❌ Team '{ownership_info['team_slug']}' not found. Skipping...")
                        continue

                    # Check if ownership already exists
                    existing_result = await session.execute(
                        select(TeamOwnership).where(
                            (TeamOwnership.pool_id == pool.id)
                            & (TeamOwnership.season == ownership_info["season"])
                            & (TeamOwnership.team_slug == ownership_info["team_slug"])
                        )
                    )
                    existing = existing_result.scalars().first()

                    if existing is None:
                        ownership = TeamOwnership(
                            pool_id=pool.id,
                            season=ownership_info["season"],
                            team_slug=ownership_info["team_slug"],
                            owner_id=member_map[ownership_info["owner_name"]].id,
                            auction_price=ownership_info["auction_price"],
                        )
                        session.add(ownership)
                        ownerships_created += 1
                        print(
                            f"    ✅ {ownership_info['owner_name']} -> {ownership_info['team_slug']} (${ownership_info['auction_price']}) [{ownership_info['season']}]"
                        )
                    else:
                        print(
                            f"    ⏭️  {ownership_info['owner_name']} -> {ownership_info['team_slug']} [{ownership_info['season']}] (already exists)"
                        )

                # Commit changes for this pool
                await session.commit()
                print(f"  🎉 Successfully seeded {ownerships_created} team ownerships for pool '{current_pool_slug}'!")

        except Exception as e:
            await session.rollback()
            print(f"❌ Error seeding team ownerships: {e}")
            raise


async def main():
    """Main entry point for the script."""
    import argparse

    parser = argparse.ArgumentParser(description="Seed team ownership data")
    parser.add_argument("--pool", help="Specific pool slug to seed team owners for")
    parser.add_argument("--force", action="store_true", help="Force overwrite existing team ownerships")

    args = parser.parse_args()

    try:
        await seed_team_owners(pool_slug=args.pool, force=args.force)
    except Exception as e:
        print(f"❌ Script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
