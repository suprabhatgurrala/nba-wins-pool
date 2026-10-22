"""Cache for computed results (leaderboards, wins races, histories), keyed by the versions of their inputs."""

import asyncio
import copy
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Hashable

from nba_wins_pool.services.nba_live_data import nba_live_data
from nba_wins_pool.utils.data_version import db_version

CURRENT_MAX_AGE_SECONDS = 10


@dataclass
class _Entry:
    versions: tuple
    computed_at: float
    value: Any


class ResultCache:
    """Reuses a result until its inputs change.

    A result built from current-season data is reused only while neither the live NBA data nor the database has
    changed, and never for more than 10 s. One built from past seasons alone is reused until the database
    changes. Each caller gets its own deep copy. Nothing is cached unless the live poller is running (only in the
    app), so tests and scripts always compute.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._entries: dict[Hashable, _Entry] = {}
        self._locks: dict[Hashable, asyncio.Lock] = {}

    async def get(self, key: Hashable, compute: Callable[[], Awaitable[Any]], *, current: bool) -> Any:
        if not nba_live_data.is_running:
            return await compute()
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            versions = (db_version(), nba_live_data.version if current else None)
            entry = self._entries.get(key)
            if entry is not None and entry.versions == versions and self._fresh(entry, current):
                return copy.deepcopy(entry.value)
            value = await compute()
            self._entries[key] = _Entry(versions, self._clock(), value)
            return copy.deepcopy(value)

    def _fresh(self, entry: _Entry, current: bool) -> bool:
        return not current or self._clock() - entry.computed_at < CURRENT_MAX_AGE_SECONDS

    def clear(self) -> None:
        self._entries.clear()


result_cache = ResultCache()
