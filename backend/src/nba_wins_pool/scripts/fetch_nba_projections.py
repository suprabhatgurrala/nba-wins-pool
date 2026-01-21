#!/usr/bin/env python3
"""
Script to fetch and store NBA win projections from FanDuel.
"""

import asyncio
import logging
import sys

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.job_definitions import fetch_nba_projections_job

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("fetch_projections")


async def main():
    """Main entry point for the script."""
    logger.info("Starting projections fetch (FanDuel and ESPN)...")

    try:
        await fetch_nba_projections_job(get_db_session)
    except Exception as e:
        logger.error(f"Failed to fetch projections: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
