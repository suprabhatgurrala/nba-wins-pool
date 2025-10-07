import { ref } from 'vue'
import type { Pool } from '@/types/pool'

export function usePoolBySlug(slug: string) {
  const pool = ref<Pool | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(true)

  const url = `/api/pools/slug/${slug}`

  const fetchPool = async () => {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      pool.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching pool by slug:', e)
      error.value = e?.message || 'Failed to fetch pool'
    } finally {
      loading.value = false
    }
  }

  return { pool, error, loading, fetchPool }
}
