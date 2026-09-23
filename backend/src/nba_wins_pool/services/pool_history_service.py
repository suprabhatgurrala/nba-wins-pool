from collections import Counter
from typing import List, Optional
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel

from nba_wins_pool.repositories.pool_season_repository import (
    PoolSeasonRepository,
    get_pool_season_repository,
)
from nba_wins_pool.services.leaderboard_service import (
    UNDRAFTED_ROSTER_NAME,
    LeaderboardService,
    get_leaderboard_service,
)
from nba_wins_pool.types.season_str import SeasonStr


class PoolHistoryStanding(BaseModel):
    name: str
    wins: int
    losses: int


class PoolHistorySeason(BaseModel):
    season: SeasonStr
    champion: Optional[PoolHistoryStanding]
    runner_up: Optional[PoolHistoryStanding]


class PoolHistoryParticipant(BaseModel):
    name: str
    seasons_played: int
    championships: int
    average_wins: float
    average_finish: float


class PoolHistory(BaseModel):
    seasons: List[PoolHistorySeason]
    participants: List[PoolHistoryParticipant]
    wins_normalized: bool
    """Whether average_wins was rescaled because some season had a different number of teams per roster."""
    baseline_team_count: Optional[int]
    """Teams-per-roster that average_wins was normalized to (the most recent completed season's)."""


class PoolHistoryService:
    def __init__(self, pool_season_repository: PoolSeasonRepository, leaderboard_service: LeaderboardService):
        self.pool_season_repository = pool_season_repository
        self.leaderboard_service = leaderboard_service

    async def get_pool_history(self, pool_id: UUID) -> PoolHistory:
        """Derive per-season winners/runners-up and per-participant career stats.

        There is no persisted "final standings" record for a season, so this replays the same
        leaderboard computation used for the live standings against every past season.
        """
        pool_seasons = await self.pool_season_repository.get_all_by_pool(pool_id)

        history_seasons: List[PoolHistorySeason] = []
        # name -> list of (wins, rank, teams drafted that season) across all seasons played
        participant_records: dict[str, list[tuple[int, int, Optional[int]]]] = {}
        # A pool's roster count (and so teams-per-roster) can change between seasons, which makes
        # raw win totals across seasons uncomparable. Normalize every season's wins to what they'd
        # be at the most recent completed season's teams-per-roster, before averaging.
        baseline_team_count: Optional[int] = None

        for pool_season in pool_seasons:
            leaderboard = await self.leaderboard_service.get_leaderboard(pool_id, pool_season.season)
            rosters = [
                roster
                for roster in leaderboard["roster"]
                if roster["name"] != UNDRAFTED_ROSTER_NAME and roster.get("rank") is not None
            ]
            rosters.sort(key=lambda roster: roster["rank"])

            champion = self._to_standing(rosters[0]) if rosters else None
            runner_up = self._to_standing(rosters[1]) if len(rosters) > 1 else None
            history_seasons.append(PoolHistorySeason(season=pool_season.season, champion=champion, runner_up=runner_up))

            if not rosters:
                continue

            team_counts = self._count_teams_per_roster(leaderboard["team"])

            # pool_seasons is sorted most-recent-first, so the first season we see with a
            # completed draft is "the most recent completed season" for baseline purposes.
            if baseline_team_count is None:
                counts = [team_counts[roster["name"]] for roster in rosters if roster["name"] in team_counts]
                if counts:
                    baseline_team_count = Counter(counts).most_common(1)[0][0]

            for roster in rosters:
                team_count = team_counts.get(roster["name"])
                participant_records.setdefault(roster["name"], []).append((roster["wins"], roster["rank"], team_count))

        participants = [
            PoolHistoryParticipant(
                name=name,
                seasons_played=len(records),
                championships=sum(1 for _, rank, _ in records if rank == 1),
                average_wins=round(
                    sum(self._normalize_wins(wins, team_count, baseline_team_count) for wins, _, team_count in records)
                    / len(records),
                    1,
                ),
                average_finish=round(sum(rank for _, rank, _ in records) / len(records), 2),
            )
            for name, records in participant_records.items()
        ]
        participants.sort(key=lambda participant: (-participant.championships, participant.average_finish))

        wins_normalized = any(
            team_count is not None and team_count != baseline_team_count
            for records in participant_records.values()
            for _, _, team_count in records
        )

        return PoolHistory(
            seasons=history_seasons,
            participants=participants,
            wins_normalized=wins_normalized,
            baseline_team_count=baseline_team_count if wins_normalized else None,
        )

    @staticmethod
    def _normalize_wins(wins: int, team_count: Optional[int], baseline_team_count: Optional[int]) -> float:
        """Rescale wins to what they'd be at the baseline teams-per-roster count."""
        if not team_count or not baseline_team_count:
            return wins
        return wins / team_count * baseline_team_count

    @staticmethod
    def _count_teams_per_roster(team_rows: list[dict]) -> dict[str, int]:
        """Number of NBA teams each roster drafted, keyed by roster name."""
        counts: dict[str, int] = {}
        for team in team_rows:
            name = team["name"]
            if name == UNDRAFTED_ROSTER_NAME:
                continue
            counts[name] = counts.get(name, 0) + 1
        return counts

    @staticmethod
    def _to_standing(roster: dict) -> PoolHistoryStanding:
        return PoolHistoryStanding(name=roster["name"], wins=roster["wins"], losses=roster["losses"])


def get_pool_history_service(
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
    leaderboard_service: LeaderboardService = Depends(get_leaderboard_service),
) -> PoolHistoryService:
    return PoolHistoryService(pool_season_repository=pool_season_repo, leaderboard_service=leaderboard_service)
