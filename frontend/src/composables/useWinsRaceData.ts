import { ref } from 'vue'
import type { WinsRaceData } from '@/types/pool'

export function useWinsRaceData(poolId: string) {
  const winsRaceData = ref<WinsRaceData | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(true)

  const baseUrl = import.meta.env.VITE_BACKEND_URL
  const winsRaceUrl = `${baseUrl}/api/pool/${poolId}/wins_race`

  const fetchWinsRaceData = async () => {
    loading.value = true
    error.value = null

    try {
      const response = await fetch(winsRaceUrl)
      winsRaceData.value = await response.json()
    } catch (err: any) {
      console.error('Error fetching wins race data:', err)
      error.value = `Error fetching wins race data: ${err.message}`
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
