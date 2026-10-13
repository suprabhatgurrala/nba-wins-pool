"""Shared helpers for the refit scripts: paths, seasons, ESPN access, and source rewriting."""

import importlib.util
import re
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import requests

REFIT_DIR = Path(__file__).resolve().parent
DATA_DIR = REFIT_DIR / "data"
BACKEND_DIR = REFIT_DIR.parent
REPO_DIR = BACKEND_DIR.parent
SRC_DIR = BACKEND_DIR / "src" / "nba_wins_pool"

ESPN_FETCHER_PATH = REPO_DIR / ".claude" / "skills" / "espn-nba-odds" / "scripts" / "fetch_espn_odds.py"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (nba-wins-pool refit)", "Accept-Encoding": "gzip"}


def season_str(end_year: int) -> str:
    """2026 -> '2025-2026' (the format sportsoddshistory uses)."""
    return f"{end_year - 1}-{end_year}"


def last_completed_season(today: date | None = None) -> int:
    """End year of the most recent season whose Finals are over (they end by late June)."""
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def parse_season_range(spec: str) -> list[int]:
    """'2022-2026' -> [2022, ..., 2026]; '2026' -> [2026]. Years are season end years."""
    lo, _, hi = spec.partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def load_espn_fetcher() -> ModuleType:
    """Import the espn-nba-odds skill's fetcher so both share one ESPN client."""
    spec = importlib.util.spec_from_file_location("fetch_espn_odds", ESPN_FETCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fetch_postseason_wins(end_year: int) -> dict[str, dict[str, int]]:
    """Wins in completed playoff and play-in games, keyed by ESPN team name ("Hawks", "Trail Blazers").

    Returns ``{name: {"playoff_wins": n, "play_in_wins": m}}`` for every team that played.
    Pages the scoreboard by month (the only form ESPN accepts) from April through
    October, which also covers the 2020 bubble playoffs.
    """
    columns = {3: "playoff_wins", 5: "play_in_wins"}
    wins: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    for month in range(4, 11):
        r = requests.get(
            ESPN_SCOREBOARD_URL,
            params={"dates": f"{end_year}{month:02d}", "limit": 1000},
            headers=HTTP_HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        for event in r.json().get("events", []):
            season = event.get("season", {})
            if season.get("year") != end_year or season.get("type") not in columns or event["id"] in seen:
                continue
            comp = event["competitions"][0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            seen.add(event["id"])
            for team in comp["competitors"]:
                counts = wins.setdefault(team["team"]["name"], dict.fromkeys(columns.values(), 0))
                counts[columns[season["type"]]] += int(bool(team.get("winner")))
    return wins


def write_constants(path: Path, values: dict[str, str]) -> None:
    """Rewrite ``NAME = <number>`` assignments in a source file in place.

    Each name must appear exactly once at the start of a line; anything else is an
    error rather than a silent no-op, so a renamed constant can't go stale unnoticed.
    """
    text = path.read_text()
    for name, value in values.items():
        pattern = re.compile(rf"^({re.escape(name)}\s*=\s*)[-+0-9.eE_]+$", re.MULTILINE)
        text, count = pattern.subn(rf"\g<1>{value}", text)
        if count != 1:
            sys.exit(f"Expected exactly one '{name} = <number>' line in {path}, found {count}")
    path.write_text(text)
    print(f"Updated {path.relative_to(REPO_DIR)}: " + ", ".join(f"{k}={v}" for k, v in values.items()))
