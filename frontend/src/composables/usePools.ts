import { ref } from 'vue'
import type { Pool, PoolCreate, PoolUpdate } from '@/types/pool'

export function usePools() {
  const pools = ref<Pool[]>([])
  const error = ref<string | null>(null)
  const loading = ref(true)

  const url = `/api/pools`

  const fetchPools = async (includeSeasons: boolean = false) => {
    loading.value = true
    error.value = null
    try {
      const queryParam = includeSeasons ? '?include_seasons=true' : ''
      const res = await fetch(`${url}${queryParam}`)
      if (!res.ok) throw new Error(`Failed to fetch pools: ${res.statusText}`)
      pools.value = await res.json()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unknown error'
    } finally {
      loading.value = false
    }
  }

  const createPool = async (payload: PoolCreate): Promise<Pool> => {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      // Try to extract error details
      let message = `Failed to create pool (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    const created: Pool = await res.json()
    // Update local state optimistically
    pools.value = [created, ...pools.value]
    return created
  }

  const updatePool = async (poolId: string, payload: PoolUpdate): Promise<Pool> => {
    const res = await fetch(`${url}/${poolId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      let message = `Failed to update pool (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    const updated: Pool = await res.json()
    pools.value = pools.value.map((p) => (p.id === updated.id ? updated : p))
    return updated
  }

  const deletePool = async (poolId: string): Promise<void> => {
    const res = await fetch(`${url}/${poolId}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      let message = `Failed to delete pool (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    // Update local cache
    pools.value = pools.value.filter((p) => p.id !== poolId)
  }

  return { pools, error, loading, fetchPools, createPool, updatePool, deletePool }
}
