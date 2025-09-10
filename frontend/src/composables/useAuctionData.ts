import { ref } from "vue"
import type { AuctionDataItem } from "@/types/pool"

export function useAuctionData(poolId: string) {
  const error = ref<string | null>(null)
  const loading = ref(true)
  const baseUrl = import.meta.env.VITE_BACKEND_URL
  const auctionUrl = `${baseUrl}/api/auction/data`
  const auctionTableData = ref<AuctionDataItem[] | null>(null)


  const fetchAuctionData = async () => {
    loading.value = true
    error.value = null

    try {
      const response = await fetch(auctionUrl)
      const data = await response.json()
      auctionTableData.value = data.data as AuctionDataItem[]
    } catch (err: any) {
      console.error('Error fetching auction data:', err)
      error.value = `Error fetching auction data: ${err.message}`
    } finally {
      loading.value = false
    }
  }

  return {
    auctionTableData,
    error,
    loading,
    fetchAuctionData,
  }
}
