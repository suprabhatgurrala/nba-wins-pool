import asyncio
import time
from functools import wraps


def ttl_cache(ttl_seconds):
    """
    A simple in-memory cache decorator with a time-to-live (TTL).
    Supports both sync and async functions. Excludes `self` from the cache key
    so the cache is shared across instances of the same class.
    """
    cache = {}

    def decorator(func):
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def wrapper(*args, **kwargs):
                key = (args[1:], frozenset(kwargs.items()))
                current_time = time.monotonic()
                if key in cache:
                    cached_value, expiration_time = cache[key]
                    if current_time < expiration_time:
                        return cached_value
                    del cache[key]
                result = await func(*args, **kwargs)
                cache[key] = (result, current_time + ttl_seconds)
                return result
        else:

            @wraps(func)
            def wrapper(*args, **kwargs):
                key = (args[1:], frozenset(kwargs.items()))
                current_time = time.monotonic()
                if key in cache:
                    cached_value, expiration_time = cache[key]
                    if current_time < expiration_time:
                        return cached_value
                    del cache[key]
                result = func(*args, **kwargs)
                cache[key] = (result, current_time + ttl_seconds)
                return result

        wrapper.cache_clear = cache.clear
        return wrapper

    return decorator
