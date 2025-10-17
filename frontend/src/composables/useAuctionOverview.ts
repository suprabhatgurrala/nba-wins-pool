import { ref } from 'vue'
import type { AuctionOverview } from '@/types/pool'

export function useAuctionOverview(auctionId: string) {
  const auctionOverview = ref<AuctionOverview | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(true)

  const auctionOverviewUrl = `/api/auctions/${auctionId}/overview`

  const fetchAuctionOverview = async () => {
    loading.value = true
    error.value = null

    try {
      const response = await fetch(auctionOverviewUrl)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      auctionOverview.value = await response.json()
    } catch (err: any) {
      console.error('Error fetching auction overview:', err)
      error.value = `Error fetching auction overview: ${err.message}`
    } finally {
      loading.value = false
    }
  }

  return {
    auctionOverview: auctionOverview,
    error,
    loading,
    fetchAuctionOverview: fetchAuctionOverview,
  }
}
