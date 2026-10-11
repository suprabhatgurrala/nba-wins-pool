import { ref } from 'vue'
import type { PoolHistory } from '@/types/poolHistory'

export function usePoolHistory() {
  const history = ref<PoolHistory | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(false)

  async function fetchPoolHistory(poolId: string) {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`/api/pools/${encodeURIComponent(poolId)}/history`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      history.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching pool history:', e)
      error.value = e?.message || 'Failed to fetch pool history'
      history.value = null
    } finally {
      loading.value = false
    }
  }

  return { history, error, loading, fetchPoolHistory }
}
