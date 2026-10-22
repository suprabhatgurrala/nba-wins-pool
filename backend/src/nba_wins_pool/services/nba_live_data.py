"""Background poller that keeps one in-memory snapshot of the current NBA season's live data."""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import pandas as pd

from nba_wins_pool.types.nba_game_status import NBAGameStatus
from nba_wins_pool.utils.time import utc_now

logger = logging.getLogger(__name__)

LIVE_POLL_SECONDS = 10
IDLE_POLL_SECONDS = 300
TIPOFF_LEAD = timedelta(minutes=15)
LATE_TIPOFF_WINDOW = timedelta(hours=6)


@dataclass(frozen=True)
class LiveInputs:
    season: str
    scoreboard_date: date
    game_df: pd.DataFrame
    odds: dict[str, dict]


@dataclass(frozen=True)
class LiveSnapshot:
    """One poll's data. Never modified after it's built; readers copy ``game_df`` before changing it."""

    season: str
    scoreboard_date: date
    game_df: pd.DataFrame
    odds: dict[str, dict]
    version: int
    fingerprint: str
    checked_at: datetime


def fetch_live_inputs() -> LiveInputs:
    """Fetch the schedule, gamecardfeed and FanDuel game odds once, bypassing every cache."""
    from nba_wins_pool.services.nba_data_service import NbaDataService

    service = NbaDataService(db_session=None, external_data_repository=None)
    raw_gamecardfeed, raw_schedule = service._fetch_current_season_raw_uncached()
    _, _, scoreboard_date = service._parse_gamecardfeed(raw_gamecardfeed)
    return LiveInputs(
        season=raw_schedule.get("leagueSchedule", {}).get("seasonYear"),
        scoreboard_date=scoreboard_date,
        game_df=service._build_current_schedule_df((raw_gamecardfeed, raw_schedule)),
        odds=service._fetch_sportsbook_game_win_probabilities(),
    )


def fingerprint(inputs: LiveInputs) -> str:
    """Hash of everything a reader can see, so the version only moves when the data does."""
    digest = hashlib.sha256()
    digest.update(f"{inputs.season}|{inputs.scoreboard_date.isoformat()}".encode())
    digest.update(inputs.game_df.to_json(orient="split", date_format="iso", default_handler=str).encode())
    digest.update(json.dumps(inputs.odds, sort_keys=True, default=str).encode())
    return digest.hexdigest()


def seconds_until_next_poll(game_df: pd.DataFrame, now: datetime) -> float:
    """Poll every 10 s while a game is live or about to tip off, every 5 minutes otherwise."""
    if game_df.empty or "status" not in game_df or "date_time" not in game_df:
        return IDLE_POLL_SECONDS
    if (game_df["status"] == NBAGameStatus.INGAME).any():
        return LIVE_POLL_SECONDS
    tipoffs = game_df.loc[game_df["status"] == NBAGameStatus.PREGAME, "date_time"]
    now_ts = pd.Timestamp(now)
    if ((tipoffs <= now_ts + TIPOFF_LEAD) & (tipoffs >= now_ts - LATE_TIPOFF_WINDOW)).any():
        return LIVE_POLL_SECONDS
    upcoming = tipoffs[tipoffs > now_ts]
    if upcoming.empty:
        return IDLE_POLL_SECONDS
    until_live = (upcoming.min() - TIPOFF_LEAD - now_ts).total_seconds()
    return min(IDLE_POLL_SECONDS, max(LIVE_POLL_SECONDS, until_live))


class NbaLiveData:
    """Holds the latest live snapshot and refreshes it in the background while the app runs.

    nba.com is never fetched more often than every ``LIVE_POLL_SECONDS``, whether the fetch comes from the
    background loop or a request arriving before the first poll finished.
    """

    def __init__(
        self, fetch: Callable[[], LiveInputs] = fetch_live_inputs, clock: Callable[[], float] = time.monotonic
    ):
        self._fetch = fetch
        self._clock = clock
        self._snapshot: LiveSnapshot | None = None
        self._last_fetch_started: float | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def version(self) -> int:
        return self._snapshot.version if self._snapshot else 0

    async def current(self) -> LiveSnapshot:
        """The latest snapshot, fetching the first one if no poll has finished yet."""
        if self._snapshot is None:
            await self.refresh()
        return self._snapshot

    async def refresh(self) -> LiveSnapshot:
        """Fetch new data unless a fetch started under ``LIVE_POLL_SECONDS`` ago, and return the latest snapshot."""
        async with self._lock:
            now = self._clock()
            if (
                self._snapshot is not None
                and self._last_fetch_started is not None
                and now - self._last_fetch_started < LIVE_POLL_SECONDS
            ):
                return self._snapshot
            self._last_fetch_started = now
            inputs = await asyncio.to_thread(self._fetch)
            previous = self._snapshot
            new_fingerprint = fingerprint(inputs)
            changed = previous is None or previous.fingerprint != new_fingerprint
            self._snapshot = LiveSnapshot(
                season=inputs.season,
                scoreboard_date=inputs.scoreboard_date,
                game_df=inputs.game_df,
                odds=inputs.odds,
                version=(previous.version if previous else 0) + (1 if changed else 0),
                fingerprint=new_fingerprint,
                checked_at=utc_now(),
            )
            return self._snapshot

    async def _run(self) -> None:
        while True:
            delay = IDLE_POLL_SECONDS
            try:
                snapshot = await self.refresh()
                delay = seconds_until_next_poll(snapshot.game_df, datetime.now(timezone.utc))
            except Exception:
                logger.warning("NBA live data poll failed; keeping the last snapshot", exc_info=True)
                delay = LIVE_POLL_SECONDS
            await asyncio.sleep(delay)

    def start(self) -> None:
        if not self.is_running:
            self._task = asyncio.create_task(self._run(), name="nba-live-data-poller")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


nba_live_data = NbaLiveData()
