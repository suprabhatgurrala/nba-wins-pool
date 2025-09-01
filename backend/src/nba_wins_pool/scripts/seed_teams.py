#!/usr/bin/env python3
"""
Script to seed NBA team data into the database.
"""

import asyncio
import json
import sys
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from nba_wins_pool.db.core import engine
from nba_wins_pool.models.team import Team


async def load_team_data() -> list[dict]:
    """Load NBA team data from JSON file."""
    data_file = Path(__file__).parent / "data" / "nba_teams.json"

    if not data_file.exists():
        raise FileNotFoundError(f"Team data file not found: {data_file}")

    with open(data_file, "r") as f:
        return json.load(f)


async def seed_teams(force: bool = False) -> None:
    """
    Seed NBA teams into the database.

    Args:
        force: If True, delete existing teams before seeding
    """
    print("🏀 Starting NBA team seeding...")

    # Load team data
    try:
        team_data = await load_team_data()
        print(f"📊 Loaded {len(team_data)} teams from data file")
    except Exception as e:
        print(f"❌ Error loading team data: {e}")
        return

    # Create database session
    async with AsyncSession(engine) as session:
        try:
            # Check if teams already exist
            existing_teams_result = await session.execute(select(Team))
            existing_teams = existing_teams_result.scalars().all()
            existing_count = len(existing_teams)

            if existing_count > 0 and not force:
                print(f"⚠️  Found {existing_count} existing teams. Use --force to overwrite.")
                return

            if force and existing_count > 0:
                print(f"🗑️  Deleting {existing_count} existing teams...")
                # Delete existing teams
                for team in existing_teams:
                    await session.delete(team)
                await session.commit()

            # Insert new teams
            print("📝 Inserting teams...")
            teams_created = 0

            for team_info in team_data:
                # Check if team already exists (by slug or nba_id)
                existing_result = await session.execute(
                    select(Team).where((Team.slug == team_info["slug"]) | (Team.nba_id == team_info["nba_id"]))
                )
                existing = existing_result.scalars().first()

                if existing is None:
                    team = Team(
                        slug=team_info["slug"],
                        nba_id=team_info["nba_id"],
                        name=team_info["name"],
                        logo_url=team_info.get("logo_url"),
                    )
                    session.add(team)
                    teams_created += 1
                    print(f"  ✅ {team_info['slug']} - {team_info['name']}")
                else:
                    print(f"  ⏭️  {team_info['slug']} - {team_info['name']} (already exists)")

            # Commit changes
            await session.commit()
            print(f"🎉 Successfully seeded {teams_created} NBA teams!")

        except Exception as e:
            await session.rollback()
            print(f"❌ Error seeding teams: {e}")
            raise


async def main():
    """Main entry point for the script."""
    import argparse

    parser = argparse.ArgumentParser(description="Seed NBA team data")
    parser.add_argument("--force", action="store_true", help="Force overwrite existing teams")

    args = parser.parse_args()

    try:
        await seed_teams(force=args.force)
    except Exception as e:
        print(f"❌ Script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
