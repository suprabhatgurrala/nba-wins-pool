import { ref } from 'vue'
import type { ParticipantHistory } from '@/types/poolHistory'

export function useParticipantHistory() {
  const history = ref<ParticipantHistory | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(false)

  async function fetchParticipantHistory(poolId: string, name: string) {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`/api/pools/${encodeURIComponent(poolId)}/participants/${encodeURIComponent(name)}/history`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      history.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching participant history:', e)
      error.value = e?.message || 'Failed to fetch participant history'
      history.value = null
    } finally {
      loading.value = false
    }
  }

  return { history, error, loading, fetchParticipantHistory }
}
