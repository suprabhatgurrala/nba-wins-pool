import { ref } from 'vue'
import type { TodayGame } from '@/types/leaderboard'

export function useTodayGames() {
  const games = ref<TodayGame[] | null>(null)
  const gamesDate = ref<string | null>(null)
  const scoreboardDate = ref<string | null>(null)
  const gameDates = ref<string[]>([])
  const error = ref<string | null>(null)
  const loading = ref<boolean>(false)

  async function fetchTodayGames(poolId: string, season: string, date?: string) {
    loading.value = true
    error.value = null
    try {
      let url = `/api/pools/${encodeURIComponent(poolId)}/season/${encodeURIComponent(season)}/today-games`
      if (date) url += `?date=${encodeURIComponent(date)}`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.game_dates?.length) gameDates.value = data.game_dates
      // If no explicit date was requested and the returned date has no games in this season,
      // default to the last available game date.
      if (!date && data.game_dates?.length && !data.game_dates.includes(data.date)) {
        const lastDate = data.game_dates[data.game_dates.length - 1]
        const res2 = await fetch(
          `/api/pools/${encodeURIComponent(poolId)}/season/${encodeURIComponent(season)}/today-games?date=${encodeURIComponent(lastDate)}`,
        )
        if (!res2.ok) throw new Error(`HTTP ${res2.status}`)
        const data2 = await res2.json()
        games.value = data2.games
        gamesDate.value = data2.date
        scoreboardDate.value = data2.scoreboard_date
      } else {
        games.value = data.games
        gamesDate.value = data.date
        scoreboardDate.value = data.scoreboard_date
      }
    } catch (e: any) {
      console.error('Error fetching games:', e)
      error.value = e?.message || 'Failed to fetch games'
    } finally {
      loading.value = false
    }
  }

  function offsetDate(dateStr: string, days: number): string {
    const d = new Date(dateStr + 'T12:00:00')
    d.setDate(d.getDate() + days)
    return d.toISOString().slice(0, 10)
  }

  async function goToPrevDay(poolId: string, season: string) {
    if (!gamesDate.value) return
    await fetchTodayGames(poolId, season, offsetDate(gamesDate.value, -1))
  }

  async function goToNextDay(poolId: string, season: string) {
    if (!gamesDate.value) return
    await fetchTodayGames(poolId, season, offsetDate(gamesDate.value, 1))
  }

  function isOnScoreboardDate(): boolean {
    return gamesDate.value === scoreboardDate.value
  }

  return { games, gamesDate, scoreboardDate, gameDates, error, loading, fetchTodayGames, goToPrevDay, goToNextDay, isOnScoreboardDate }
}
