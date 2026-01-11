import { ref } from 'vue'
import type { LeaderboardMetadata, LeaderboardResponse, RosterRow, TeamRow } from '@/types/leaderboard'

export function useLeaderboard() {
  const roster = ref<RosterRow[] | null>(null)
  const team = ref<TeamRow[] | null>(null)
  const metadata = ref<LeaderboardMetadata | null>(null)
  const error = ref<string | null>(null)
  const loading = ref<boolean>(false)

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
      metadata.value = data.metadata
    } catch (e: any) {
      console.error('Error fetching leaderboard:', e)
      error.value = e?.message || 'Failed to fetch leaderboard'
    } finally {
      loading.value = false
    }
  }

  return { roster, team, metadata, error, loading, fetchLeaderboard }
}
