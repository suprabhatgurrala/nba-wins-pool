#!/usr/bin/env python3
"""Dump cached NBA schedules from the database into checked-in fixtures.

Reads the `nba:schedule:*` rows out of `external_data` and writes each one to
`data/nba_schedule_cache/<season>.json.gz`, which `seed_data.py --nba-cache`
seeds back into a fresh database without touching stats.nba.com.

Usage:
    make run-script script=dump_nba_schedule_cache.py
    make run-script script=dump_nba_schedule_cache.py args='--season 2024-25'
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from nba_wins_pool.db.core import engine
from nba_wins_pool.repositories.external_data_repository import ExternalDataRepository
from nba_wins_pool.scripts.schedule_fixtures import (
    CACHE_KEY_PREFIX,
    cache_key,
    season_from_cache_key,
    write_fixture,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("dump_nba_schedule_cache")


async def dump_schedules(seasons: list[str] | None) -> int:
    """Write cached schedules to fixture files.

    Args:
        seasons: Specific seasons to dump, or None for every cached season.

    Returns:
        Number of fixtures written.
    """
    async with AsyncSession(engine) as session:
        repo = ExternalDataRepository(session)

        if seasons:
            records = []
            for season in seasons:
                record = await repo.get_by_key(cache_key(season))
                if record is None:
                    logger.warning(f"No cached schedule for season {season}; skipping")
                    continue
                records.append(record)
        else:
            records = await repo.get_by_key_prefix(CACHE_KEY_PREFIX)

        written = 0
        for record in sorted(records, key=lambda r: r.key):
            season = season_from_cache_key(record.key)
            if not record.data_json:
                logger.warning(f"Cached schedule for season {season} is empty; skipping")
                continue

            path = write_fixture(season, record.data_json)
            size_kb = path.stat().st_size / 1024
            logger.info(f"Wrote {path} ({size_kb:.0f} KB, cached {record.updated_at:%Y-%m-%d})")
            written += 1

    return written


async def main():
    parser = argparse.ArgumentParser(description="Dump cached NBA schedules to fixture files")
    parser.add_argument(
        "--season",
        action="append",
        dest="seasons",
        help="Season to dump in YYYY-YY format (repeatable). Defaults to every cached season.",
    )
    args = parser.parse_args()

    try:
        written = await dump_schedules(args.seasons)
    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)

    if not written:
        logger.error("No schedules dumped. Is the database seeded with `make seed-data-nba-cache`?")
        sys.exit(1)

    logger.info(f"Dumped {written} season schedule(s)")


if __name__ == "__main__":
    asyncio.run(main())
