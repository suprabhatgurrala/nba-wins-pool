import { ref } from 'vue'
import type { TodayGame } from '@/types/leaderboard'

export function useTodayGames() {
  const games = ref<TodayGame[] | null>(null)
  const error = ref<string | null>(null)
  const loading = ref<boolean>(false)

  async function fetchTodayGames(poolId: string, season: string) {
    loading.value = true
    error.value = null
    try {
      const url = `/api/pools/${encodeURIComponent(poolId)}/season/${encodeURIComponent(season)}/today-games`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      games.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching today games:', e)
      error.value = e?.message || 'Failed to fetch today\'s games'
    } finally {
      loading.value = false
    }
  }

  return { games, error, loading, fetchTodayGames }
}
