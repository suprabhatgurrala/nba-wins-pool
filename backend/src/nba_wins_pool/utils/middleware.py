import logging
import time
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

SLOW_REQUEST_SECONDS = 0.5
MANY_QUERIES = 30

_request_queries: ContextVar[list[int] | None] = ContextVar("request_queries", default=None)


def count_queries(engine: AsyncEngine) -> None:
    """Count each SQL statement against the request that issued it."""

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(*_args) -> None:
        counter = _request_queries.get()
        if counter is not None:
            counter[0] += 1


def _is_event_stream(scope: Scope) -> bool:
    accept = dict(scope.get("headers") or []).get(b"accept", b"")
    return b"text/event-stream" in accept


class RequestMetricsMiddleware:
    """Log requests that are slow or run many SQL queries."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _is_event_stream(scope):
            await self.app(scope, receive, send)
            return

        counter = [0]
        token = _request_queries.set(counter)
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send)
        finally:
            elapsed = time.perf_counter() - start
            _request_queries.reset(token)
            if elapsed > SLOW_REQUEST_SECONDS or counter[0] > MANY_QUERIES:
                logger.warning(
                    "Slow request %s %s: %.0f ms, %d queries",
                    scope["method"],
                    scope["path"],
                    elapsed * 1000,
                    counter[0],
                )


class GZipExceptEventStreamMiddleware:
    """Gzip responses, except event streams, which must reach the client unbuffered."""

    def __init__(self, app: ASGIApp, minimum_size: int = 1000) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _is_event_stream(scope):
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)
