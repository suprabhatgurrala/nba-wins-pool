import pytest
from fastapi.testclient import TestClient

from nba_wins_pool.main_backend import app
from nba_wins_pool.repositories.pool_repository import get_pool_repository
from nba_wins_pool.routes.social import _is_crawler

BROWSER = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"


class RequestStub:
    def __init__(self, user_agent):
        self.headers = {"user-agent": user_agent}


@pytest.mark.parametrize(
    "user_agent",
    [
        "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
        "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
        "facebookexternalhit/1.1;line-poker/1.0",
        "Twitterbot/1.0",
        "WhatsApp/2.23.20.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_1) AppleWebKit/601.2.4 (KHTML, like Gecko) Version/9.0.1 "
        "Safari/601.2.4 facebookexternalhit/1.1 Facebot Twitterbot/1.0",
    ],
)
def test_link_preview_crawlers_are_detected(user_agent):
    assert _is_crawler(RequestStub(user_agent))


def test_browsers_are_not_crawlers():
    assert not _is_crawler(RequestStub(BROWSER))
    assert not _is_crawler(RequestStub(""))


class UnreachablePoolRepository:
    async def get_by_slug(self, slug):
        raise AssertionError("a browser page load should not read the pool")


def test_browser_page_load_skips_the_meta_tag_lookup():
    app.dependency_overrides[get_pool_repository] = UnreachablePoolRepository
    try:
        response = TestClient(app).get("/pools/sg/season/2025-26", headers={"user-agent": BROWSER})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
