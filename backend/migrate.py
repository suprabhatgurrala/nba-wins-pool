#!/usr/bin/env python3
"""Simple migration script for Docker usage"""

import sys
from alembic import command
from alembic.config import Config
import os


def get_alembic_config() -> Config:
    """Get Alembic configuration"""
    alembic_cfg = Config("alembic.ini")
    # Use DATABASE_URL from environment
    database_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@database:5432/nba_wins_pool")
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    return alembic_cfg


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python migrate.py upgrade    # Run migrations")
        print("  python migrate.py revision <message>  # Create new migration")
        sys.exit(1)

    command_name = sys.argv[1]
    alembic_cfg = get_alembic_config()

    if command_name == "upgrade":
        print("Running migrations...")
        command.upgrade(alembic_cfg, "head")
        print("✅ Migrations completed")

    elif command_name == "revision":
        if len(sys.argv) < 3:
            print("Please provide a migration message")
            sys.exit(1)
        message = " ".join(sys.argv[2:])
        print(f"Creating migration: {message}")
        command.revision(alembic_cfg, message=message, autogenerate=True)
        print("✅ Migration created")

    else:
        print(f"Unknown command: {command_name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
