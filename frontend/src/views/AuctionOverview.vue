<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import { useAuctionOverview } from '@/composables/useAuctionOverview'
import { useAuctionEvents } from '@/composables/useAuctionEvents'
import { useAuctionBidding } from '@/composables/useAuctionBidding'
import { useAudio } from '@/composables/useAudio'
import Button from 'primevue/button'
import Drawer from 'primevue/drawer'
import Dialog from 'primevue/dialog'
import Panel from 'primevue/panel'
import Tag from 'primevue/tag'
import Card from 'primevue/card'
import Dropdown from 'primevue/dropdown'
import Message from 'primevue/message'
import InputNumber from 'primevue/inputnumber'
import InputGroup from 'primevue/inputgroup'
import InputGroupAddon from 'primevue/inputgroupaddon'
import Avatar from 'primevue/avatar'
import TreeTable from 'primevue/treetable'
import Column from 'primevue/column'
import type { TreeNode } from 'primevue/treenode'
import Divider from 'primevue/divider'
import AuctionForm from '@/components/pool/AuctionForm.vue'
import AuctionTable from '@/components/pool/AuctionTable.vue'
import PlayerAvatar from '@/components/common/PlayerAvatar.vue'
import { useAuctions } from '@/composables/useAuctions'
import { useAuctionData } from '@/composables/useAuctionData'
import type {
  AuctionCreate,
  AuctionUpdate,
  AuctionStatus,
  AuctionOverviewParticipant,
} from '@/types/pool'
import { formatCurrency } from '@/utils/currency'
import { formatUTCDate, formatUTCTime, parseUTCTimestampToMs } from '@/utils/time'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const confirm = useConfirm()
const auctionId = route.params.auctionId as string

const {
  auctionOverview: auctionOverview,
  error: auctionOverviewError,
  fetchAuctionOverview,
} = useAuctionOverview(auctionId)

// Drawer & edit dialog state
const showDrawer = ref(false)
const showEditDialog = ref(false)
const editSubmitting = ref(false)
const editError = ref<string | null>(null)
const actionSubmitting = ref(false)
const actionError = ref<string | null>(null)
const importParticipantsSubmitting = ref(false)
const importParticipantsError = ref<string | null>(null)
const importParticipantsMessage = ref<string | null>(null)
const importLotsSubmitting = ref(false)
const importLotsError = ref<string | null>(null)
const importLotsMessage = ref<string | null>(null)
const nominationParticipantId = ref<string | null>(null)
const nominationSubmitting = ref(false)
const nominationError = ref<string | null>(null)
const showNominationDialog = ref(false)
const selectedTeamForNomination = ref<any | null>(null)
const nominationBidAmount = ref<number | null>(null)
const closeLotSubmitting = ref(false)
const closeLotError = ref<string | null>(null)

// Rotating title state
const titleIndex = ref(0)
const titleOptions = computed(() => [
  '⚖️ Auction Draft 💰',
  `🏀 ${auctionOverview.value?.pool.name} 🏆`,
  `🏀 ${auctionOverview.value?.season} 🏆`,
])

// Auctions API for status updates
const { updateAuction } = useAuctions()

// Format auction status for display
const statusDisplay = computed(() => {
  const s = String(auctionOverview.value?.status || '')
  // Convert snake_case to Title Case
  return s
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
})

// Tag severity for auction status
const statusSeverity = computed(() => {
  const s = String(auctionOverview.value?.status || '')
  if (s === 'active') return 'success'
  if (s === 'completed') return 'info'
  return 'secondary'
})

// Handle edit dialog submit
async function handleAuctionEditSubmit(payload: AuctionCreate | AuctionUpdate) {
  editSubmitting.value = true
  editError.value = null
  try {
    const updatePayload = payload as AuctionUpdate
    await updateAuction(auctionId, updatePayload)
    await fetchAuctionOverview()
    showEditDialog.value = false
    toast.add({
      severity: 'success',
      summary: 'Auction Updated',
      detail: 'Auction configuration has been updated',
      life: 3000,
    })
  } catch (e: any) {
    editError.value = e?.message || 'Failed to update auction'
  } finally {
    editSubmitting.value = false
  }
}

async function handleImportParticipants() {
  importParticipantsSubmitting.value = true
  importParticipantsError.value = null
  importParticipantsMessage.value = null
  try {
    const res = await fetch('/api/auction-participants/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: 'pool',
        auction_id: auctionId,
      }),
    })
    // NOTE: Backend expects auction to be in draft status for participant import.
    if (!res.ok) {
      let message = `Failed to import participants (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    const imported = await res.json()
    if (Array.isArray(imported)) {
      const count = imported.length
      importParticipantsMessage.value = count
        ? `Imported ${count} participant${count === 1 ? '' : 's'} from pool rosters.`
        : 'No new participants were added.'
    } else {
      importParticipantsMessage.value = 'Imported participants from pool rosters.'
    }
    await fetchAuctionOverview()
  } catch (e: any) {
    importParticipantsError.value = e?.message || 'Failed to import participants'
  } finally {
    importParticipantsSubmitting.value = false
  }
}

async function handleImportLotsFromLeague() {
  importLotsSubmitting.value = true
  importLotsError.value = null
  importLotsMessage.value = null
  try {
    const res = await fetch('/api/auction-lots/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: 'league',
        source_id: 'nba',
        auction_id: auctionId,
      }),
    })
    // NOTE: Backend expects league slug to be lowercase (e.g., "nba").
    if (!res.ok) {
      let message = `Failed to import lots (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    const added = await res.json()
    if (Array.isArray(added)) {
      const count = added.length
      importLotsMessage.value = count
        ? `Imported ${count} lot${count === 1 ? '' : 's'} from the NBA.`
        : 'No new lots were added (all teams already present).'
    } else {
      importLotsMessage.value = 'Imported league lots into the auction.'
    }
    await fetchAuctionOverview()
  } catch (e: any) {
    importLotsError.value = e?.message || 'Failed to import league lots'
  } finally {
    importLotsSubmitting.value = false
  }
}

function handleTeamNomination(team: any) {
  // Find the lot for this team - must be in READY status
  // Match by team_id (most reliable), fallback to logo_url if team_id not available
  const lot = team.team_id
    ? readyLots.value.find((l) => l.team?.id === team.team_id)
    : readyLots.value.find((l) => l.team?.logo_url === team.logo_url)

  if (!lot) {
    toast.add({
      severity: 'error',
      summary: 'Nomination Error',
      detail: 'This team is not available for nomination (lot must be in ready status)',
      life: 3000,
    })
    return
  }
  selectedTeamForNomination.value = { ...team, lotId: lot.id, lotTeamName: lot.team?.name }
  nominationBidAmount.value = minIncrement.value

  // Auto-select participant if in participant mode
  if (viewMode.value === 'participant' && selectedParticipantId.value) {
    nominationParticipantId.value = selectedParticipantId.value
  }

  showNominationDialog.value = true
}

async function submitNomination() {
  nominationError.value = null
  if (
    !selectedTeamForNomination.value ||
    !nominationParticipantId.value ||
    nominationBidAmount.value == null
  ) {
    toast.add({
      severity: 'error',
      summary: 'Nomination Error',
      detail: 'Please select a participant and enter a bid amount',
      life: 3000,
    })
    return
  }
  const amount = Math.floor(Number(nominationBidAmount.value))
  if (!Number.isInteger(amount) || amount < minIncrement.value) {
    toast.add({
      severity: 'error',
      summary: 'Invalid Bid',
      detail: `Opening bid must be at least ${formatCurrency(minIncrement.value)}`,
      life: 3000,
    })
    return
  }
  nominationSubmitting.value = true
  try {
    await submitBid(selectedTeamForNomination.value.lotId, nominationParticipantId.value, amount)
    toast.add({
      severity: 'success',
      summary: 'Team Nominated',
      detail: `${selectedTeamForNomination.value.team} nominated with opening bid of ${formatCurrency(amount)}`,
      life: 3000,
    })
    showNominationDialog.value = false
    selectedTeamForNomination.value = null
    nominationBidAmount.value = null
    await fetchAuctionOverview()
  } catch (e: any) {
    nominationError.value = e?.message || 'Failed to nominate team'
    toast.add({
      severity: 'error',
      summary: 'Nomination Failed',
      detail: nominationError.value,
      life: 3000,
    })
  } finally {
    nominationSubmitting.value = false
  }
}

const confirmCloseLot = () => {
  if (!currentLot.value) return
  confirm.require({
    message: `Close the lot for ${currentLot.value.team?.name}? The current winning bid of ${formatCurrency(currentLot.value.winning_bid?.amount)} will be awarded to ${currentLot.value.winning_bid?.bidder_name}.`,
    header: 'Close Lot',
    rejectLabel: 'Cancel',
    rejectProps: {
      label: 'Cancel',
      severity: 'secondary',
      outlined: true,
    },
    acceptLabel: 'Close Lot',
    acceptProps: {
      label: 'Close Lot',
      severity: 'primary',
      outlined: true,
    },
    accept: () => {
      closeLot()
    },
  })
}

async function closeLot() {
  if (!currentLot.value) return
  closeLotSubmitting.value = true
  closeLotError.value = null
  try {
    const res = await fetch(`/api/auction-lots/${currentLot.value.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'closed' }),
    })
    if (!res.ok) {
      let message = `Failed to close lot (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    toast.add({
      severity: 'success',
      summary: 'Lot Closed',
      detail: `${currentLot.value.team?.name} awarded to ${currentLot.value.winning_bid?.bidder_name} for ${formatCurrency(currentLot.value.winning_bid?.amount)}`,
      life: 3000,
    })
    await fetchAuctionOverview()
  } catch (e: any) {
    closeLotError.value = e?.message || 'Failed to close lot'
    toast.add({
      severity: 'error',
      summary: 'Close Lot Failed',
      detail: closeLotError.value,
      life: 3000,
    })
  } finally {
    closeLotSubmitting.value = false
  }
}

// Quick status transition buttons in drawer header
const quickTransition = async (next: AuctionStatus) => {
  actionSubmitting.value = true
  actionError.value = null
  try {
    await updateAuction(auctionId, { status: next })
    await fetchAuctionOverview()
    // Refresh events to show the status change event (e.g., "auction started")
    await fetchHistoricalEvents()
    // Connect to live events if transitioning to active
    if (next === 'active' && !isConnected.value) {
      connect()
    }
  } catch (e: any) {
    actionError.value = e?.message || 'Failed to update status'
  } finally {
    actionSubmitting.value = false
  }
}

// Confirm and start auction
const confirmStartAuction = () => {
  confirm.require({
    message: 'Are you sure you want to start this auction?',
    header: 'Start Auction',
    rejectLabel: 'Cancel',
    rejectProps: {
      label: 'Cancel',
      severity: 'secondary',
      outlined: true,
    },
    acceptLabel: 'Start',
    acceptProps: {
      label: 'Start Auction',
      severity: 'success',
      outlined: true,
    },
    accept: () => {
      quickTransition('active')
    },
  })
}

// Confirm and complete auction
const confirmCompleteAuction = () => {
  confirm.require({
    message: 'Are you sure you want to complete this auction?',
    header: 'Complete Auction',
    rejectLabel: 'Cancel',
    rejectProps: {
      label: 'Cancel',
      severity: 'secondary',
      outlined: true,
    },
    acceptLabel: 'Complete',
    acceptProps: {
      label: 'Complete Auction',
      severity: 'success',
      outlined: true,
    },
    accept: () => {
      quickTransition('completed')
    },
  })
}

const viewMode = ref<'spectator' | 'participant'>('spectator')
const selectedParticipantId = ref<string | null>(null)
const bidAmount = ref<number | null>(null)
const isFeedExpanded = ref(false)
const feedScrollContainer = ref<HTMLElement | null>(null)
const latestEventIndex = ref<number>(-1)

// Timer state for "time since last bid"
const currentTime = ref(Date.now())
const timerInterval = ref<number | null>(null)

// Table density state controls internal table scaling (default to 'M' on all devices)
const tableScale = ref<'S' | 'M' | 'L'>('M')

const { submitBid, loading: biddingLoading, error: biddingError } = useAuctionBidding()
const {
  connect,
  disconnect,
  isConnected,
  latestEvent,
  events,
  error: sseError,
  loading: eventsLoading,
  fetchHistoricalEvents,
} = useAuctionEvents(auctionId)
const {
  auctionTableData,
  error: valuationError,
  loading: valuationLoading,
  fetchAuctionData,
} = useAuctionData(auctionId)
const { playDraftSound, playDing } = useAudio()

const participants = computed(() => auctionOverview.value?.participants ?? [])
const readyLots = computed(
  () => auctionOverview.value?.lots.filter((lot) => lot.status === 'ready') ?? [],
)
const nominatableTeamIds = computed(() => {
  const teamIds = new Set<string>()
  readyLots.value.forEach((lot) => {
    if (lot.team?.id) {
      teamIds.add(lot.team.id)
    }
  })
  return teamIds
})

const closedLotTeamIds = computed(() => {
  const teamIds = new Set<string>()
  auctionOverview.value?.lots
    .filter((lot) => lot.status === 'closed')
    .forEach((lot) => {
      if (lot.team?.id) {
        teamIds.add(lot.team.id)
      }
    })
  return teamIds
})

const participantOptions = computed(() =>
  participantSummaries.value
    .filter((p) => p.remainingSlots > 0) // Only show participants who can still draft teams
    .map((p) => ({
      label: `${p.name} · ${formatCurrency(p.budget)}`,
      value: p.id,
    })),
)

// Check if any participant can still nominate/draft teams
const anyParticipantCanNominate = computed(() =>
  participantSummaries.value.some((p) => p.remainingSlots > 0),
)
// Selected participant helper (declared early for watchers)
const selectedParticipant = computed(
  () => participantSummaries.value.find((p) => p.id === selectedParticipantId.value) || null,
)
const currentLot = computed(() => auctionOverview.value?.current_lot ?? null)

// Get the timestamp of the last event (most recent event is first in the array)
const lastEventTimestamp = computed(() => {
  if (!events.value.length) return null
  const lastEvent = events.value[0]
  const timestamp = lastEvent.timestamp || lastEvent.created_at
  return parseUTCTimestampToMs(timestamp)
})

// Format elapsed time since last event
const timeSinceLastBid = computed(() => {
  if (!lastEventTimestamp.value || !currentLot.value || currentLot.value.status !== 'open') {
    return null
  }
  const elapsed = Math.max(0, Math.floor((currentTime.value - lastEventTimestamp.value) / 1000))
  const minutes = Math.floor(elapsed / 60)
  const seconds = elapsed % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
})

const minIncrement = computed(() => {
  // Whole-dollar increments only
  const v = auctionOverview.value?.min_bid_increment
  const n = Math.floor(Number(v))
  return Number.isFinite(n) && n >= 1 ? n : 1
})
const nextMinBid = computed(() => {
  // Opening bid is min_bid_increment, then last winning bid + min increment (integers)
  const curr = Number(currentLot.value?.winning_bid?.amount ?? 0)
  return curr > 0 ? Math.floor(curr + minIncrement.value) : minIncrement.value
})
const requiredTeams = computed(() => auctionOverview.value?.max_lots_per_participant ?? 0)
type ParticipantSummary = AuctionOverviewParticipant & {
  remainingSlots: number
}
const participantSummaries = computed<ParticipantSummary[]>(() =>
  participants.value.map((participant) => {
    const lots = participant.lots_won ?? []
    return {
      ...participant,
      lots_won: lots,
      remainingSlots: Math.max(requiredTeams.value - lots.length, 0),
    }
  }),
)
const expandedParticipantKeys = ref<Record<string, boolean>>({})

// Check if all participants are expanded
const allParticipantsExpanded = computed(() => {
  const participantKeys = participantTreeNodes.value.map((node) => String(node.key))
  return (
    participantKeys.length > 0 && participantKeys.every((key) => expandedParticipantKeys.value[key])
  )
})

// Toggle expand/collapse all participants
const toggleAllParticipants = () => {
  const updated: Record<string, boolean> = {}
  const shouldExpand = !allParticipantsExpanded.value

  participantTreeNodes.value.forEach((node) => {
    const key = String(node.key)
    if (shouldExpand) {
      updated[key] = true
    }
    // If collapsing, we just don't add the key (undefined = collapsed)
  })

  expandedParticipantKeys.value = updated
}

// Handle clicks on participant rows to toggle expansion
const handleRowClick = (event: MouseEvent) => {
  const row = (event.target as HTMLElement).closest('tr')
  if (!row || row.getAttribute('aria-level') !== '1') return

  const tbody = row.parentElement
  if (!tbody) return

  const topLevelRows = Array.from(tbody.querySelectorAll('tr[aria-level="1"]'))
  const rowIndex = topLevelRows.indexOf(row)

  if (rowIndex >= 0 && rowIndex < participantTreeNodes.value.length) {
    const key = String(participantTreeNodes.value[rowIndex].key)
    const updated = { ...expandedParticipantKeys.value }

    if (updated[key]) {
      delete updated[key]
    } else {
      updated[key] = true
    }

    expandedParticipantKeys.value = updated
  }
}

// Handle clicking on participant avatar to select them in participate mode
const handleParticipantAvatarClick = (participantId: string, event: MouseEvent) => {
  if (viewMode.value === 'participant') {
    event.stopPropagation() // Prevent row expansion
    selectedParticipantId.value = participantId
  }
}

// Handle clicking on participant in drawer to select them
const handleDrawerParticipantClick = (participantId: string) => {
  if (viewMode.value === 'participant' && !selectedParticipantId.value) {
    selectedParticipantId.value = participantId
  }
}

// Handle participate button click in drawer
const handleParticipateButtonClick = () => {
  if (viewMode.value === 'participant' && selectedParticipantId.value) {
    // Clear selection to allow choosing a different participant
    selectedParticipantId.value = null
  } else {
    // Switch to participate mode
    viewMode.value = 'participant'
  }
}

// Passthrough props for TreeTable styling and interaction
const treeTablePt = {
  tbody: {
    onClick: handleRowClick,
  },
  row: {
    class: 'cursor-pointer transition-colors',
  },
}
const participantTreeNodes = computed<TreeNode[]>(() => {
  // Sort participants: active participant first when in participant mode
  const sortedParticipants = [...participantSummaries.value]
  if (viewMode.value === 'participant' && selectedParticipantId.value) {
    sortedParticipants.sort((a, b) => {
      if (a.id === selectedParticipantId.value) return -1
      if (b.id === selectedParticipantId.value) return 1
      return 0
    })
  }

  return sortedParticipants.map((participant) => ({
    key: participant.id,
    data: {
      type: 'participant',
      participant,
    },
    children: (participant.lots_won ?? []).map((lot, index) => ({
      key: `${participant.id}-${lot.id ?? index}`,
      data: {
        type: 'lot',
        participant,
        lot,
      },
      leaf: true,
    })),
  }))
})
const draftedTeams = computed(() => selectedParticipant.value?.lots_won.length ?? 0)
const remainingToDraftAfterWin = computed(() =>
  Math.max(requiredTeams.value - draftedTeams.value - 1, 0),
)
const remainingBudget = computed(() =>
  selectedParticipant.value ? parseFloat(selectedParticipant.value.budget) : 0,
)
const smartMaxBid = computed(() => {
  // Enforce smart max: budget - (min_bid_increment × remaining teams to draft after this win)
  const budget = Math.floor(Number(remainingBudget.value) || 0)
  const reserve = Math.max(0, Number(remainingToDraftAfterWin.value) || 0) * minIncrement.value
  const cap = Math.max(0, budget - reserve)
  return Math.floor(cap)
})
watch(
  currentLot,
  () => {
    if (currentLot.value) {
      const min = nextMinBid.value
      const max = smartMaxBid.value
      if (min > max) {
        bidAmount.value = null
      } else if (bidAmount.value != null) {
        bidAmount.value = bidAmount.value < min || bidAmount.value > max ? min : bidAmount.value
      }
    } else {
      bidAmount.value = null
    }
  },
  { immediate: true },
)
// Re-clamp when participant or budgets change
watch([selectedParticipant, smartMaxBid, nextMinBid], () => {
  if (!currentLot.value) return
  const min = nextMinBid.value
  const max = smartMaxBid.value
  if (min > max) {
    bidAmount.value = null
  } else if (bidAmount.value != null && (bidAmount.value < min || bidAmount.value > max)) {
    bidAmount.value = min
  }
})
const canBid = computed(() => {
  const base =
    viewMode.value === 'participant' &&
    !!selectedParticipant.value &&
    !!currentLot.value &&
    draftedTeams.value < requiredTeams.value &&
    String(currentLot.value.status || '').toLowerCase() !== 'closed'
  // Must also be able to meet next minimum
  return base && nextMinBid.value <= smartMaxBid.value
})

const cannotBidReason = computed(() => {
  if (viewMode.value !== 'participant' || !selectedParticipant.value) {
    return null
  }
  if (!currentLot.value) {
    return 'No lot is currently open for bidding'
  }
  if (draftedTeams.value >= requiredTeams.value) {
    return 'You have already drafted the maximum number of teams'
  }
  if (nextMinBid.value > smartMaxBid.value) {
    return `Insufficient funds: minimum bid is ${formatCurrency(nextMinBid.value)} but you can only bid up to ${formatCurrency(smartMaxBid.value)}`
  }
  return null
})
const bidIsValid = computed(() => {
  if (!canBid.value || bidAmount.value == null) return false
  const amt = Number(bidAmount.value)
  return Number.isInteger(amt) && amt >= nextMinBid.value && amt <= smartMaxBid.value
})

// Format event for display
function formatEventMessage(event: any) {
  const type = event.type || event.payload?.type
  const payload = event.payload

  switch (type) {
    case 'bid_accepted':
      return {
        icon: 'gavel',
        message: `bid ${formatCurrency(payload.lot?.winning_bid?.amount)} on`,
        participant: payload.lot?.winning_bid?.bidder_name,
        team: payload.lot?.team,
      }
    case 'lot_closed':
      return {
        icon: 'check-circle',
        message: `won`,
        participant: payload.lot?.winning_bid?.bidder_name,
        team: payload.lot?.team,
      }
    case 'auction_started':
      return {
        icon: 'megaphone',
        message: 'Auction started',
        participant: null,
        team: null,
      }
    case 'auction_completed':
      return {
        icon: 'flag',
        message: 'Auction completed',
        participant: null,
        team: null,
      }
    default:
      return {
        icon: 'info-circle',
        message: JSON.stringify(payload),
        participant: null,
        team: null,
      }
  }
}

function formatTime(timestamp: string | undefined) {
  return formatUTCTime(timestamp)
}

onMounted(async () => {
  await fetchAuctionOverview()
  // Fetch historical events first
  await fetchHistoricalEvents()
  // Update current time after events are loaded to ensure accurate initial timer display
  currentTime.value = Date.now()
  // Only fetch auction valuation data if there are participants and lots
  if (participants.value.length > 0 && auctionOverview.value?.lots.length) {
    await fetchAuctionData()
  }
  // Only connect to live events if auction is active
  if (auctionOverview.value?.status === 'active') {
    connect()
  }

  // Start title rotation
  setInterval(() => {
    titleIndex.value = (titleIndex.value + 1) % titleOptions.value.length
  }, 5000)

  // Start timer for "time since last bid"
  timerInterval.value = window.setInterval(() => {
    currentTime.value = Date.now()
  }, 1000)
})
onUnmounted(() => {
  disconnect()
  if (timerInterval.value) {
    clearInterval(timerInterval.value)
  }
  if (!auctionOverview.value) {
    router.replace({ name: 'not-found' })
  }
})
watch(auctionOverviewError, (err) => {
  if (err && String(err).includes('HTTP 404')) {
    router.replace({ name: 'not-found' })
  }
})
watch(latestEvent, (newEvent) => {
  // On any live event, refresh the overview to stay in sync
  fetchAuctionOverview()

  if (newEvent) {
    const eventType = newEvent.type || newEvent.payload?.type
    
    // Play NBA draft sound when a lot is closed
    if (eventType === 'lot_closed') {
      playDraftSound().catch((err) => {
        console.warn('Failed to play draft sound:', err)
      })
    } else {
      // Play subtle ding for other auction events
      playDing().catch((err) => {
        console.warn('Failed to play notification ding:', err)
      })
    }
  }

  // Trigger flash animation for new event
  if (newEvent) {
    latestEventIndex.value = 0
    setTimeout(() => {
      latestEventIndex.value = -1
    }, 2000)
  }
})

// Scroll feed to top when events change or feed collapses
watch(
  [events, isFeedExpanded],
  () => {
    if (!isFeedExpanded.value && feedScrollContainer.value) {
      // When collapsed, scroll to top to show most recent events
      setTimeout(() => {
        if (feedScrollContainer.value) {
          feedScrollContainer.value.scrollTop = 0
        }
      }, 50)
    }
  },
  { flush: 'post' },
)

// Watch for auction status changes to connect/disconnect SSE
watch(
  () => auctionOverview.value?.status,
  (newStatus, oldStatus) => {
    if (newStatus === 'active' && oldStatus !== 'active' && !isConnected.value) {
      // Auction just became active, connect to live events
      connect()
    } else if (newStatus !== 'active' && isConnected.value) {
      // Auction is no longer active, disconnect from live events
      disconnect()
    }
  },
)

watch(
  () => viewMode.value,
  (vm) => {
    // Clear selected participant when switching to spectator mode
    if (vm === 'spectator') {
      selectedParticipantId.value = null
    }
    // Clear bid amount when switching to participant mode
    if (vm === 'participant') {
      bidAmount.value = null
    }
  },
)

watch(
  () => participants.value,
  (list) => {
    if (!list.length) {
      selectedParticipantId.value = null
      nominationParticipantId.value = null
      return
    }
    // Clear selected participant if they no longer exist
    if (selectedParticipantId.value && !list.find((p) => p.id === selectedParticipantId.value)) {
      selectedParticipantId.value = null
    }
    // Set default nomination participant if needed
    if (
      !nominationParticipantId.value ||
      !list.find((p) => p.id === nominationParticipantId.value)
    ) {
      nominationParticipantId.value = list[0].id
    }
  },
  { immediate: true },
)

// Watch for participants and lots being added to fetch auction data
watch(
  () => [participants.value.length, auctionOverview.value?.lots.length] as const,
  ([participantCount, lotCount], [prevParticipantCount, prevLotCount]) => {
    // If we now have both participants and lots, and we didn't before, fetch auction data
    if (
      participantCount > 0 &&
      lotCount != null &&
      lotCount > 0 &&
      (prevParticipantCount === 0 || prevLotCount == null || prevLotCount === 0)
    ) {
      fetchAuctionData()
    }
  },
)
watch(showDrawer, (open) => {
  if (!open) {
    importParticipantsError.value = null
    importParticipantsMessage.value = null
    importLotsError.value = null
    importLotsMessage.value = null
    nominationError.value = null
    actionError.value = null
    // If drawer was closed without selecting a participant, revert to spectator
    if (viewMode.value === 'participant' && !selectedParticipantId.value) {
      viewMode.value = 'spectator'
    }
  }
})

watch(showNominationDialog, (open) => {
  if (!open) {
    selectedTeamForNomination.value = null
    nominationBidAmount.value = null
    nominationError.value = null
  }
})

const onSubmitBid = async () => {
  if (!canBid.value || !currentLot.value || !selectedParticipant.value || bidAmount.value == null) {
    toast.add({
      severity: 'error',
      summary: 'Bid Error',
      detail: 'Unable to submit bid. Check participant and lot status.',
      life: 3000,
    })
    return
  }
  const amount = Math.floor(Number(bidAmount.value))
  if (!Number.isInteger(amount) || amount < nextMinBid.value || amount > smartMaxBid.value) {
    toast.add({
      severity: 'error',
      summary: 'Invalid Bid',
      detail: `Bid must be a whole dollar between ${formatCurrency(nextMinBid.value)} and ${formatCurrency(smartMaxBid.value)}`,
      life: 3000,
    })
    return
  }
  try {
    await submitBid(currentLot.value.id, selectedParticipant.value.id, amount)
    toast.add({
      severity: 'success',
      summary: 'Bid Submitted',
      detail: `Your bid of ${formatCurrency(amount)} has been placed`,
      life: 3000,
    })
    bidAmount.value = null // Clear input after successful bid
    await fetchAuctionOverview()
  } catch (e: any) {
    toast.add({
      severity: 'error',
      summary: 'Bid Failed',
      detail: biddingError.value || e?.message || 'Failed to submit bid',
      life: 3000,
    })
  }
}
</script>

<template>
  <!-- <TopBanner
    v-if="auctionOverview?.status === 'active'"
    to="#"
    label="Auction Live Now"
    :showDot="true"
    trailingIcon=""
    @click.prevent
  /> -->
  <header>
    <div class="flex items-center justify-between p-4">
      <Button
        icon="pi pi-arrow-left"
        variant="outlined"
        severity="secondary"
        @click="
          router.push({
            name: 'pool-season',
            params: { slug: auctionOverview?.pool.id, season: auctionOverview?.season },
          })
        "
        aria-label="Back"
      />
      <Transition name="fade" mode="out-in">
        <p :key="titleIndex" class="text-xl font-bold">{{ titleOptions[titleIndex] }}</p>
      </Transition>
      <Button
        icon="pi pi-bars"
        variant="outlined"
        severity="secondary"
        @click="showDrawer = true"
        aria-label="Menu"
      />
    </div>
  </header>

  <main>
    <div class="flex flex-col items-center">
      <!-- <p class="text-2xl font-extrabold text-center text-primary">{{ auctionOverview?.pool.name }}</p> -->
      <div class="flex items-center gap-4">
        <!-- <p class="text-4xl font-extrabold text-center text-primary">Auction Draft</p> -->
        <!-- <LiveDot v-if="auctionOverview?.status === 'active'" color="var(--p-red-500)" :size="16" /> -->
      </div>

      <!-- <p class="text-xl font-medium text-center">{{ auctionOverview?.pool.name }}</p> -->
      <!-- <p class="text-xl font-medium text-surface-400 italic text-center">{{ auctionOverview?.season }}</p> -->
    </div>

    <!-- Empty State: No participants or lots configured -->
    <div
      v-if="!participants.length || !auctionOverview?.lots.length"
      class="flex items-center justify-center px-4 py-12"
    >
      <Panel class="max-w-md text-surface-400" header="Configure Your Auction">
        <div class="flex flex-col gap-2">
          <p class="text-sm">
            To get started, please configure the auction using the menu on the right.
          </p>
          <ul class="text-sm list-disc list-inside space-y-1 mt-2">
            <li v-if="!participants.length">Import participants from pool rosters</li>
            <li v-if="!auctionOverview?.lots.length">Import lots from the NBA league</li>
          </ul>
        </div>
      </Panel>
    </div>

    <!-- 2-Column Layout: Left (Current Lot + Feed + Participants) | Right (Team Valuations) -->
    <div v-else class="px-2 lg:px-4 max-w-full lg:max-w-[75vw] mx-auto">
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-2">
        <!-- Left Column: Current Lot, Activity Feed, Participants -->
        <div class="flex flex-col gap-4 lg:col-span-1">
          <!-- Current Lot Card -->
          <Card
            v-if="currentLot"
            class="border-2 rounded-xl"
            :class="[
              currentLot.status === 'open'
                ? 'border-primary'
                : 'border-[var(--p-content-border-color)]',
              currentLot.status === 'closed' ? 'opacity-65' : '',
            ]"
          >
            <template #header>
              <div class="flex items-center gap-2 pt-3 px-3 justify-between">
                <Tag
                  class="text-xs"
                  :value="currentLot.status.toUpperCase()"
                  :severity="currentLot.status === 'open' ? 'primary' : 'secondary'"
                />
                <p v-if="viewMode === 'participant'" class="text-xs text-surface-400">
                  You: {{ selectedParticipant?.name }}
                </p>
              </div>
            </template>
            <template #content>
              <div class="flex justify-between pb-2">
                <div class="flex items-center gap-2">
                  <div class="flex flex-col items-center gap-2">
                    <Avatar
                      v-if="currentLot.team?.logo_url"
                      :image="currentLot.team.logo_url"
                      size="xlarge"
                    />
                  </div>
                  <div>
                    <p class="text-2xl font-bold">{{ currentLot.team?.name }}</p>
                    <div v-if="currentLot.winning_bid" class="flex flex-col gap-0.5">
                      <p class="text-sm text-surface-300 font-medium">
                        Winner: {{ currentLot.winning_bid.bidder_name }}
                      </p>
                      <p
                        v-if="timeSinceLastBid"
                        class="text-xs text-surface-400 font-medium italic"
                      >
                        Time since last bid: {{ timeSinceLastBid }}
                      </p>
                    </div>
                  </div>
                </div>
                <div class="flex items-center">
                  <div class="text-right">
                    <div v-if="currentLot.winning_bid">
                      <div class="text-3xl font-bold text-primary">
                        {{ formatCurrency(currentLot.winning_bid.amount) }}
                      </div>
                    </div>
                    <div v-else>
                      <div class="text-lg font-semibold">{{ formatCurrency(nextMinBid) }}</div>
                      <div class="text-xs text-surface-500">Opening bid</div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="flex flex-col gap-4">
                <!-- Bidding Section (Participant Mode Only) -->
                <div
                  v-if="
                    viewMode === 'participant' &&
                    selectedParticipant &&
                    currentLot.status === 'open'
                  "
                >
                  <div v-if="!canBid && cannotBidReason" class="text-sm text-surface-500 italic">
                    {{ cannotBidReason }}
                  </div>

                  <div v-else-if="canBid" class="flex flex-col gap-3 items-center">
                    <!-- Bid Input -->
                    <InputGroup>
                      <InputGroupAddon>
                        <Button
                          icon="pi pi-minus"
                          text
                          size="small"
                          :disabled="!bidAmount || bidAmount <= nextMinBid"
                          @click="
                            bidAmount = Math.max(
                              nextMinBid,
                              (bidAmount || nextMinBid) - minIncrement,
                            )
                          "
                        />
                      </InputGroupAddon>
                      <InputNumber
                        input-class="text-center"
                        v-model="bidAmount"
                        :min="nextMinBid"
                        :max="smartMaxBid"
                        :step="minIncrement"
                        mode="decimal"
                        :useGrouping="false"
                        placeholder="Enter bid amount"
                        @input="(e) => bidAmount = typeof e.value === 'number' ? e.value : null"
                      />
                      <InputGroupAddon>
                        <Button
                          icon="pi pi-plus"
                          text
                          size="small"
                          :disabled="bidAmount != null && bidAmount >= smartMaxBid"
                          @click="
                            bidAmount =
                              bidAmount == null
                                ? nextMinBid
                                : Math.min(smartMaxBid, bidAmount + minIncrement)
                          "
                        />
                      </InputGroupAddon>
                    </InputGroup>

                    <!-- Quick Bid Tags -->
                    <div class="flex flex-wrap gap-2">
                      <Button
                        :label="'Min: ' + formatCurrency(nextMinBid)"
                        variant="outlined"
                        size="small"
                        rounded
                        class="cursor-pointer"
                        @click="bidAmount = nextMinBid"
                      />
                      <Button
                        :label="'Max: ' + formatCurrency(smartMaxBid)"
                        variant="outlined"
                        size="small"
                        rounded
                        class="cursor-pointer"
                        @click="bidAmount = smartMaxBid"
                      />
                    </div>

                    <!-- Submit Button -->
                    <Button
                      v-if="bidAmount && bidIsValid"
                      label="Submit Bid"
                      icon="pi pi-check"
                      :loading="biddingLoading"
                      :disabled="!bidIsValid"
                      @click="onSubmitBid"
                      class="w-full"
                    />
                  </div>
                </div>
              </div>
            </template>
          </Card>

          <!-- Activity Feed -->
          <Card
            v-if="auctionOverview?.status === 'active' || events.length > 0"
            class="border-2 border-[var(--p-content-border-color)] rounded-xl"
            :pt="{
              header: 'px-4 pt-2',
              body: 'p-2',
            }"
          >
            <template #header>
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <i class="pi pi-megaphone text-sm"></i>
                  <p class="text-sm font-semibold">Activity</p>
                  <Tag v-if="isConnected" class="text-xs" value="LIVE" />
                </div>
                <Button
                  :icon="isFeedExpanded ? 'pi pi-chevron-up' : 'pi pi-chevron-down'"
                  size="small"
                  rounded
                  variant="text"
                  severity="secondary"
                  @click="isFeedExpanded = !isFeedExpanded"
                  :aria-label="isFeedExpanded ? 'Collapse feed' : 'Expand feed'"
                />
              </div>
            </template>
            <template #content>
              <div v-if="sseError" class="ml-2 mb-2 text-sm text-red-400">⚠️ {{ sseError }}</div>
              <div
                v-else-if="!events.length && !eventsLoading"
                class="py-8 text-center text-surface-400"
              >
                <i class="pi pi-inbox text-2xl mb-2"></i>
                <p class="text-xs">No activity yet</p>
              </div>
              <div
                v-else
                ref="feedScrollContainer"
                :class="isFeedExpanded ? 'max-h-96' : 'max-h-32'"
                class="overflow-y-auto transition-all duration-300"
              >
                <ul class="flex list-none flex-col">
                  <li
                    v-for="(e, idx) in events"
                    :key="idx"
                    class="flex items-start gap-2 px-2 py-1 transition-all duration-500"
                    :class="idx === latestEventIndex ? 'bg-primary/20' : ''"
                  >
                    <!-- Time (fixed width, no wrap) -->
                    <span class="text-xs text-surface-400 font-mono flex-shrink-0 pt-0.5">
                      {{ formatTime(e.timestamp || e.created_at) }}
                    </span>

                    <!-- Message content (wraps as one continuous line) -->
                    <div class="flex flex-wrap items-center gap-1 text-sm leading-relaxed">
                      <!-- Participant Avatar (if applicable) -->
                      <PlayerAvatar
                        v-if="formatEventMessage(e).participant"
                        :name="formatEventMessage(e).participant || ''"
                        size="small"
                        custom-class="flex-shrink-0"
                      />

                      <!-- Event Icon (for system events) -->
                      <Avatar
                        v-else
                        shape="circle"
                        class="size-6 text-xs flex-shrink-0"
                        :style="{ backgroundColor: 'var(--p-content-border-color)' }"
                      >
                        <i :class="`pi pi-${formatEventMessage(e).icon} text-xs`"></i>
                      </Avatar>

                      <!-- Participant name -->
                      <span v-if="formatEventMessage(e).participant">{{
                        formatEventMessage(e).participant === selectedParticipant?.name
                          ? 'You'
                          : formatEventMessage(e).participant
                      }}</span>

                      <!-- Message text -->
                      <span class="text-surface-400">{{ formatEventMessage(e).message }}</span>

                      <!-- Team Logo -->
                      <Avatar
                        v-if="formatEventMessage(e).team"
                        :image="formatEventMessage(e).team.logo_url"
                        shape="circle"
                        class="size-6 flex-shrink-0 bg-[var(--p-content-border-color)]"
                      />

                      <!-- Team name -->
                      <span v-if="formatEventMessage(e).team">
                        {{ formatEventMessage(e).team.abbreviation }}
                      </span>
                    </div>
                  </li>
                </ul>
              </div>
            </template>
          </Card>

          <!-- Participants Table -->
          <Card
            v-if="participantTreeNodes.length"
            class="border-2 border-[var(--p-content-border-color)]"
            :pt="{
              header: 'px-4 pt-2',
              body: 'p-2',
            }"
          >
            <template #header>
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <i class="pi pi-user text-sm"></i>
                  <span class="text-sm font-semibold">Participants</span>
                </div>
                <Button
                  :icon="allParticipantsExpanded ? 'pi pi-chevron-up' : 'pi pi-chevron-down'"
                  size="small"
                  rounded
                  variant="text"
                  severity="secondary"
                  @click="toggleAllParticipants"
                  :aria-label="allParticipantsExpanded ? 'Collapse all' : 'Expand all'"
                />
              </div>
            </template>
            <template #content>
              <div class="[&_td]:!border-0 [&_th]:!border-0 max-h-72 overflow-y-auto">
                <TreeTable
                  :value="participantTreeNodes"
                  size="small"
                  v-model:expandedKeys="expandedParticipantKeys"
                  rowHover
                  :indentation="0"
                  :pt="treeTablePt"
                >
                  <!-- Single Column with Flexbox Layout -->
                  <Column headerClass="hidden">
                    <template #body="{ node }">
                      <div class="flex flex-col w-full">
                        <div class="flex items-center w-full">
                          <!-- Avatar Section -->
                          <div class="flex items-center gap-3">
                            <PlayerAvatar
                              v-if="node.data.type === 'participant'"
                              :name="node.data.participant.name"
                              :custom-class="
                                [
                                  'transition-all',
                                  viewMode === 'participant' &&
                                  selectedParticipantId === node.data.participant.id
                                    ? 'ring-2 ring-primary'
                                    : '',
                                ].join(' ')
                              "
                              v-tooltip="node.data.participant.name"
                              @click="
                                (e: MouseEvent) =>
                                  handleParticipantAvatarClick(node.data.participant.id, e)
                              "
                            />
                            <Divider
                              v-if="node.data.type === 'participant'"
                              layout="vertical"
                              class="m-0"
                            />
                            <template v-if="node.data.type === 'participant'">
                              <span v-if="expandedParticipantKeys[node.key]" class="font-medium">
                                {{ node.data.participant.name }}
                              </span>
                              <div v-else class="flex gap-2 justify-start">
                                <!-- Won lots -->
                                <Avatar
                                  v-for="lot in node.data.participant.lots_won"
                                  :key="lot.id"
                                  :image="lot.team?.logo_url"
                                  shape="circle"
                                  class="size-8 bg-[var(--p-content-border-color)]"
                                  v-tooltip.top="lot.team?.name"
                                />
                                <!-- Pending lot (if current winning bidder) -->
                                <Avatar
                                  v-if="
                                    currentLot?.status === 'open' &&
                                    currentLot?.winning_bid?.bidder_name ===
                                      node.data.participant.name
                                  "
                                  :image="currentLot.team?.logo_url"
                                  shape="circle"
                                  class="size-8 bg-[var(--p-content-border-color)] animate-pulse-opacity"
                                  v-tooltip.top="`${currentLot.team?.name} (Pending)`"
                                />
                                <!-- Empty slots (adjusted for pending lot) -->
                                <PlayerAvatar
                                  v-for="index in currentLot?.status === 'open' &&
                                  currentLot?.winning_bid?.bidder_name ===
                                    node.data.participant.name
                                    ? node.data.participant.remainingSlots - 1
                                    : node.data.participant.remainingSlots"
                                  :key="`empty-${node.data.participant.id}-${index}`"
                                  icon="pi pi-plus"
                                  custom-class="opacity-50"
                                />
                              </div>
                            </template>
                            <div v-else class="flex items-center gap-2 pl-8">
                              <Avatar
                                shape="circle"
                                class="size-8 bg-[var(--p-content-border-color)]"
                                :image="node.data.lot.team?.logo_url"
                                v-tooltip.top="node.data.lot.team?.name"
                              />
                              <span class="text-sm">{{
                                node.data.lot.team?.name ?? 'Team TBD'
                              }}</span>
                            </div>
                          </div>

                          <!-- Budget/Amount Section -->
                          <div class="flex-shrink-0 ml-auto">
                            <Tag
                              :value="
                                node.data.type === 'participant'
                                  ? formatCurrency(node.data.participant.budget)
                                  : formatCurrency(node.data.lot.winning_bid?.amount ?? 0)
                              "
                              :severity="node.data.type === 'participant' ? 'primary' : 'secondary'"
                            />
                          </div>
                        </div>
                        <!-- Divider below active participant -->
                        <Divider
                          v-if="
                            viewMode === 'participant' &&
                            node.data?.type === 'participant' &&
                            node.data?.participant?.id === selectedParticipantId
                          "
                          class="mb-0 mt-2"
                        />
                      </div>
                    </template>
                  </Column>
                </TreeTable>
              </div>
            </template>
          </Card>
        </div>

        <!-- Right Column: Team Valuations Table -->
        <div class="lg:col-span-2">
          <Card
            :class="[
              'border-2 rounded-xl overflow-hidden',
              auctionOverview?.status === 'active' &&
              (!currentLot || currentLot.status === 'closed') &&
              anyParticipantCanNominate
                ? 'border-primary'
                : 'border-[var(--p-content-border-color)]',
            ]"
            :pt="{ body: 'p-0', header: 'px-4 py-2' }"
          >
            <template #header>
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <i class="pi pi-chart-bar"></i>
                  <p class="text-sm font-semibold">Auction Valuations</p>
                </div>
                <div class="flex gap-1">
                  <Button
                    label="S"
                    size="small"
                    variant="outlined"
                    :severity="tableScale === 'S' ? 'primary' : 'secondary'"
                    @click="tableScale = 'S'"
                    class="w-8 h-8 p-0"
                  />
                  <Button
                    label="M"
                    size="small"
                    variant="outlined"
                    :severity="tableScale === 'M' ? 'primary' : 'secondary'"
                    @click="tableScale = 'M'"
                    class="w-8 h-8 p-0"
                  />
                  <Button
                    label="L"
                    size="small"
                    variant="outlined"
                    :severity="tableScale === 'L' ? 'primary' : 'secondary'"
                    @click="tableScale = 'L'"
                    class="w-8 h-8 p-0"
                  />
                </div>
              </div>
            </template>
            <template #content>
              <div v-if="valuationError" class="text-sm text-red-500">⚠️ {{ valuationError }}</div>
              <div v-else-if="valuationLoading" class="py-8 text-center text-surface-400">
                <i class="pi pi-spinner pi-spin text-3xl mb-2"></i>
                <p class="text-sm">Loading valuation data...</p>
              </div>
              <div v-else-if="auctionTableData">
                <AuctionTable
                  :auctionTableData="auctionTableData"
                  :density="tableScale"
                  maxHeight="calc(85vh - 4rem)"
                  :showNominateButton="
                    auctionOverview?.status === 'active' &&
                    (!currentLot || currentLot.status === 'closed') &&
                    anyParticipantCanNominate &&
                    !(viewMode === 'participant' && draftedTeams >= requiredTeams)
                  "
                  :nominatableTeamIds="nominatableTeamIds"
                  :closedLotTeamIds="closedLotTeamIds"
                  :currentLotTeamId="currentLot?.team?.id"
                  :currentLotStatus="currentLot?.status"
                  @nominate="handleTeamNomination"
                />
              </div>
              <div v-else class="py-8 text-center text-surface-400">
                <p class="text-sm">No valuation data available</p>
              </div>
            </template>
          </Card>
        </div>
      </div>
    </div>

    <!-- Right Drawer: Auction Settings -->
    <Drawer v-model:visible="showDrawer" position="right">
      <template #header>
        <div class="flex gap-2 flex-wrap">
          <Button
            v-if="auctionOverview?.status === 'not_started'"
            icon="pi pi-pencil"
            label="Edit"
            size="small"
            variant="outlined"
            @click="showEditDialog = true"
          />
          <Button
            v-if="auctionOverview?.status === 'not_started'"
            label="Start Auction"
            icon="pi pi-play-circle"
            size="small"
            variant="outlined"
            :loading="actionSubmitting"
            :disabled="actionSubmitting"
            @click="confirmStartAuction"
          />
          <Button
            v-if="auctionOverview?.status === 'active'"
            label="Complete Auction"
            icon="pi pi-flag"
            size="small"
            variant="outlined"
            :loading="actionSubmitting"
            :disabled="actionSubmitting"
            @click="confirmCompleteAuction"
          />
        </div>
      </template>
      <div class="flex flex-col gap-4">
        <div>
          <p class="font-extrabold text-2xl text-primary">Auction Draft</p>
          <p class="text-xl">{{ auctionOverview?.pool?.name }}</p>
          <p class="text-sm italic">{{ auctionOverview?.season }}</p>
        </div>
        <Message v-if="actionError" severity="error" class="mb-2">{{ actionError }}</Message>
        <Panel>
          <template #header>
            <div class="flex items-center justify-between w-full">
              <p class="font-semibold text-lg text-surface-400">Status</p>
              <Tag class="text-sm" :value="statusDisplay" :severity="statusSeverity" />
            </div>
          </template>
          <div class="flex flex-col gap-2">
            <div class="grid grid-cols-[1fr_auto] gap-x-4 gap-y-2">
              <div class="text-sm text-surface-400">Max Teams</div>
              <div class="text-sm text-right font-semibold">
                {{ auctionOverview?.max_lots_per_participant }}
              </div>
              <div class="text-sm text-surface-400">Min Bid Increment</div>
              <div class="text-sm text-right font-semibold">
                ${{ auctionOverview?.min_bid_increment }}
              </div>
              <div class="text-sm text-surface-400">Starting Budget</div>
              <div class="text-sm text-right font-semibold">
                ${{ auctionOverview?.starting_participant_budget }}
              </div>
              <template v-if="auctionOverview?.started_at">
                <p class="text-sm text-surface-400">Started At</p>
                <div class="text-right font-semibold text-xs">
                  <p>{{ formatUTCDate(auctionOverview.started_at) }}</p>
                  <p>{{ formatUTCTime(auctionOverview.started_at) }}</p>
                </div>
              </template>
              <template v-if="auctionOverview?.completed_at">
                <p class="text-sm text-surface-400">Completed At</p>
                <div class="text-right font-semibold text-xs">
                  <p>{{ formatUTCDate(auctionOverview.completed_at) }}</p>
                  <p>{{ formatUTCTime(auctionOverview.completed_at) }}</p>
                </div>
              </template>
            </div>
          </div>
        </Panel>
        <Panel v-if="currentLot && currentLot.status === 'open'">
          <template #header>
            <p class="font-semibold text-lg text-surface-400">
              <i class="pi pi-box"></i> Current Lot
            </p>
          </template>
          <div class="flex flex-col gap-3">
            <div class="flex items-center gap-3">
              <Avatar
                v-if="currentLot.team?.logo_url"
                :image="currentLot.team.logo_url"
                size="large"
              />
              <div>
                <p class="text-md font-bold">{{ currentLot.team?.name }}</p>
                <p v-if="currentLot.winning_bid" class="text-sm text-surface-400">
                  {{ currentLot.winning_bid.bidder_name }} -
                  {{ formatCurrency(currentLot.winning_bid.amount) }}
                </p>
                <p v-else class="text-sm text-surface-400">No bids yet</p>
              </div>
            </div>
            <Button
              label="Close Lot"
              icon="pi pi-hammer"
              variant="outlined"
              class="w-full"
              :loading="closeLotSubmitting"
              :disabled="closeLotSubmitting"
              @click="confirmCloseLot"
            />
          </div>
        </Panel>
        <Panel>
          <template #header>
            <p class="font-semibold text-lg"><i class="pi pi-user"></i> Participants</p>
          </template>
          <div class="flex flex-col gap-2">
            <ul v-if="participantSummaries?.length" class="flex flex-col gap-2">
              <li v-for="participant in participantSummaries" :key="participant.id">
                <div
                  class="rounded-lg transition-colors"
                  :class="[
                    viewMode === 'participant' && !selectedParticipantId
                      ? 'cursor-pointer hover:bg-primary/10'
                      : '',
                    viewMode === 'participant' && selectedParticipantId === participant.id
                      ? 'bg-primary/20'
                      : '',
                  ]"
                  @click="
                    viewMode === 'participant' && !selectedParticipantId
                      ? handleDrawerParticipantClick(participant.id)
                      : null
                  "
                >
                  <div class="flex justify-between items-center p-1">
                    <div class="flex items-center gap-2">
                      <Button
                        class="size-6"
                        v-if="viewMode === 'participant' && !selectedParticipantId"
                        icon="pi pi-user-plus"
                        variant="outlined"
                        size="small"
                        rounded
                        @click="handleParticipateButtonClick"
                      />
                      <PlayerAvatar v-else :name="participant.name" size="small" />
                      <p class="text-sm font-medium">{{ participant.name }}</p>
                    </div>
                    <Tag
                      class="text-xs"
                      rounded
                      severity="success"
                      :value="formatCurrency(participant.budget)"
                    />
                  </div>
                </div>
              </li>
            </ul>
            <p v-else class="italic">No participants</p>

            <!-- Mode Selection Buttons -->
            <div v-if="auctionOverview?.status === 'active'" class="flex gap-2 mt-2">
              <Button
                v-if="viewMode === 'participant'"
                label="Spectate"
                icon="pi pi-eye"
                class="flex-1"
                variant="outlined"
                severity="secondary"
                size="small"
                @click="viewMode = 'spectator'"
              />
              <Button
                v-if="viewMode === 'spectator'"
                label="Participate"
                icon="pi pi-user"
                class="w-full"
                variant="outlined"
                size="small"
                @click="handleParticipateButtonClick"
              />
              <Button
                v-if="viewMode === 'participant' && selectedParticipantId"
                label="Change"
                icon="pi pi-pencil"
                class="flex-1"
                variant="outlined"
                size="small"
                @click="handleParticipateButtonClick"
              />
            </div>

            <Button
              v-if="auctionOverview?.status === 'not_started'"
              label="Import Pool Rosters"
              icon="pi pi-user-plus"
              class="w-full"
              variant="outlined"
              severity="contrast"
              :loading="importParticipantsSubmitting"
              :disabled="importParticipantsSubmitting || auctionOverview?.status !== 'not_started'"
              @click="handleImportParticipants"
            />
            <Message v-if="importParticipantsError" severity="error">{{
              importParticipantsError
            }}</Message>
            <Message v-if="importParticipantsMessage" severity="success">{{
              importParticipantsMessage
            }}</Message>
          </div>
        </Panel>
        <Panel>
          <template #header>
            <p class="font-semibold text-lg text-surface-400">
              <i class="pi pi-box"></i> Lots (Teams)
            </p>
          </template>
          <div class="flex flex-col gap-2">
            <p v-if="!auctionOverview?.lots.length" class="text-sm italic text-surface-400">
              No lots to nominate.
            </p>
            <ul v-else class="flex flex-col gap-2">
              <li v-for="lot in auctionOverview?.lots" :key="lot.id">
                <div class="flex justify-between items-center">
                  <div class="flex items-center gap-1">
                    <Avatar class="size-7" :image="lot.team?.logo_url" />
                    <p class="text-sm">{{ lot.team?.name }}</p>
                  </div>
                  <Tag class="text-xs" rounded severity="secondary" :value="lot.status" />
                </div>
              </li>
            </ul>
            <p v-if="nominationError" class="text-xs text-red-500">{{ nominationError }}</p>
            <Button
              v-if="auctionOverview?.status === 'not_started'"
              label="Load All NBA Teams"
              icon="pi pi-download"
              class="w-full"
              severity="contrast"
              variant="outlined"
              :loading="importLotsSubmitting"
              :disabled="importLotsSubmitting || auctionOverview?.status !== 'not_started'"
              @click="handleImportLotsFromLeague"
            />
            <Message v-if="importLotsError" severity="error">{{ importLotsError }}</Message>
            <Message v-if="importLotsMessage" severity="success">{{ importLotsMessage }}</Message>
          </div>
        </Panel>
      </div>
    </Drawer>

    <!-- Nomination Dialog -->
    <Dialog
      v-model:visible="showNominationDialog"
      modal
      :draggable="false"
      dismissableMask
      class="container min-w-min max-w-md mx-4"
    >
      <template #header>
        <p class="text-2xl font-semibold">Nominate Team</p>
      </template>
      <div v-if="selectedTeamForNomination" class="flex flex-col gap-4">
        <!-- Team Info -->
        <Card class="border-2 border-primary">
          <template #content>
            <div class="flex items-center gap-3">
              <Avatar
                v-if="selectedTeamForNomination.logo_url"
                :image="selectedTeamForNomination.logo_url"
                shape="circle"
                size="xlarge"
              />
              <div>
                <p class="text-2xl font-bold">{{ selectedTeamForNomination.team }}</p>
                <p class="text-sm text-surface-400">
                  Expected Wins:
                  <span class="font-semibold">{{
                    selectedTeamForNomination.total_expected_wins?.toFixed(1)
                  }}</span>
                </p>
                <p class="text-sm text-surface-400">
                  Auction Value:
                  <span class="font-semibold">{{
                    formatCurrency(selectedTeamForNomination.auction_value)
                  }}</span>
                </p>
              </div>
            </div>
          </template>
        </Card>

        <!-- Participant Selection -->
        <div v-if="viewMode === 'spectator'" class="flex flex-col gap-2">
          <label class="text-sm font-semibold">Nominating Participant</label>
          <Dropdown
            v-model="nominationParticipantId"
            :options="participantOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="Select participant"
            class="w-full"
          />
        </div>
        <div
          v-else-if="viewMode === 'participant' && selectedParticipant"
          class="flex flex-col gap-2"
        >
          <label class="text-sm font-semibold">Nominating As</label>
          <Card class="border-2 border-[var(--p-content-border-color)]">
            <template #content>
              <div class="flex items-center justify-between py-1">
                <div class="flex items-center gap-2">
                  <PlayerAvatar :name="selectedParticipant.name" size="small" />
                  <span class="font-semibold">{{ selectedParticipant.name }}</span>
                </div>
                <Tag severity="success" :value="formatCurrency(selectedParticipant.budget)" />
              </div>
            </template>
          </Card>
        </div>

        <!-- Bid Amount -->
        <div class="flex flex-col gap-2">
          <label class="text-sm font-semibold">Opening Bid</label>
          <InputGroup>
            <InputGroupAddon>
              <Button
                icon="pi pi-minus"
                text
                size="small"
                :disabled="!nominationBidAmount || nominationBidAmount <= minIncrement"
                @click="
                  nominationBidAmount = Math.max(
                    minIncrement,
                    (nominationBidAmount || minIncrement) - minIncrement,
                  )
                "
              />
            </InputGroupAddon>
            <InputNumber
              input-class="text-center"
              v-model="nominationBidAmount"
              :min="minIncrement"
              :step="minIncrement"
              mode="decimal"
              :useGrouping="false"
              placeholder="Enter opening bid"
            />
            <InputGroupAddon>
              <Button
                icon="pi pi-plus"
                text
                size="small"
                @click="nominationBidAmount = (nominationBidAmount || 0) + minIncrement"
              />
            </InputGroupAddon>
          </InputGroup>
          <p class="text-xs text-surface-400">
            Minimum opening bid: {{ formatCurrency(minIncrement) }}
          </p>
        </div>

        <!-- Error Message -->
        <Message v-if="nominationError" severity="error">{{ nominationError }}</Message>

        <!-- Action Buttons -->
        <div class="flex gap-2 justify-end">
          <Button
            label="Cancel"
            severity="secondary"
            variant="outlined"
            @click="showNominationDialog = false"
          />
          <Button
            label="Nominate"
            icon="pi pi-check"
            :loading="nominationSubmitting"
            :disabled="
              !nominationParticipantId || !nominationBidAmount || nominationBidAmount < minIncrement
            "
            @click="submitNomination"
          />
        </div>
      </div>
    </Dialog>

    <!-- Edit Auction Dialog -->
    <Dialog
      v-model:visible="showEditDialog"
      modal
      :draggable="false"
      dismissableMask
      class="container min-w-min max-w-md mx-4"
    >
      <template #header>
        <p class="text-2xl font-semibold">Edit Auction</p>
      </template>
      <AuctionForm
        mode="edit"
        :initial="{
          status: auctionOverview?.status as AuctionStatus,
          max_lots_per_participant: auctionOverview?.max_lots_per_participant,
          min_bid_increment: Number(auctionOverview?.min_bid_increment),
          starting_participant_budget: Number(auctionOverview?.starting_participant_budget),
        }"
        :auctionStatus="auctionOverview?.status as AuctionStatus"
        :submitting="editSubmitting"
        :error="editError"
        @submit="handleAuctionEditSubmit"
      />
    </Dialog>
  </main>
</template>

<style scoped>
/* Fade transition for rotating title */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.75s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@keyframes pulse-opacity {
  0%,
  100% {
    opacity: 0.5;
  }
  50% {
    background-color: var(--p-primary-700);
    opacity: 1;
  }
}

.animate-pulse-opacity {
  animation: pulse-opacity 1.5s ease-in-out infinite;
}

/* Custom scrollbar styling - transparent track, visible thumb */
:deep(::-webkit-scrollbar) {
  width: 10px;
  height: 10px;
}

:deep(::-webkit-scrollbar-track) {
  background: transparent;
}

:deep(::-webkit-scrollbar-thumb) {
  background: var(--p-surface-600);
  border-radius: 5px;
}

:deep(::-webkit-scrollbar-thumb:hover) {
  background: var(--p-surface-600);
}

/* Firefox scrollbar styling */
:deep(*) {
  scrollbar-width: thin;
  scrollbar-color: var(--p-surface-600) transparent;
}
</style>
