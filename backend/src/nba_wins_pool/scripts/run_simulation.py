#!/usr/bin/env python3
"""Script to run the NBA season Monte Carlo simulation and persist results."""

import asyncio
import logging

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.job_definitions import fetch_nba_projections_job

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

if __name__ == "__main__":
    asyncio.run(fetch_nba_projections_job(get_db_session))
