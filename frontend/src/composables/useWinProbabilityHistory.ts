import { ref } from 'vue'
import type { WinProbabilityHistory } from '@/types/winProbabilityHistory'

export function useWinProbabilityHistory() {
  const history = ref<WinProbabilityHistory | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(false)
  let loadedFor: string | null = null

  /** Fetch a pool season's win probability history; repeat calls for the loaded season do nothing. */
  async function fetchHistory(slug: string, season: string) {
    const key = `${slug}/${season}`
    if (loadedFor === key) return
    loadedFor = key
    history.value = null
    loading.value = true
    error.value = null
    try {
      const url = `/api/pools/slug/${encodeURIComponent(slug)}/seasons/${encodeURIComponent(season)}/win-probability-history`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: WinProbabilityHistory = await res.json()
      if (loadedFor === key) history.value = data
    } catch (e: any) {
      console.error('Error fetching win probability history:', e)
      if (loadedFor !== key) return
      error.value = e?.message || 'Failed to fetch win probability history'
      loadedFor = null
    } finally {
      if (loadedFor === key || loadedFor === null) loading.value = false
    }
  }

  return { history, error, loading, fetchHistory }
}
