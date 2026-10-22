from unittest.mock import PropertyMock, patch

import pytest

from nba_wins_pool.services.nba_live_data import NbaLiveData
from nba_wins_pool.utils import result_cache as result_cache_module
from nba_wins_pool.utils.data_version import bump_db_version
from nba_wins_pool.utils.result_cache import CURRENT_MAX_AGE_SECONDS, ResultCache


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Counter:
    def __init__(self):
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        return {"calls": self.calls, "rows": [{"wins": 1}]}


@pytest.fixture
def live_version():
    """Pretend the live poller is running; yields a setter for its version."""
    state = {"version": 1}
    with (
        patch.object(NbaLiveData, "is_running", new_callable=PropertyMock, return_value=True),
        patch.object(NbaLiveData, "version", new_callable=PropertyMock, side_effect=lambda: state["version"]),
    ):
        yield state


@pytest.mark.asyncio
async def test_always_computes_when_the_poller_is_not_running():
    cache = ResultCache()
    compute = Counter()

    await cache.get("key", compute, current=True)
    await cache.get("key", compute, current=True)

    assert compute.calls == 2


@pytest.mark.asyncio
async def test_reuses_a_result_until_the_database_changes(live_version):
    cache = ResultCache(clock=FakeClock())
    compute = Counter()

    await cache.get("key", compute, current=False)
    await cache.get("key", compute, current=False)
    bump_db_version()
    await cache.get("key", compute, current=False)

    assert compute.calls == 2


@pytest.mark.asyncio
async def test_current_results_are_recomputed_when_live_data_changes(live_version):
    cache = ResultCache(clock=FakeClock())
    compute = Counter()

    await cache.get("key", compute, current=True)
    live_version["version"] = 2
    await cache.get("key", compute, current=True)

    assert compute.calls == 2


@pytest.mark.asyncio
async def test_past_results_ignore_live_data_and_age(live_version):
    clock = FakeClock()
    cache = ResultCache(clock=clock)
    compute = Counter()

    await cache.get("key", compute, current=False)
    live_version["version"] = 2
    clock.now += 3600
    await cache.get("key", compute, current=False)

    assert compute.calls == 1


@pytest.mark.asyncio
async def test_current_results_are_never_older_than_ten_seconds(live_version):
    clock = FakeClock()
    cache = ResultCache(clock=clock)
    compute = Counter()

    await cache.get("key", compute, current=True)
    clock.now += CURRENT_MAX_AGE_SECONDS - 1
    await cache.get("key", compute, current=True)
    clock.now += 1
    await cache.get("key", compute, current=True)

    assert compute.calls == 2


@pytest.mark.asyncio
async def test_each_caller_gets_its_own_copy(live_version):
    cache = ResultCache(clock=FakeClock())
    compute = Counter()

    first = await cache.get("key", compute, current=False)
    first["rows"][0]["wins"] = 99
    second = await cache.get("key", compute, current=False)

    assert second["rows"][0]["wins"] == 1


def test_module_exposes_a_shared_cache():
    assert isinstance(result_cache_module.result_cache, ResultCache)
