import { ref } from 'vue'
import type { Pool } from '@/types/pool'

export function usePool() {
  const pool = ref<Pool | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(false)

  const fetchPoolBySlug = async (slug: string) => {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`/api/pools/slug/${encodeURIComponent(slug)}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      pool.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching pool by slug:', e)
      error.value = e?.message || 'Failed to fetch pool'
      pool.value = null
    } finally {
      loading.value = false
    }
  }

  const fetchPoolById = async (id: string) => {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(`/api/pools/${id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      pool.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching pool by id:', e)
      error.value = e?.message || 'Failed to fetch pool'
      pool.value = null
    } finally {
      loading.value = false
    }
  }

  return { pool, error, loading, fetchPoolBySlug, fetchPoolById }
}
