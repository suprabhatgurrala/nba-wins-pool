from collections import Counter, defaultdict
from typing import List, Optional
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel

from nba_wins_pool.models.auction import AuctionStatus
from nba_wins_pool.repositories.auction_repository import AuctionRepository, get_auction_repository
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
from nba_wins_pool.services.nba_data_service import NbaDataService, get_nba_data_service
from nba_wins_pool.types.season_str import SeasonStr


class PoolHistoryStanding(BaseModel):
    name: str
    wins: int
    losses: int


class PoolHistorySeason(BaseModel):
    season: SeasonStr
    champions: List[PoolHistoryStanding]
    """Every roster ranked first; more than one when first place is tied."""
    runner_up: Optional[PoolHistoryStanding]
    """The second-placed roster, or None when first place is tied."""
    auction_status: Optional[AuctionStatus] = None
    """Status of the season's auction, or None if no auction has been created for it."""
    in_progress: bool
    """Whether the season is still being played, so its champion and runner-up are only the current leaders."""


class PoolHistoryParticipant(BaseModel):
    name: str
    seasons_played: int
    """Seasons drafted, including one still in progress."""
    championships: int
    average_wins: Optional[float]
    """Average wins over finished seasons, or None before the participant has finished one."""
    average_finish: Optional[float]
    """Average rank over finished seasons, or None before the participant has finished one."""
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
    rank_tied: bool
    """Whether another roster shares this rank."""
    in_progress: bool
    """Whether the season is still being played, so rank is only the current standing."""
    teams: List[ParticipantSeasonTeam]


class ParticipantHistory(BaseModel):
    name: str
    seasons: List[ParticipantHistorySeason]
    """Most-recent season first, matching the pool's season ordering."""
    blurb: Optional[str]
    """One-line career summary, e.g. "4 seasons · 2-time champion"; None when there are no seasons."""


class PoolHistoryService:
    def __init__(
        self,
        pool_season_repository: PoolSeasonRepository,
        leaderboard_service: LeaderboardService,
        pool_team_season_result_repository: PoolTeamSeasonResultRepository,
        nba_data_service: NbaDataService,
        auction_repository: AuctionRepository,
    ):
        self.auction_repository = auction_repository
        self.pool_season_repository = pool_season_repository
        self.leaderboard_service = leaderboard_service
        self.pool_team_season_result_repository = pool_team_season_result_repository
        self.nba_data_service = nba_data_service

    async def get_pool_history(self, pool_id: UUID) -> PoolHistory:
        """Build the pool's season-by-season champions and per-participant career stats."""
        pool_seasons = await self.pool_season_repository.get_all_by_pool(pool_id)
        auctions_by_season = {
            auction.season: auction for auction in await self.auction_repository.get_all(pool_id, None, None)
        }

        history_seasons: List[PoolHistorySeason] = []
        # name -> list of (wins, rank, teams drafted that season) across finished seasons
        participant_records: dict[str, list[tuple[int, int, Optional[int]]]] = {}
        seasons_played: Counter[str] = Counter()
        # (pool_season_id, team count per roster, leaderboard team rows) for projection averages
        season_team_rows: list[tuple[UUID, dict[str, int], list[dict]]] = []
        # A pool's roster count (and so teams-per-roster) can change between seasons, which makes
        # raw win totals across seasons uncomparable. Normalize every season's wins to what they'd
        # be at the most recent completed season's teams-per-roster, before averaging.
        baseline_team_count: Optional[int] = None

        for pool_season in pool_seasons:
            leaderboard = await self.leaderboard_service.get_leaderboard(pool_id, pool_season.season, pool_season)
            rosters = [
                roster
                for roster in leaderboard["roster"]
                if roster["name"] != UNDRAFTED_ROSTER_NAME and roster.get("rank") is not None
            ]
            rosters.sort(key=lambda roster: roster["rank"])

            champions = [self._to_standing(roster) for roster in rosters if roster["rank"] == 1]
            runner_up = self._to_standing(rosters[1]) if len(champions) == 1 and len(rosters) > 1 else None
            auction = auctions_by_season.get(pool_season.season)
            finished = await self.nba_data_service.is_season_finished(pool_season.season)
            history_seasons.append(
                PoolHistorySeason(
                    season=pool_season.season,
                    champions=champions,
                    runner_up=runner_up,
                    auction_status=auction.status if auction else None,
                    in_progress=not finished,
                )
            )

            if not rosters:
                continue

            team_counts = self._count_teams_per_roster(leaderboard["team"])
            season_team_rows.append((pool_season.id, team_counts, leaderboard["team"]))
            seasons_played.update(roster["name"] for roster in rosters)
            if not finished:
                continue

            # pool_seasons is sorted most-recent-first, so the first season we see with a
            # completed draft is "the most recent completed season" for baseline purposes.
            if baseline_team_count is None:
                counts = [team_counts[roster["name"]] for roster in rosters if roster["name"] in team_counts]
                if counts:
                    baseline_team_count = Counter(counts).most_common(1)[0][0]

            for roster in rosters:
                team_count = team_counts.get(roster["name"])
                participant_records.setdefault(roster["name"], []).append((roster["wins"], roster["rank"], team_count))

        average_projected_wins = await self._compute_average_projected_wins(
            pool_id, baseline_team_count, season_team_rows
        )

        participants = [
            self._to_participant(
                name, played, participant_records.get(name, []), baseline_team_count, average_projected_wins.get(name)
            )
            for name, played in seasons_played.items()
        ]
        participants.sort(
            key=lambda participant: (
                participant.average_finish is None,
                -participant.championships,
                participant.average_finish or 0,
                participant.name if participant.average_finish is None else "",
            )
        )

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
            leaderboard = await self.leaderboard_service.get_leaderboard(pool_id, pool_season.season, pool_season)
            roster = next((r for r in leaderboard["roster"] if r["name"] == name), None)
            if roster is None:
                continue
            finished = await self.nba_data_service.is_season_finished(pool_season.season)
            rank = roster.get("rank")
            rank_tied = rank is not None and (
                sum(1 for r in leaderboard["roster"] if r["name"] != UNDRAFTED_ROSTER_NAME and r.get("rank") == rank)
                > 1
            )

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
                    rank=rank,
                    rank_tied=rank_tied,
                    in_progress=not finished,
                    teams=teams,
                )
            )

        return ParticipantHistory(name=name, seasons=seasons, blurb=self._participant_blurb(seasons))

    async def _compute_average_projected_wins(
        self,
        pool_id: UUID,
        baseline_team_count: Optional[int],
        season_team_rows: list[tuple[UUID, dict[str, int], list[dict]]],
    ) -> dict[str, float]:
        """Average preseason-projected wins per season, keyed by roster name.

        Materialized seasons use the projection frozen into their per-team results; the rest (the
        current season) use the leaderboard's preseason projection, when every team on the roster
        has one. Normalized to `baseline_team_count` the same way average_wins is.
        """
        pool_team_season_rows = await self.pool_team_season_result_repository.get_all_by_pool(pool_id)

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

        materialized_season_ids = {row.pool_season_id for row in pool_team_season_rows}
        for pool_season_id, team_counts, team_rows in season_team_rows:
            if pool_season_id in materialized_season_ids:
                continue
            for roster_name, total in self._sum_preseason_wins(team_rows).items():
                per_roster_normalized[roster_name].append(
                    self._normalize_wins(total, team_counts.get(roster_name), baseline_team_count)
                )

        return {name: round(sum(values) / len(values), 1) for name, values in per_roster_normalized.items()}

    def _to_participant(
        self,
        name: str,
        seasons_played: int,
        records: list[tuple[int, int, Optional[int]]],
        baseline_team_count: Optional[int],
        average_projected_wins: Optional[float],
    ) -> PoolHistoryParticipant:
        """Career stats from a participant's finished-season records."""
        average_wins = average_finish = None
        if records:
            average_wins = round(
                sum(self._normalize_wins(wins, team_count, baseline_team_count) for wins, _, team_count in records)
                / len(records),
                1,
            )
            average_finish = round(sum(rank for _, rank, _ in records) / len(records), 2)
        return PoolHistoryParticipant(
            name=name,
            seasons_played=seasons_played,
            championships=sum(1 for _, rank, _ in records if rank == 1),
            average_wins=average_wins,
            average_finish=average_finish,
            average_projected_wins=average_projected_wins,
        )

    @staticmethod
    def _sum_preseason_wins(team_rows: list[dict]) -> dict[str, float]:
        """Preseason-projected wins per roster, for rosters where every team has a projection."""
        totals: dict[str, float] = defaultdict(float)
        missing: set[str] = set()
        for team in team_rows:
            name = team["name"]
            if name == UNDRAFTED_ROSTER_NAME:
                continue
            projected = team.get("preseason_projected_wins")
            if projected is None:
                missing.add(name)
            else:
                totals[name] += projected
        return {name: total for name, total in totals.items() if name not in missing}

    @staticmethod
    def _participant_blurb(seasons: List[ParticipantHistorySeason]) -> Optional[str]:
        """Season count (including one in progress), then titles or best finish from finished seasons."""
        if not seasons:
            return None
        seasons_text = f"{len(seasons)} season{'' if len(seasons) == 1 else 's'}"
        finished = [s for s in seasons if not s.in_progress and s.rank is not None]
        champion_seasons = [s for s in finished if s.rank == 1]

        if len(champion_seasons) > 1:
            return f"{seasons_text} · {len(champion_seasons)}-time champion"
        if len(champion_seasons) == 1:
            title = "Co-champion" if champion_seasons[0].rank_tied else "Champion"
            return f"{seasons_text} · {title} in {champion_seasons[0].season}"
        if not finished:
            return seasons_text
        best = min(finished, key=lambda s: (s.rank, s.rank_tied))
        return f"{seasons_text} · Best finish: {tied_ordinal(best.rank, best.rank_tied)}"

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


def ordinal(rank: int) -> str:
    """English ordinal for a rank, e.g. 1st, 12th, 23rd."""
    if 11 <= (rank % 100) <= 13:
        return f"{rank}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def tied_ordinal(rank: int, tied: bool) -> str:
    """Ordinal with a "T-" prefix for a shared rank, e.g. T-3rd."""
    return f"T-{ordinal(rank)}" if tied else ordinal(rank)


def get_pool_history_service(
    pool_season_repo: PoolSeasonRepository = Depends(get_pool_season_repository),
    leaderboard_service: LeaderboardService = Depends(get_leaderboard_service),
    pool_team_season_result_repository: PoolTeamSeasonResultRepository = Depends(
        get_pool_team_season_result_repository
    ),
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
    auction_repository: AuctionRepository = Depends(get_auction_repository),
) -> PoolHistoryService:
    return PoolHistoryService(
        pool_season_repository=pool_season_repo,
        leaderboard_service=leaderboard_service,
        pool_team_season_result_repository=pool_team_season_result_repository,
        nba_data_service=nba_data_service,
        auction_repository=auction_repository,
    )
