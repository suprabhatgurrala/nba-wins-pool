import { ref } from 'vue'
import type { Roster, RosterCreate, RosterQuery, RosterUpdate } from '@/types/pool'

export function useRosters() {
  const rosters = ref<Roster[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const sortRosters = (items: Roster[]) =>
    [...items].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    )

  const fetchRosters = async (query: RosterQuery = {}) => {
    loading.value = true
    error.value = null
    try {
      const params = new URLSearchParams()
      if (query.pool_id) params.append('pool_id', query.pool_id)
      if (query.season) params.append('season', query.season)
      const url = `/api/rosters${params.toString() ? `?${params.toString()}` : ''}`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: Roster[] = await res.json()
      rosters.value = sortRosters(data)
    } catch (e: any) {
      console.error('Error fetching rosters:', e)
      error.value = e?.message || 'Failed to fetch rosters'
    } finally {
      loading.value = false
    }
  }

  const createRoster = async (payload: RosterCreate): Promise<Roster> => {
    const res = await fetch('/api/rosters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      let message = `Failed to create roster (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    const created: Roster = await res.json()
    rosters.value = sortRosters([created, ...rosters.value])
    return created
  }

  const updateRoster = async (rosterId: string, payload: RosterUpdate): Promise<Roster> => {
    const res = await fetch(`/api/rosters/${rosterId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      let message = `Failed to update roster (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    const updated: Roster = await res.json()
    rosters.value = sortRosters(rosters.value.map((roster) => (roster.id === rosterId ? updated : roster)))
    return updated
  }

  const deleteRoster = async (rosterId: string) => {
    const res = await fetch(`/api/rosters/${rosterId}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      let message = `Failed to delete roster (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    rosters.value = rosters.value.filter((roster) => roster.id !== rosterId)
  }

  return { rosters, loading, error, fetchRosters, createRoster, updateRoster, deleteRoster }
}
