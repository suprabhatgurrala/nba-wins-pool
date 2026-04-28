#!/usr/bin/env python3
"""Script to run the NBA season Monte Carlo simulation and persist results."""

import argparse
import asyncio
import logging
import sys

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.job_definitions import fetch_nba_projections_job

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("run_simulation")


async def main(calibrate: bool, fetch_projections: bool):
    if fetch_projections:
        logger.info("Fetching fresh NBA projections (FanDuel + ESPN)...")
        try:
            await fetch_nba_projections_job(get_db_session)
        except Exception as e:
            logger.error(f"Projections fetch failed: {e}", exc_info=True)
            sys.exit(1)

    from nba_wins_pool.services.nba_simulator.nba_simulator_service import run_and_save_simulation

    logger.info("Starting NBA season simulation (calibrate=%s)...", calibrate)
    try:
        async for db in get_db_session():
            await run_and_save_simulation(db, calibrate=calibrate)
            break
    except Exception as e:
        logger.error(f"Simulation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the NBA season Monte Carlo simulation.")
    parser.add_argument(
        "--no-calibrate",
        action="store_true",
        dest="no_calibrate",
        help="Skip Nelder-Mead calibration (faster; stores raw ESPN BPI as power rating).",
    )
    parser.add_argument(
        "--fetch-projections",
        action="store_true",
        help="Fetch fresh FanDuel and ESPN projections before running the simulation.",
    )
    args = parser.parse_args()

    asyncio.run(main(calibrate=not args.no_calibrate, fetch_projections=args.fetch_projections))
