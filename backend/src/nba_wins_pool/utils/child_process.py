import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable


async def run_in_child_process(fn: Callable[..., Any], *args: Any) -> Any:
    """Run ``fn(*args)`` in a fresh child process so its CPU and memory use never block the event loop."""
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        return await asyncio.get_running_loop().run_in_executor(pool, fn, *args)
    finally:
        pool.shutdown(wait=False)
