import { ref } from 'vue'
import type { Auction, AuctionCreate, AuctionUpdate } from '@/types/pool'

export type AuctionQuery = {
  pool_id?: string
  season?: string
  status?: 'not_started' | 'active' | 'completed'
}

export function useAuctions() {
  const auctions = ref<Auction[]>([])
  const error = ref<string | null>(null)
  const loading = ref(true)

  const fetchAuctions = async (query: AuctionQuery = {}) => {
    loading.value = true
    error.value = null
    try {
      const params = new URLSearchParams()
      if (query.pool_id) params.append('pool_id', query.pool_id)
      if (query.season) params.append('season', query.season)
      if (query.status) params.append('status', query.status)
      const url = `/api/auctions${params.toString() ? `?${params.toString()}` : ''}`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      auctions.value = await res.json()
    } catch (e: any) {
      console.error('Error fetching auctions:', e)
      error.value = e?.message || 'Failed to fetch auctions'
    } finally {
      loading.value = false
    }
  }

  const createAuction = async (payload: AuctionCreate): Promise<Auction> => {
    const res = await fetch('/api/auctions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      let message = `Failed to create auction (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    const created: Auction = await res.json()
    auctions.value = [created, ...auctions.value]
    return created
  }

  const updateAuction = async (auctionId: string, payload: AuctionUpdate): Promise<Auction> => {
    const res = await fetch(`/api/auctions/${auctionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      let message = `Failed to update auction (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    const updated: Auction = await res.json()
    auctions.value = auctions.value.map((a) => (a.id === updated.id ? updated : a))
    return updated
  }

  return { auctions, error, loading, fetchAuctions, createAuction, updateAuction }
}
