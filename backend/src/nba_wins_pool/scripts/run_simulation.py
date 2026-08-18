#!/usr/bin/env python3
"""Script to run the NBA season Monte Carlo simulation and persist results."""

import asyncio
import logging

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.services.nba_simulator.nba_simulator_service import run_projections_and_simulation

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


async def main():
    async for db in get_db_session():
        await run_projections_and_simulation(db)
        break


if __name__ == "__main__":
    asyncio.run(main())
