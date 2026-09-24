from collections import Counter, defaultdict
from typing import List, Optional
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel

from nba_wins_pool.repositories.pool_season_repository import (
    PoolSeasonRepository,
    get_pool_season_repository,
)
from nba_wins_pool.repositories.pool_team_season_result_repository import (
    PoolTeamSeasonResultRepository,
    get_pool_team_season_result_repository,
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
    average_projected_wins: Optional[float]
    """Average preseason-projected wins per season, over seasons with a known projection."""


class PoolHistory(BaseModel):
    seasons: List[PoolHistorySeason]
    participants: List[PoolHistoryParticipant]
    wins_normalized: bool
    """Whether average_wins was rescaled because some season had a different number of teams per roster."""
    baseline_team_count: Optional[int]
    """Teams-per-roster that average_wins was normalized to (the most recent completed season's)."""


class ParticipantSeasonTeam(BaseModel):
    name: str
    abbreviation: str
    logo_url: str
    wins: int
    losses: int
    auction_price: Optional[float]
    projected_wins: Optional[float]


class ParticipantHistorySeason(BaseModel):
    season: SeasonStr
    wins: int
    losses: int
    rank: Optional[int]
    teams: List[ParticipantSeasonTeam]


class ParticipantHistory(BaseModel):
    name: str
    seasons: List[ParticipantHistorySeason]
    """Most-recent season first, matching the pool's season ordering."""


class PoolHistoryService:
    def __init__(
        self,
        pool_season_repository: PoolSeasonRepository,
        leaderboard_service: LeaderboardService,
        pool_team_season_result_repository: PoolTeamSeasonResultRepository,
    ):
        self.pool_season_repository = pool_season_repository
        self.leaderboard_service = leaderboard_service
        self.pool_team_season_result_repository = pool_team_season_result_repository

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

        average_projected_wins = await self._compute_average_projected_wins(pool_id, baseline_team_count)

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
                average_projected_wins=average_projected_wins.get(name),
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

    async def get_participant_history(self, pool_id: UUID, name: str) -> ParticipantHistory:
        """Per-season record and drafted teams for a single participant, identified by roster name."""
        pool_seasons = await self.pool_season_repository.get_all_by_pool(pool_id)

        seasons: List[ParticipantHistorySeason] = []
        for pool_season in pool_seasons:
            leaderboard = await self.leaderboard_service.get_leaderboard(pool_id, pool_season.season)
            roster = next((r for r in leaderboard["roster"] if r["name"] == name), None)
            if roster is None:
                continue

            teams = [
                ParticipantSeasonTeam(
                    name=team["team"],
                    abbreviation=team["abbreviation"],
                    logo_url=team["logo_url"],
                    wins=team["wins"],
                    losses=team["losses"],
                    auction_price=team.get("auction_price"),
                    projected_wins=team.get("projected_wins", team.get("expected_wins")),
                )
                for team in leaderboard["team"]
                if team["name"] == name
            ]
            teams.sort(key=lambda t: (-t.wins, t.name))

            seasons.append(
                ParticipantHistorySeason(
                    season=pool_season.season,
                    wins=roster["wins"],
                    losses=roster["losses"],
                    rank=roster.get("rank"),
                    teams=teams,
                )
            )

        return ParticipantHistory(name=name, seasons=seasons)

    async def _compute_average_projected_wins(
        self, pool_id: UUID, baseline_team_count: Optional[int]
    ) -> dict[str, float]:
        """Average preseason-projected wins per season, keyed by roster name.

        Sourced from the materialized per-team results rather than the leaderboard, since those
        carry the preseason projection frozen at draft time. Only covers seasons that have been
        materialized (i.e. have finished and been read at least once) and that have a known
        projection — the current season isn't materialized and so isn't included. Normalized to
        `baseline_team_count` the same way average_wins is, so a roster that drafted more or
        fewer teams in a given season doesn't skew the comparison.
        """
        pool_team_season_rows = await self.pool_team_season_result_repository.get_all_by_pool(pool_id)
        if not pool_team_season_rows:
            return {}

        season_totals: dict[tuple[str, UUID], float] = defaultdict(float)
        season_team_counts: dict[tuple[str, UUID], int] = defaultdict(int)
        for row in pool_team_season_rows:
            if row.projected_wins is None:
                continue
            key = (row.roster_name, row.pool_season_id)
            season_totals[key] += row.projected_wins
            season_team_counts[key] += 1

        per_roster_normalized: dict[str, list[float]] = defaultdict(list)
        for (roster_name, pool_season_id), total in season_totals.items():
            team_count = season_team_counts[(roster_name, pool_season_id)]
            per_roster_normalized[roster_name].append(self._normalize_wins(total, team_count, baseline_team_count))

        return {name: round(sum(values) / len(values), 1) for name, values in per_roster_normalized.items()}

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
    pool_team_season_result_repository: PoolTeamSeasonResultRepository = Depends(
        get_pool_team_season_result_repository
    ),
) -> PoolHistoryService:
    return PoolHistoryService(
        pool_season_repository=pool_season_repo,
        leaderboard_service=leaderboard_service,
        pool_team_season_result_repository=pool_team_season_result_repository,
    )
