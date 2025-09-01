#!/usr/bin/env python3
"""
Script to seed season milestone data into the database.
"""

import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from nba_wins_pool.db.core import engine
from nba_wins_pool.models.season_milestone import SeasonMilestone
from nba_wins_pool.models.pool import Pool


async def load_milestone_data() -> list[dict]:
    """Load milestone data from CSV file."""
    data_file = Path(__file__).parent.parent / "data" / "milestones.csv"

    if not data_file.exists():
        raise FileNotFoundError(f"Milestone data file not found: {data_file}")

    milestones = []
    with open(data_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse the date string
            date_obj = datetime.strptime(row["date"], "%Y-%m-%d").date()
            milestones.append(
                {
                    "slug": row["slug"],
                    "season": row["season"],
                    "date": date_obj,
                    "description": row["description"],
                }
            )

    return milestones


async def seed_milestones(pool_slug: str = None, force: bool = False) -> None:
    """
    Seed season milestones into the database.

    Args:
        pool_slug: Specific pool to seed milestones for (if None, seeds for all pools)
        force: If True, delete existing milestones before seeding
    """
    print("📅 Starting season milestone seeding...")

    # Load milestone data
    try:
        milestone_data = await load_milestone_data()
        print(f"📊 Loaded {len(milestone_data)} milestones from data file")
    except Exception as e:
        print(f"❌ Error loading milestone data: {e}")
        return

    # Create database session
    async with AsyncSession(engine) as session:
        try:
            # Get pools to seed milestones for
            if pool_slug:
                pool_result = await session.execute(select(Pool).where(Pool.slug == pool_slug))
                pools = [pool_result.scalars().first()]
                if not pools[0]:
                    print(f"❌ Pool '{pool_slug}' not found")
                    return
            else:
                pool_result = await session.execute(select(Pool))
                pools = pool_result.scalars().all()

            if not pools:
                print("❌ No pools found. Please create pools first.")
                return

            print(f"🎯 Seeding milestones for {len(pools)} pool(s)")

            for pool in pools:
                # Store pool info before any database operations to avoid detached instance issues
                pool_slug = pool.slug
                pool_name = pool.name
                pool_id = pool.id
                
                print(f"\n🏊 Processing pool: {pool_slug} - {pool_name}")

                # Check if milestones already exist for this pool
                existing_milestones_result = await session.execute(
                    select(SeasonMilestone).where(SeasonMilestone.pool_id == pool_id)
                )
                existing_milestones = existing_milestones_result.scalars().all()
                existing_count = len(existing_milestones)

                if existing_count > 0 and not force:
                    print(f"  ⚠️  Found {existing_count} existing milestones. Use --force to overwrite.")
                    continue

                if force and existing_count > 0:
                    print(f"  🗑️  Deleting {existing_count} existing milestones...")
                    for milestone in existing_milestones:
                        await session.delete(milestone)
                    await session.commit()

                # Insert new milestones
                print("  📝 Inserting milestones...")
                milestones_created = 0

                for milestone_info in milestone_data:
                    # Check if milestone already exists (by pool, season, and slug)
                    existing_result = await session.execute(
                        select(SeasonMilestone).where(
                            (SeasonMilestone.pool_id == pool_id)
                            & (SeasonMilestone.season == milestone_info["season"])
                            & (SeasonMilestone.slug == milestone_info["slug"])
                        )
                    )
                    existing = existing_result.scalars().first()

                    if existing is None:
                        milestone = SeasonMilestone(
                            pool_id=pool_id,
                            slug=milestone_info["slug"],
                            season=milestone_info["season"],
                            date=milestone_info["date"],
                            description=milestone_info["description"],
                        )
                        session.add(milestone)
                        milestones_created += 1
                        print(
                            f"    ✅ {milestone_info['slug']} - {milestone_info['description']} ({milestone_info['season']})"
                        )
                    else:
                        print(
                            f"    ⏭️  {milestone_info['slug']} - {milestone_info['description']} ({milestone_info['season']}) (already exists)"
                        )

                # Commit changes for this pool
                await session.commit()
                print(f"  🎉 Successfully seeded {milestones_created} milestones for pool '{pool_slug}'!")

        except Exception as e:
            await session.rollback()
            print(f"❌ Error seeding milestones: {e}")
            raise


async def main():
    """Main entry point for the script."""
    import argparse

    parser = argparse.ArgumentParser(description="Seed season milestone data")
    parser.add_argument("--pool", help="Specific pool slug to seed milestones for")
    parser.add_argument("--force", action="store_true", help="Force overwrite existing milestones")

    args = parser.parse_args()

    try:
        await seed_milestones(pool_slug=args.pool, force=args.force)
    except Exception as e:
        print(f"❌ Script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
