import { ref } from 'vue'
import type { TodayGame, TodayGamesResponse } from '@/types/leaderboard'

export function useTodayGames() {
  const games = ref<TodayGame[] | null>(null)
  const gamesDate = ref<string | null>(null)
  const scoreboardDate = ref<string | null>(null)
  const gameDates = ref<string[]>([])
  const error = ref<string | null>(null)
  const loading = ref<boolean>(false)

  function setTodayGames(data: TodayGamesResponse) {
    if (data.game_dates?.length) gameDates.value = data.game_dates
    games.value = data.games
    gamesDate.value = data.date
    scoreboardDate.value = data.scoreboard_date
  }

  async function fetchGamesForDate(slug: string, season: string, date: string) {
    loading.value = true
    error.value = null
    try {
      const url = `/api/pools/slug/${encodeURIComponent(slug)}/seasons/${encodeURIComponent(season)}/games?date=${encodeURIComponent(date)}`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setTodayGames(await res.json())
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

  async function goToPrevDay(slug: string, season: string) {
    if (!gamesDate.value) return
    await fetchGamesForDate(slug, season, offsetDate(gamesDate.value, -1))
  }

  async function goToNextDay(slug: string, season: string) {
    if (!gamesDate.value) return
    await fetchGamesForDate(slug, season, offsetDate(gamesDate.value, 1))
  }

  function isOnScoreboardDate(): boolean {
    return gamesDate.value === scoreboardDate.value
  }

  return {
    games,
    gamesDate,
    scoreboardDate,
    gameDates,
    error,
    loading,
    setTodayGames,
    fetchGamesForDate,
    goToPrevDay,
    goToNextDay,
    isOnScoreboardDate,
  }
}
