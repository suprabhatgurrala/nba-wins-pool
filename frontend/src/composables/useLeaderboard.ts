import { ref } from 'vue'
import type { LeaderboardResponse, RosterRow, TeamRow } from '@/types/leaderboard'
import { parseUTCTimestamp } from '@/utils/time'

export function useLeaderboard() {
  const roster = ref<RosterRow[] | null>(null)
  const team = ref<TeamRow[] | null>(null)
  const lastUpdated = ref<Date | null>(null)
  const simLastUpdated = ref<Date | null>(null)

  function setLeaderboard(data: LeaderboardResponse | null) {
    roster.value = data?.roster ?? null
    team.value = data?.team ?? null
    lastUpdated.value = parseUTCTimestamp(data?.nba_checked_at)
    simLastUpdated.value = parseUTCTimestamp(data?.sim_last_updated)
  }

  return { roster, team, lastUpdated, simLastUpdated, setLeaderboard }
}
