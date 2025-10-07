import { ref } from 'vue'

export function useAuctionBidding() {
  const loading = ref(false)
  const error = ref<string | null>(null)

  const submitBid = async (lotId: string, participantId: string, amount: number) => {
    loading.value = true
    error.value = null
    try {
      const url = `/api/bids`
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          lot_id: lotId,
          participant_id: participantId,
          amount: amount,
        }),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `Bid failed with status ${res.status}`)
      }
      return await res.json().catch(() => ({}))
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  return { submitBid, loading, error }
}

