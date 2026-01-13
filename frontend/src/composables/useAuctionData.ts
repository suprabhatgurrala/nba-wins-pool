import { ref } from 'vue'
import type { AuctionDataItem } from '@/types/pool'

export function useAuctionData(auctionId: string) {
  const error = ref<string | null>(null)
  const loading = ref(true)
  const auctionTableData = ref<AuctionDataItem[] | null>(null)
  const metadata = ref<{
    num_participants: number
    budget_per_participant: number
    teams_per_participant: number
    cached_at: string
    projection_date?: string
    source?: string
  } | null>(null)

  const fetchAuctionData = async () => {
    if (!auctionId) {
      error.value = 'Auction ID is required'
      loading.value = false
      return
    }

    loading.value = true
    error.value = null

    try {
      const response = await fetch(`/api/auctions/${auctionId}/valuation-data`)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      const data = await response.json()
      auctionTableData.value = data.data as AuctionDataItem[]
      metadata.value = {
        num_participants: data.num_participants,
        budget_per_participant: data.budget_per_participant,
        teams_per_participant: data.teams_per_participant,
        cached_at: data.cached_at,
        projection_date: data.projection_date,
        source: data.source,
      }
    } catch (err: any) {
      console.error('Error fetching auction valuation data:', err)
      error.value = `Error fetching auction valuation data: ${err.message}`
    } finally {
      loading.value = false
    }
  }

  return {
    auctionTableData,
    metadata,
    error,
    loading,
    fetchAuctionData,
  }
}
