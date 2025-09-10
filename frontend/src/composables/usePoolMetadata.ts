import { ref } from 'vue'
import type { PoolMetadata } from '@/types/pool'

export function usePoolMetadata(poolId: string) {
  const poolMetadata = ref<PoolMetadata | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(true)

  const baseUrl = import.meta.env.VITE_BACKEND_URL
  const poolMetadataUrl = `${baseUrl}/api/pool/${poolId}/metadata`

  const fetchPoolMetadata = async () => {
    loading.value = true
    error.value = null

    try {
      const response = await fetch(poolMetadataUrl)
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
