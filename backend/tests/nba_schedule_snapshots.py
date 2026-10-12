"""Load archived NBA schedule snapshots for simulator tests.

Snapshots in ``fixtures/nba-schedule-snapshots`` are ``scheduleLeagueV2_1.json`` captures
from the Wayback Machine, named ``schedule-<season>-<capture date>.json.gz``.
"""

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from nba_wins_pool.services.nba_data_service import NbaDataService
from nba_wins_pool.services.nba_simulator.core.game_probability import game_probabilities
from nba_wins_pool.services.nba_simulator.core.playoff_seeding import load_team_metadata
from nba_wins_pool.services.nba_simulator.core.schedule import with_cup_rounds
from nba_wins_pool.types.nba_game_type import NBAGameType

SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "nba-schedule-snapshots"

# Production labels game types from ESPN season dates; snapshots are offline, so use the
# game ID prefix instead (001 preseason, 002 regular season, 004 playoffs, 005 play-in).
# NBA Cup knockouts (the Championship has its own prefix) are regular-season games.
_GAME_TYPE_BY_PREFIX = {
    "002": NBAGameType.REGULAR_SEASON,
    "004": NBAGameType.PLAYOFFS,
    "005": NBAGameType.PLAY_IN,
}


def load_snapshot(name: str) -> pd.DataFrame:
    """Parse ``schedule-<name>.json.gz`` the way the app parses the live schedule."""
    return load_schedule_file(SNAPSHOT_DIR / f"schedule-{name}.json.gz")


def load_schedule_file(path: Path) -> pd.DataFrame:
    """Parse a raw NBA schedule JSON file (gzipped or plain)."""
    data = path.read_bytes()
    raw = json.loads(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)
    service = NbaDataService(db_session=None, external_data_repository=None)
    df = service._finalize_game_df(pd.DataFrame(service._parse_schedule(raw)))
    knockout = df["game_subtype"] == "in-season-knockout"
    df = df[df["game_id"].str[:3].isin(_GAME_TYPE_BY_PREFIX) | knockout].copy()
    df["game_type"] = df["game_id"].str[:3].map(_GAME_TYPE_BY_PREFIX).fillna(NBAGameType.REGULAR_SEASON)
    return with_cup_rounds(df.reset_index(drop=True))


def sample_ratings() -> dict[str, float]:
    """Deterministic spread of power ratings for all 30 teams."""
    rng = np.random.default_rng(0)
    teams = sorted(load_team_metadata())
    return dict(zip(teams, rng.normal(0, 4, len(teams)).tolist()))


def game_df_from_ratings(schedule: pd.DataFrame, ratings: dict[str, float]) -> pd.DataFrame:
    """Upcoming games with probabilities from ratings + home court + rest (snapshots have no odds)."""
    return game_probabilities(schedule, ratings)
