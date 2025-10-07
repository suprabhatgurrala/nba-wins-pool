import { ref } from 'vue'
import type { PoolMetadata } from '@/types/pool'

export function usePoolMetadata() {
  const poolMetadata = ref<PoolMetadata | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(true)

  const fetchPoolMetadata = async (slug: string) => {
    loading.value = true
    error.value = null

    try {
      const response = await fetch(`/api/pool/${slug}/metadata`)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      poolMetadata.value = await response.json()
    } catch (err: any) {
      console.error('Error fetching pool metadata:', err)
      error.value = `Error fetching pool metadata: ${err.message}`
    } finally {
      loading.value = false
    }
  }

  return {
    poolMetadata,
    error,
    loading,
    fetchPoolMetadata,
  }
}
