"""Loader for data/pool_seasons.json: per pool season history that isn't derivable from the roster slots."""

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Tuple

POOL_SEASONS_JSON = Path(__file__).parent / "data" / "pool_seasons.json"
DEFAULT_STARTING_BUDGET = Decimal(200)
FIRST_APP_SEASON = "2025-26"


@dataclass(frozen=True)
class PoolSeasonRecord:
    """One pool season from pool_seasons.json.

    starting_budget is per drafter, auction_at is when the auction took place (UTC), projection_date is the day of the
    odds the preseason valuations were computed from, and rules is the buy-in and payout text shown on the season page.
    """

    pool: str
    season: str
    starting_budget: Decimal
    auction_at: Optional[datetime]
    projection_date: Optional[date]
    rules: Optional[str]


def is_file_owned(season: str) -> bool:
    """True for seasons that predate the app, whose data the checked-in files are the source of truth for.

    From FIRST_APP_SEASON on, the app owns the data, so seeding only fills in what is missing.
    """
    return season < FIRST_APP_SEASON


def _naive_utc(value: str) -> datetime:
    """Parse an ISO timestamp as naive UTC, the convention of every datetime column in the DB."""
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def load_pool_seasons(path: Path = POOL_SEASONS_JSON) -> Dict[Tuple[str, str], PoolSeasonRecord]:
    """Load the JSON keyed by (pool slug, season). Missing or empty fields mean "unknown"; rules are a list of lines."""
    records: Dict[Tuple[str, str], PoolSeasonRecord] = {}
    with open(path, encoding="utf-8") as f:
        for row in json.load(f):
            record = PoolSeasonRecord(
                pool=row["pool"],
                season=row["season"],
                starting_budget=Decimal(row["starting_budget"])
                if row.get("starting_budget")
                else DEFAULT_STARTING_BUDGET,
                auction_at=_naive_utc(row["auction_at"]) if row.get("auction_at") else None,
                projection_date=date.fromisoformat(row["projection_date"]) if row.get("projection_date") else None,
                rules="\n".join(row["rules"]).strip() if row.get("rules") else None,
            )
            records[(record.pool, record.season)] = record
    return records
