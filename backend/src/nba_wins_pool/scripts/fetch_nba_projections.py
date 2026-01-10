#!/usr/bin/env python3
"""
Script to fetch and store NBA win projections from FanDuel.
"""

import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import engine
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.repositories.nba_projections_repository import NBAProjectionsRepository
from nba_wins_pool.repositories.team_repository import TeamRepository
from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.services.nba_espn_projections_service import NBAEspnProjectionsService
from nba_wins_pool.services.nba_vegas_projections_service import NBAVegasProjectionsService

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("fetch_projections")


async def main():
    """Main entry point for the script."""
    logger.info("Starting projections fetch (FanDuel and ESPN)...")

    try:
        async with AsyncSession(engine) as session:
            # Initialize repositories and services
            team_repo = TeamRepository(session)
            external_repo = ExternalDataRepository(session)
            nba_projections_repo = NBAProjectionsRepository(session)
            nba_data_service = NbaDataService(session, external_repo)

            # FanDuel (Vegas) service
            vegas_service = NBAVegasProjectionsService(
                db_session=session,
                nba_data_service=nba_data_service,
                team_repository=team_repo,
                nba_projections_repository=nba_projections_repo,
            )

            # ESPN service
            espn_service = NBAEspnProjectionsService(
                db_session=session,
                team_repository=team_repo,
                nba_projections_repository=nba_projections_repo,
            )

            # Fetch and write projections
            vegas_count = await vegas_service.write_projections()
            espn_count = await espn_service.write_projections()

            # Commit changes
            await session.commit()

            logger.info(f"FanDuel projections fetch completed. Successfully wrote {vegas_count} records.")
            logger.info(f"ESPN BPI projections fetch completed. Successfully wrote {espn_count} records.")

    except Exception as e:
        logger.error(f"Failed to fetch projections: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
