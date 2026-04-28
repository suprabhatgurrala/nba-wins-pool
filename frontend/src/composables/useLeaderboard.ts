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

  async function fetchLeaderboard(poolId: string, season: string) {
    loading.value = true
    error.value = null
    try {
      const url = `/api/pools/${encodeURIComponent(poolId)}/season/${encodeURIComponent(season)}/leaderboard`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: LeaderboardResponse = await res.json()
      roster.value = data.roster
      team.value = data.team
      lastUpdated.value = new Date()
      simLastUpdated.value = parseUTCTimestamp(data.sim_last_updated)
    } catch (e: any) {
      console.error('Error fetching leaderboard:', e)
      error.value = e?.message || 'Failed to fetch leaderboard'
    } finally {
      loading.value = false
    }
  }

  async function runSimulation(poolId: string, season: string) {
    simulating.value = true
    error.value = null
    try {
      const url = `/api/pools/${encodeURIComponent(poolId)}/season/${encodeURIComponent(season)}/simulation`
      const res = await fetch(url, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: LeaderboardResponse = await res.json()
      roster.value = data.roster
      team.value = data.team
      lastUpdated.value = new Date()
      simLastUpdated.value = parseUTCTimestamp(data.sim_last_updated)
    } catch (e: any) {
      console.error('Error running simulation:', e)
      error.value = e?.message || 'Failed to run simulation'
    } finally {
      simulating.value = false
    }
  }

  return { roster, team, error, loading, simulating, lastUpdated, simLastUpdated, fetchLeaderboard, runSimulation }
}
