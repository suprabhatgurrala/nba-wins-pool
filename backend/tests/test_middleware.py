import logging

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from nba_wins_pool.utils import middleware
from nba_wins_pool.utils.middleware import GZipExceptEventStreamMiddleware, RequestMetricsMiddleware

BIG_BODY = "x" * 5000


def _app(queries: int = 0) -> FastAPI:
    app = FastAPI()

    @app.get("/data")
    async def data():
        counter = middleware._request_queries.get()
        if counter is not None:
            counter[0] += queries
        return PlainTextResponse(BIG_BODY)

    app.add_middleware(GZipExceptEventStreamMiddleware)
    app.add_middleware(RequestMetricsMiddleware)
    return app


def test_gzips_large_responses():
    response = TestClient(_app()).get("/data", headers={"accept-encoding": "gzip"})

    assert response.headers["content-encoding"] == "gzip"
    assert response.text == BIG_BODY


def test_does_not_gzip_event_streams():
    response = TestClient(_app()).get("/data", headers={"accept-encoding": "gzip", "accept": "text/event-stream"})

    assert "content-encoding" not in response.headers


def test_logs_requests_with_many_queries(caplog):
    with caplog.at_level(logging.WARNING, logger=middleware.__name__):
        TestClient(_app(queries=middleware.MANY_QUERIES + 1)).get("/data")

    assert "Slow request GET /data" in caplog.text
    assert f"{middleware.MANY_QUERIES + 1} queries" in caplog.text


def test_does_not_log_fast_requests_with_few_queries(caplog):
    with caplog.at_level(logging.WARNING, logger=middleware.__name__):
        TestClient(_app(queries=2)).get("/data")

    assert "Slow request" not in caplog.text
