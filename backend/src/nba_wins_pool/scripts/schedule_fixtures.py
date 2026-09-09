"""Read and write the checked-in NBA schedule cache fixtures.

stats.nba.com's `scheduleleaguev2` endpoint routinely takes minutes to return a
full season schedule, and often never returns at all, which makes seeding a
fresh database from it unusable in CI. Raw responses for completed seasons never
change, so they are dumped to gzipped JSON under `data/nba_schedule_cache/` and
seeded straight into the `external_data` cache table.

Use `dump_nba_schedule_cache.py` to refresh the fixtures from a database that
already has the cache populated.
"""

import gzip
import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "data" / "nba_schedule_cache"
FIXTURE_SUFFIX = ".json.gz"


def fixture_path(season: str) -> Path:
    """Return the on-disk fixture path for a season (which may not exist)."""
    return FIXTURE_DIR / f"{season}{FIXTURE_SUFFIX}"


def load_fixture(season: str) -> dict | None:
    """Load a season's raw schedule response from disk.

    Args:
        season: Season string in format YYYY-YY.

    Returns:
        The raw NBA API schedule dictionary, or None if no fixture exists.
    """
    path = fixture_path(season)
    if not path.is_file():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_fixture(season: str, raw_schedule: dict) -> Path:
    """Write a season's raw schedule response to disk as gzipped JSON.

    Args:
        season: Season string in format YYYY-YY.
        raw_schedule: Raw NBA API schedule dictionary.

    Returns:
        Path the fixture was written to.
    """
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = fixture_path(season)
    # mtime=0 so re-dumping unchanged data produces an identical file (no repo churn).
    with gzip.GzipFile(path, "wb", compresslevel=9, mtime=0) as gz:
        gz.write(json.dumps(raw_schedule, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return path
