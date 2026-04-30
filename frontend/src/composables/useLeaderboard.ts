import { ref } from 'vue'
import type { LeaderboardResponse, RosterRow, TeamRow } from '@/types/leaderboard'
import { parseUTCTimestamp } from '@/utils/time'

export function useLeaderboard() {
  const roster = ref<RosterRow[] | null>(null)
  const team = ref<TeamRow[] | null>(null)
  const error = ref<string | null>(null)
  const loading = ref<boolean>(false)
  const simulating = ref<boolean>(false)
  const lastUpdated = ref<Date | null>(null)
  const simLastUpdated = ref<Date | null>(null)

  async function loadFrom(
    url: string,
    init: RequestInit,
    busy: typeof loading,
    errorContext: string,
  ) {
    busy.value = true
    error.value = null
    try {
      const res = await fetch(url, init)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: LeaderboardResponse = await res.json()
      roster.value = data.roster
      team.value = data.team
      lastUpdated.value = new Date()
      simLastUpdated.value = parseUTCTimestamp(data.sim_last_updated)
    } catch (e: any) {
      console.error(`${errorContext}:`, e)
      error.value = e?.message || errorContext
    } finally {
      busy.value = false
    }
  }

  function fetchLeaderboard(poolId: string, season: string) {
    const url = `/api/pools/${encodeURIComponent(poolId)}/season/${encodeURIComponent(season)}/leaderboard`
    return loadFrom(url, {}, loading, 'Failed to fetch leaderboard')
  }

  function runSimulation(poolId: string, season: string) {
    const url = `/api/pools/${encodeURIComponent(poolId)}/season/${encodeURIComponent(season)}/simulation`
    return loadFrom(url, { method: 'POST' }, simulating, 'Failed to run simulation')
  }

  return { roster, team, error, loading, simulating, lastUpdated, simLastUpdated, fetchLeaderboard, runSimulation }
}
