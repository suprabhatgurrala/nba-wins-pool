#!/usr/bin/env python3
"""Store synthetic hourly simulation runs for one pool season, so the e2e stack has a win probability history."""

import argparse
import asyncio
import random
from datetime import datetime, timedelta

from sqlmodel import select

from nba_wins_pool.db.core import get_db_session
from nba_wins_pool.models.pool import Pool
from nba_wins_pool.models.roster import Roster
from nba_wins_pool.models.simulation_results import SimulationRosterResult, SimulationRun

START = datetime(2026, 3, 25, 12, 0)
HOURS = 18 * 24


async def main(pool_slug: str, season: str) -> None:
    async for db in get_db_session():
        if (await db.execute(select(SimulationRun.id).where(SimulationRun.season == season).limit(1))).first():
            print(f"{season} already has simulation runs")
            return
        pool = (await db.execute(select(Pool).where(Pool.slug == pool_slug))).scalar_one()
        rosters = (
            (
                await db.execute(
                    select(Roster).where(Roster.pool_id == pool.id, Roster.season == season).order_by(Roster.name)
                )
            )
            .scalars()
            .all()
        )
        rng = random.Random(0)
        weights = [1.0 + i for i in range(len(rosters))]
        for hour in range(HOURS):
            weights = [max(0.05, w * (1 + rng.gauss(0, 0.03))) for w in weights]
            total = sum(weights)
            run = SimulationRun(
                season=season, phase="Regular Season", n_sims=1000, simulated_at=START + timedelta(hours=hour)
            )
            db.add(run)
            await db.flush()
            db.add_all(
                SimulationRosterResult(run_id=run.id, roster_id=r.id, pool_id=pool.id, win_pct=w / total)
                for r, w in zip(rosters, weights)
            )
        await db.commit()
        print(f"Stored {HOURS} simulation runs for {pool_slug} {season}")
        break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", default="sg")
    parser.add_argument("--season", default="2025-26")
    args = parser.parse_args()
    asyncio.run(main(args.pool, args.season))
