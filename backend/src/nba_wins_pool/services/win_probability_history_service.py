from datetime import timezone
from typing import Any
from uuid import UUID

from fastapi import Depends

from nba_wins_pool.repositories.roster_repository import RosterRepository, get_roster_repository
from nba_wins_pool.repositories.simulation_results_repository import (
    SimulationResultsRepository,
    get_simulation_results_repository,
)
from nba_wins_pool.services.nba_data_service import NbaDataService, get_nba_data_service
from nba_wins_pool.types.season_str import SeasonStr
from nba_wins_pool.utils.result_cache import result_cache


class WinProbabilityHistoryService:
    def __init__(
        self,
        simulation_results_repository: SimulationResultsRepository,
        roster_repository: RosterRepository,
        nba_data_service: NbaDataService,
    ) -> None:
        self.simulation_results_repository = simulation_results_repository
        self.roster_repository = roster_repository
        self.nba_data_service = nba_data_service

    async def get_history(self, pool_id: UUID, season: SeasonStr) -> dict[str, Any]:
        """Each roster's pool win probability (percent) at every stored simulation run of the season."""
        return await result_cache.get(
            ("win_probability_history", pool_id, season), lambda: self._compute(pool_id, season), current=False
        )

    async def _compute(self, pool_id: UUID, season: SeasonStr) -> dict[str, Any]:
        rows = await self.simulation_results_repository.get_roster_history(season, pool_id)
        names = {r.id: r.name for r in await self.roster_repository.get_all(pool_id=pool_id, season=season)}

        timestamps: list[int] = []
        index: dict[Any, int] = {}
        for simulated_at, roster_id, _ in rows:
            if roster_id in names and simulated_at not in index:
                index[simulated_at] = len(timestamps)
                timestamps.append(int(simulated_at.replace(tzinfo=timezone.utc).timestamp() * 1000))

        series: dict[str, list[float | None]] = {}
        for simulated_at, roster_id, win_pct in rows:
            if roster_id not in names:
                continue
            values = series.setdefault(str(roster_id), [None] * len(timestamps))
            values[index[simulated_at]] = round(win_pct * 100, 1)

        rosters = sorted(({"id": rid, "name": names[UUID(rid)]} for rid in series), key=lambda r: r["name"])
        milestones = await self.nba_data_service.get_season_milestones(season) if timestamps else []
        return {"rosters": rosters, "timestamps": timestamps, "series": series, "milestones": milestones}


def get_win_probability_history_service(
    simulation_results_repository: SimulationResultsRepository = Depends(get_simulation_results_repository),
    roster_repository: RosterRepository = Depends(get_roster_repository),
    nba_data_service: NbaDataService = Depends(get_nba_data_service),
) -> WinProbabilityHistoryService:
    return WinProbabilityHistoryService(simulation_results_repository, roster_repository, nba_data_service)
