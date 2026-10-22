from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from nba_wins_pool.services.nba_live_data import (
    IDLE_POLL_SECONDS,
    LIVE_POLL_SECONDS,
    LiveInputs,
    NbaLiveData,
    seconds_until_next_poll,
)
from nba_wins_pool.types.nba_game_status import NBAGameStatus

NOW = datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc)


def _games(*games: tuple[NBAGameStatus, datetime]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_id": [str(i) for i in range(len(games))],
            "status": [status for status, _ in games],
            "date_time": pd.to_datetime([tip for _, tip in games], utc=True),
            "home_score": [0] * len(games),
        }
    )


def _inputs(home_score: int = 0) -> LiveInputs:
    game_df = _games((NBAGameStatus.INGAME, NOW))
    game_df["home_score"] = home_score
    return LiveInputs(season="2026-27", scoreboard_date=date(2026, 10, 21), game_df=game_df, odds={})


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_version_moves_only_when_the_data_changes():
    responses = iter([_inputs(10), _inputs(10), _inputs(12)])
    clock = FakeClock()
    live = NbaLiveData(fetch=lambda: next(responses), clock=clock)

    first = await live.refresh()
    clock.now += LIVE_POLL_SECONDS
    same = await live.refresh()
    clock.now += LIVE_POLL_SECONDS
    changed = await live.refresh()

    assert (first.version, same.version, changed.version) == (1, 1, 2)
    assert first.checked_at <= same.checked_at <= changed.checked_at


@pytest.mark.asyncio
async def test_never_fetches_more_often_than_every_ten_seconds():
    calls = []
    clock = FakeClock()
    live = NbaLiveData(fetch=lambda: calls.append(1) or _inputs(), clock=clock)

    await live.refresh()
    clock.now += LIVE_POLL_SECONDS - 1
    await live.refresh()
    await live.current()

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_failed_fetch_keeps_the_last_snapshot_and_its_check_time():
    responses = iter([_inputs(10)])

    def fetch():
        try:
            return next(responses)
        except StopIteration:
            raise ConnectionError("nba.com unreachable") from None

    clock = FakeClock()
    live = NbaLiveData(fetch=fetch, clock=clock)
    first = await live.refresh()
    clock.now += LIVE_POLL_SECONDS

    with pytest.raises(ConnectionError):
        await live.refresh()

    assert await live.current() is first


def test_polls_every_ten_seconds_while_a_game_is_live():
    assert seconds_until_next_poll(_games((NBAGameStatus.INGAME, NOW)), NOW) == LIVE_POLL_SECONDS


def test_polls_every_ten_seconds_from_fifteen_minutes_before_tipoff():
    game_df = _games((NBAGameStatus.PREGAME, NOW + timedelta(minutes=14)))

    assert seconds_until_next_poll(game_df, NOW) == LIVE_POLL_SECONDS


def test_keeps_polling_a_game_whose_tipoff_is_late():
    game_df = _games((NBAGameStatus.PREGAME, NOW - timedelta(minutes=20)))

    assert seconds_until_next_poll(game_df, NOW) == LIVE_POLL_SECONDS


def test_polls_every_five_minutes_when_no_game_is_near():
    game_df = _games(
        (NBAGameStatus.FINAL, NOW - timedelta(hours=3)),
        (NBAGameStatus.PREGAME, NOW + timedelta(hours=20)),
    )

    assert seconds_until_next_poll(game_df, NOW) == IDLE_POLL_SECONDS
    assert seconds_until_next_poll(pd.DataFrame(), NOW) == IDLE_POLL_SECONDS


def test_wakes_up_fifteen_minutes_before_the_next_tipoff():
    game_df = _games((NBAGameStatus.PREGAME, NOW + timedelta(minutes=18)))

    assert seconds_until_next_poll(game_df, NOW) == 180
