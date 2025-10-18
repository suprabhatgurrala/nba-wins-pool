import { ref } from 'vue'
import { parseUTCTimestamp } from '@/utils/time'

export type AuctionEvent = {
  type: string
  payload: any
  timestamp?: string
  created_at?: string
}

export function useAuctionEvents(auctionId: string) {
  const eventsUrl = `/api/auctions/${auctionId}/events`
  const historyUrl = `/api/auctions/${auctionId}/events/history`
  const eventSource = ref<EventSource | null>(null)
  const isConnected = ref(false)
  const error = ref<string | null>(null)
  const loading = ref(false)
  const events = ref<AuctionEvent[]>([])
  const latestEvent = ref<AuctionEvent | null>(null)
  let customEventTypes: string[] = []
  let handleEvent: ((ev: MessageEvent<string>) => void) | null = null

  const connect = () => {
    if (eventSource.value) return
    error.value = null
    try {
      const es = typeof window !== 'undefined' ? new EventSource(eventsUrl) : null
      if (!es) return
      eventSource.value = es
      customEventTypes = ['auction_started', 'auction_completed', 'bid_accepted', 'lot_closed']
      handleEvent = (ev: MessageEvent<string>) => {
        try {
          const data = JSON.parse(ev.data)
          const type = ev.type && ev.type !== 'message' ? ev.type : (data.type ?? 'message')
          // Ensure timestamp is properly formatted as UTC
          const timestamp = data.created_at || data.timestamp
          const utcTimestamp = timestamp
            ? (parseUTCTimestamp(timestamp)?.toISOString() ?? new Date().toISOString())
            : new Date().toISOString()

          const evt: AuctionEvent = {
            type,
            payload: data,
            created_at: utcTimestamp,
            timestamp: utcTimestamp,
          }
          latestEvent.value = evt
          events.value.unshift(evt)
          if (events.value.length > 50) events.value.pop()
        } catch (err) {
          // ignore parse errors
        }
      }
      es.onopen = () => {
        isConnected.value = true
      }
      es.onerror = () => {
        isConnected.value = false
        error.value = 'Connection error'
      }
      es.onmessage = (ev) => {
        handleEvent?.(ev as MessageEvent<string>)
      }
      customEventTypes.forEach((eventName) => {
        es.addEventListener(eventName, handleEvent as EventListener)
      })
    } catch (e: any) {
      error.value = e.message
    }
  }

  const disconnect = () => {
    if (eventSource.value) {
      customEventTypes.forEach((eventName) => {
        if (handleEvent) {
          eventSource.value?.removeEventListener(eventName, handleEvent as EventListener)
        }
      })
      customEventTypes = []
      handleEvent = null
      eventSource.value.close()
      eventSource.value = null
      isConnected.value = false
    }
  }

  const fetchHistoricalEvents = async () => {
    loading.value = true
    error.value = null
    try {
      const response = await fetch(historyUrl)
      if (!response.ok) {
        throw new Error(`Failed to fetch event history: ${response.status}`)
      }
      const historicalEvents = await response.json()

      // Transform backend events to match our format
      const transformedEvents: AuctionEvent[] = historicalEvents.map((event: any) => ({
        type: event.type || 'unknown',
        payload: event,
        timestamp: event.created_at || event.timestamp,
        created_at: event.created_at,
      }))

      // Replace events array with historical events (already sorted desc from backend)
      events.value = transformedEvents
    } catch (e: any) {
      error.value = e?.message || 'Failed to load event history'
    } finally {
      loading.value = false
    }
  }

  return {
    connect,
    disconnect,
    isConnected,
    error,
    loading,
    events,
    latestEvent,
    fetchHistoricalEvents,
  }
}
