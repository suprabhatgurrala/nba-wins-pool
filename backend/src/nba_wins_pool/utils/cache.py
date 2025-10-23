import time
from functools import wraps


def ttl_cache(ttl_seconds):
    """
    A simple in-memory cache decorator with a time-to-live (TTL).
    """
    cache = {}

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, frozenset(kwargs.items()))  # Create a hashable key
            current_time = time.monotonic()

            if key in cache:
                cached_value, expiration_time = cache[key]
                if current_time < expiration_time:
                    return cached_value
                else:
                    # Cache expired, remove it
                    del cache[key]

            # Cache miss or expired, call the original function
            result = func(*args, **kwargs)
            cache[key] = (result, current_time + ttl_seconds)
            return result
        return wrapper
    return decorator