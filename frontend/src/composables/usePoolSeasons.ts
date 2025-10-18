import { ref } from 'vue'

export interface PoolSeason {
  id: string
  pool_id: string
  season: string
  rules: string | null
  created_at: string
}

export interface PoolSeasonCreate {
  pool_id: string
  season: string
  rules?: string | null
}

export interface PoolSeasonUpdate {
  rules?: string | null
}

export function usePoolSeasons() {
  const loading = ref(false)
  const error = ref<string | null>(null)

  const fetchPoolSeasons = async (poolId: string): Promise<PoolSeason[]> => {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`/api/pools/${poolId}/seasons`)
      if (!res.ok) throw new Error(`Failed to fetch pool seasons: ${res.statusText}`)
      return await res.json()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unknown error'
      throw err
    } finally {
      loading.value = false
    }
  }

  const fetchPoolSeason = async (poolId: string, season: string): Promise<PoolSeason> => {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`/api/pools/${poolId}/seasons/${season}`)
      if (!res.ok) throw new Error(`Failed to fetch pool season: ${res.statusText}`)
      return await res.json()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unknown error'
      throw err
    } finally {
      loading.value = false
    }
  }

  const createPoolSeason = async (
    poolId: string,
    payload: PoolSeasonCreate,
  ): Promise<PoolSeason> => {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`/api/pools/${poolId}/seasons`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`Failed to create pool season: ${res.statusText}`)
      return await res.json()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unknown error'
      throw err
    } finally {
      loading.value = false
    }
  }

  const updatePoolSeason = async (
    poolId: string,
    season: string,
    payload: PoolSeasonUpdate,
  ): Promise<PoolSeason> => {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`/api/pools/${poolId}/seasons/${season}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`Failed to update pool season: ${res.statusText}`)
      return await res.json()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unknown error'
      throw err
    } finally {
      loading.value = false
    }
  }

  const deletePoolSeason = async (poolId: string, season: string): Promise<void> => {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`/api/pools/${poolId}/seasons/${season}`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error(`Failed to delete pool season: ${res.statusText}`)
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unknown error'
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    error,
    fetchPoolSeasons,
    fetchPoolSeason,
    createPoolSeason,
    updatePoolSeason,
    deletePoolSeason,
  }
}
