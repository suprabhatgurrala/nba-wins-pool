import { ref } from 'vue'
import type { PoolOverview } from '@/types/pool'

export function usePoolSeasonOverview() {
  const overview = ref<PoolOverview | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(true)

  const fetchPoolSeasonOverview = async ({ poolId, season }: { poolId: string; season: string }) => {
    loading.value = true
    error.value = null
    try {
      const url = `/api/pools/${poolId}/season/${encodeURIComponent(season)}/overview`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      overview.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching pool season overview:', e)
      error.value = e?.message || 'Failed to fetch pool season overview'
    } finally {
      loading.value = false
    }
  }

  return { overview, error, loading, fetchPoolSeasonOverview }
}
