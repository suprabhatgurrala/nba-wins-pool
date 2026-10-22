import { ref } from 'vue'
import type { SeasonLive, SeasonPage } from '@/types/pool'

export function useSeasonPage() {
  const page = ref<SeasonPage | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(true)

  async function fetchSeasonPage(slug: string, season: string) {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(
        `/api/pools/slug/${encodeURIComponent(slug)}/seasons/${encodeURIComponent(season)}`,
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      page.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching season:', e)
      error.value = e?.message || 'Failed to fetch season'
    } finally {
      loading.value = false
    }
  }

  return { page, error, loading, fetchSeasonPage }
}

export function useSeasonLive() {
  const error = ref<string | null>(null)
  const loading = ref(false)

  /** Standings, wins race and the day's games; resolves to null when the request fails. */
  async function fetchSeasonLive(slug: string, season: string): Promise<SeasonLive | null> {
    loading.value = true
    error.value = null
    try {
      const url = `/api/pools/slug/${encodeURIComponent(slug)}/seasons/${encodeURIComponent(season)}/live`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return await res.json()
    } catch (e: any) {
      console.error('Error fetching live season data:', e)
      error.value = e?.message || 'Failed to fetch standings'
      return null
    } finally {
      loading.value = false
    }
  }

  return { error, loading, fetchSeasonLive }
}
