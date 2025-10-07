import { ref } from 'vue'
import type { WinsRaceData } from '@/types/winsRace'

export function useWinsRaceData() {
  const winsRaceData = ref<WinsRaceData | null>(null)
  const error = ref<string | null>(null)
  const loading = ref<boolean>(false)

  async function fetchWinsRaceData(poolId: string, season: string) {
    loading.value = true
    error.value = null
    try {
      const url = `/api/pools/${encodeURIComponent(poolId)}/season/${encodeURIComponent(season)}/wins-race`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      winsRaceData.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching wins race data:', e)
      error.value = e?.message || 'Failed to fetch wins race data'
      winsRaceData.value = null
    } finally {
      loading.value = false
    }
  }

  return {
    winsRaceData,
    error,
    loading,
    fetchWinsRaceData,
  }
}
