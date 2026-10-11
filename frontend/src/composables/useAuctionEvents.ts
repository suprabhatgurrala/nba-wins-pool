import { ref } from 'vue'
import { parseUTCTimestamp } from '@/utils/time'

export type AuctionEvent = {
  type: string
  payload: any
  timestamp?: string
  created_at?: string
}

// Backend sends a `ping` event every 15s; treat the stream as dead if nothing arrives for this long.
const STALE_CONNECTION_MS = 45_000
const RECONNECT_BASE_DELAY_MS = 1_000
const RECONNECT_MAX_DELAY_MS = 30_000
const CUSTOM_EVENT_TYPES = [
  'auction_started',
  'auction_completed',
  'bid_accepted',
  'lot_closed',
  'participant_joined',
]
// Live-only events that aren't in the persisted history, so they must survive a history reload.
const EPHEMERAL_EVENT_TYPES = new Set(['participant_joined'])

export type UseAuctionEventsOptions = {
  /** Called after the stream re-opens following a drop, so the caller can resync state it may have missed. */
  onReconnect?: () => void | Promise<void>
}

export function useAuctionEvents(auctionId: string, options: UseAuctionEventsOptions = {}) {
  const eventsUrl = `/api/auctions/${auctionId}/events`
  const historyUrl = `/api/auctions/${auctionId}/events/history`
  const eventSource = ref<EventSource | null>(null)
  const isConnected = ref(false)
  const error = ref<string | null>(null)
  const loading = ref(false)
  const events = ref<AuctionEvent[]>([])
  const latestEvent = ref<AuctionEvent | null>(null)

  // True between connect() and disconnect(); drives automatic reconnection.
  let wantConnected = false
  let hasOpenedBefore = false
  let reconnectAttempts = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let watchdogTimer: ReturnType<typeof setInterval> | null = null
  let lastActivityAt = 0

  const handleEvent = (ev: MessageEvent<string>) => {
    lastActivityAt = Date.now()
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

  const handlePing = () => {
    lastActivityAt = Date.now()
  }

  const closeEventSource = () => {
    const es = eventSource.value
    if (!es) return
    es.onopen = null
    es.onerror = null
    es.onmessage = null
    CUSTOM_EVENT_TYPES.forEach((eventName) =>
      es.removeEventListener(eventName, handleEvent as EventListener),
    )
    es.removeEventListener('ping', handlePing)
    es.close()
    eventSource.value = null
    isConnected.value = false
  }

  const clearReconnectTimer = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  const scheduleReconnect = () => {
    if (!wantConnected || reconnectTimer) return
    const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** reconnectAttempts, RECONNECT_MAX_DELAY_MS)
    reconnectAttempts++
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      openEventSource()
    }, delay)
  }

  const openEventSource = () => {
    if (typeof window === 'undefined' || !wantConnected) return
    closeEventSource()
    clearReconnectTimer()
    try {
      const es = new EventSource(eventsUrl)
      eventSource.value = es
      lastActivityAt = Date.now()
      es.onopen = () => {
        lastActivityAt = Date.now()
        isConnected.value = true
        error.value = null
        reconnectAttempts = 0
        if (hasOpenedBefore) {
          Promise.resolve(options.onReconnect?.()).catch((err) => {
            console.warn('Failed to resync after reconnect:', err)
          })
        }
        hasOpenedBefore = true
      }
      es.onerror = () => {
        isConnected.value = false
        error.value = 'Connection error'
        // The browser retries on its own while CONNECTING; once CLOSED it gives up, so we take over.
        if (es.readyState === EventSource.CLOSED) {
          closeEventSource()
          scheduleReconnect()
        }
      }
      es.onmessage = (ev) => handleEvent(ev as MessageEvent<string>)
      CUSTOM_EVENT_TYPES.forEach((eventName) =>
        es.addEventListener(eventName, handleEvent as EventListener),
      )
      es.addEventListener('ping', handlePing)
    } catch (e: any) {
      error.value = e.message
      scheduleReconnect()
    }
  }

  // Force a fresh connection, e.g. when the page wakes up and the old socket may be silently dead.
  const reconnectNow = () => {
    if (!wantConnected) return
    reconnectAttempts = 0
    openEventSource()
  }

  const checkStale = () => {
    if (!wantConnected || reconnectTimer) return
    if (Date.now() - lastActivityAt > STALE_CONNECTION_MS) {
      reconnectNow()
    }
  }

  const handleVisibilityChange = () => {
    if (document.visibilityState === 'visible') checkStale()
  }

  const handlePageShow = (ev: PageTransitionEvent) => {
    // Restored from the back/forward cache: the old connection is gone.
    if (ev.persisted) reconnectNow()
  }

  const connect = () => {
    if (wantConnected || typeof window === 'undefined') return
    wantConnected = true
    hasOpenedBefore = false
    reconnectAttempts = 0
    error.value = null
    openEventSource()
    watchdogTimer = setInterval(checkStale, 5_000)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('online', reconnectNow)
    window.addEventListener('pageshow', handlePageShow)
  }

  const disconnect = () => {
    if (!wantConnected) return
    wantConnected = false
    clearReconnectTimer()
    if (watchdogTimer) {
      clearInterval(watchdogTimer)
      watchdogTimer = null
    }
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    window.removeEventListener('online', reconnectNow)
    window.removeEventListener('pageshow', handlePageShow)
    closeEventSource()
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

      // Replace events with history, keeping live-only events and re-sorting newest first
      const ephemeralEvents = events.value.filter((e) => EPHEMERAL_EVENT_TYPES.has(e.type))
      events.value = [...transformedEvents, ...ephemeralEvents].sort(
        (a, b) =>
          (parseUTCTimestamp(b.created_at ?? b.timestamp)?.getTime() ?? 0) -
          (parseUTCTimestamp(a.created_at ?? a.timestamp)?.getTime() ?? 0),
      )
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
