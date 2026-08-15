import time
import functools
import logging
from threading import Lock
from typing import Callable, Any

logger = logging.getLogger("app.core.cache")


def ttl_cache(seconds: int, maxsize: int = 256) -> Callable:
    """
    Minimal in-process TTL cache decorator for functions with hashable arguments.
    No Redis in this stack (see KICKOFF_PROMPT.md), and a single-process cache is
    enough to avoid re-hitting rate-limited external APIs for repeated lookups
    (e.g. same destination requested twice within a session).
    """
    def decorator(func: Callable) -> Callable:
        store: dict[Any, tuple[float, Any]] = {}
        lock = Lock()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()

            with lock:
                cached = store.get(key)
                if cached is not None and now - cached[0] < seconds:
                    return cached[1]

            result = func(*args, **kwargs)

            with lock:
                if len(store) >= maxsize:
                    oldest_key = min(store, key=lambda k: store[k][0])
                    del store[oldest_key]
                store[key] = (now, result)

            return result

        wrapper.cache_clear = lambda: store.clear()
        return wrapper

    return decorator
