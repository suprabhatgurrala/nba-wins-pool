<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import { useAuctionOverview } from '@/composables/useAuctionOverview'
import { useAuctionEvents } from '@/composables/useAuctionEvents'
import { useAuctionBidding } from '@/composables/useAuctionBidding'
import Button from 'primevue/button'
import Drawer from 'primevue/drawer'
import Dialog from 'primevue/dialog'
import Panel from 'primevue/panel'
import Tag from 'primevue/tag'
import Card from 'primevue/card'
import SelectButton from 'primevue/selectbutton'
import Dropdown from 'primevue/dropdown'
import Message from 'primevue/message'
import InputNumber from 'primevue/inputnumber'
import InputGroup from 'primevue/inputgroup'
import InputGroupAddon from 'primevue/inputgroupaddon'
import ScrollPanel from 'primevue/scrollpanel'
import Avatar from 'primevue/avatar'
import AuctionForm from '@/components/pool/AuctionForm.vue'
import TopBanner from '@/components/common/TopBanner.vue'
import { useAuctions } from '@/composables/useAuctions'
import type {
  AuctionCreate,
  AuctionUpdate,
  AuctionStatus,
  AuctionOverviewParticipant,
} from '@/types/pool'
import LiveDot from '@/components/common/LiveDot.vue'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const confirm = useConfirm()
const auctionId = route.params.auctionId as string

const {
  auctionOverview: auctionOverview,
  error: auctionOverviewError,
  loading: auctionOverviewLoading,
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
const nominationSuccess = ref<string | null>(null)

// Auctions API for status updates
const { updateAuction } = useAuctions()

// Format auction status for display
const statusDisplay = computed(() => {
  const s = String(auctionOverview.value?.status || '')
  // Convert snake_case to Title Case
  return s
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
})

// Tag severity for auction status
const statusSeverity = computed(() => {
  const s = String(auctionOverview.value?.status || '')
  if (s === 'active') return 'success'
  if (s === 'completed') return 'contrast'
  return 'secondary'
})

const avatarPalette = ['#2563eb', '#7c3aed', '#db2777', '#ea580c', '#16a34a', '#0ea5e9', '#f97316', '#9333ea']

function hashString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i)
    hash |= 0
  }
  return Math.abs(hash)
}

function getInitials(name: string): string {
  if (!name) return '??'
  const segments = name.trim().split(/\s+/).filter(Boolean)
  if (!segments.length) return '??'
  const [first, second] = segments
  const initials = `${first?.[0] ?? ''}${second?.[0] ?? first?.[1] ?? ''}`
  return initials.toUpperCase().slice(0, 2)
}

function getAvatarColor(name: string): string {
  if (!name) return '#1f2937'
  const index = hashString(name) % avatarPalette.length
  return avatarPalette[index]
}

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

async function nominateLot(lotId: string) {
  nominationError.value = null
  nominationSuccess.value = null
  if (!auctionOverview.value) {
    nominationError.value = 'Auction data is unavailable.'
    return
  }
  if (auctionOverview.value.status !== 'active') {
    nominationError.value = 'Lots can only be nominated while the auction is active.'
    return
  }
  if (!nominationParticipantId.value) {
    nominationError.value = 'Select a participant to nominate this lot.'
    return
  }
  const openingBid = Math.max(1, Math.floor(Number(auctionOverview.value.min_bid_increment ?? 1)))
  nominationSubmitting.value = true
  try {
    await submitBid(lotId, nominationParticipantId.value, openingBid)
    nominationSuccess.value = 'Lot nominated with opening bid.'
    await fetchAuctionOverview()
  } catch (e: any) {
    nominationError.value = e?.message || 'Failed to nominate lot'
  } finally {
    nominationSubmitting.value = false
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
const bidError = ref<string | null>(null)
const bidSuccess = ref<string | null>(null)

const { submitBid, loading: biddingLoading, error: biddingError } = useAuctionBidding()
const { connect, disconnect, isConnected, latestEvent, events, error: sseError, loading: eventsLoading, fetchHistoricalEvents } = useAuctionEvents(auctionId)

const participants = computed(() => auctionOverview.value?.participants ?? [])
const readyLots = computed(() => auctionOverview.value?.lots.filter((lot) => lot.status === 'ready') ?? [])
const participantOptions = computed(() =>
  participants.value.map((p) => ({
    label: `${p.name} · ${formatCurrency(p.budget)}`,
    value: p.id,
  })),
)
const viewModeOptions = [
  { label: 'Spectator', value: 'spectator', icon: 'pi pi-eye' },
  { label: 'Participant', value: 'participant', icon: 'pi pi-user' },
]
// Selected participant helper (declared early for watchers)
const selectedParticipant = computed(
  () => participants.value.find((p) => p.id === selectedParticipantId.value) || null,
)
const currentLot = computed(() => auctionOverview.value?.current_lot ?? null)
const minIncrement = computed(() => {
  // Whole-dollar increments only
  const v = auctionOverview.value?.min_bid_increment
  const n = Math.floor(Number(v))
  return Number.isFinite(n) && n >= 1 ? n : 1
})
const nextMinBid = computed(() => {
  // Opening bid is $1, then last winning bid + min increment (integers)
  const curr = Number(currentLot.value?.winning_bid?.amount ?? 0)
  return curr > 0 ? Math.floor(curr + minIncrement.value) : 1
})
const requiredTeams = computed(() => auctionOverview.value?.max_lots_per_participant ?? 0)
type ParticipantSummary = AuctionOverviewParticipant & {
  initials: string
  avatarColor: string
  remainingSlots: number
}
const participantSummaries = computed<ParticipantSummary[]>(() =>
  participants.value.map((participant) => {
    const lots = participant.lots_won ?? []
    return {
      ...participant,
      lots_won: lots,
      initials: getInitials(participant.name),
      avatarColor: getAvatarColor(participant.name),
      remainingSlots: Math.max(requiredTeams.value - lots.length, 0),
    }
  }),
)
const draftedTeams = computed(() => selectedParticipant.value?.lots_won.length ?? 0)
const remainingToDraftAfterWin = computed(() =>
  Math.max(requiredTeams.value - draftedTeams.value - 1, 0),
)
const remainingBudget = computed(() =>
  selectedParticipant.value ? parseFloat(selectedParticipant.value.budget) : 0,
)
const smartMaxBid = computed(() => {
  // Enforce smart max: budget - ($1 × remaining teams to draft after this win)
  const budget = Math.floor(Number(remainingBudget.value) || 0)
  const reserve = Math.max(0, Number(remainingToDraftAfterWin.value) || 0) * 1
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
  const base = (
    viewMode.value === 'participant' &&
    !!selectedParticipant.value &&
    !!currentLot.value &&
    draftedTeams.value < requiredTeams.value &&
    String(currentLot.value.status || '').toLowerCase() !== 'closed'
  )
  // Must also be able to meet next minimum
  return base && nextMinBid.value <= smartMaxBid.value
})
const bidIsValid = computed(() => {
  if (!canBid.value || bidAmount.value == null) return false
  const amt = Number(bidAmount.value)
  return Number.isInteger(amt) && amt >= nextMinBid.value && amt <= smartMaxBid.value
})

function formatCurrency(val: number | string | null | undefined) {
  const num = typeof val === 'string' ? parseFloat(val) : typeof val === 'number' ? val : 0
  if (!isFinite(num)) return '$0'
  return `$${num.toFixed(0)}`
}

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
        message: `won for ${formatCurrency(payload.lot?.winning_bid?.amount)}`,
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
  if (!timestamp) return ''
  try {
    const date = new Date(timestamp)
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return timestamp.slice(11, 19) || ''
  }
}

onMounted(async () => {
  await fetchAuctionOverview()
  // Fetch historical events first
  await fetchHistoricalEvents()
  // Only connect to live events if auction is active
  if (auctionOverview.value?.status === 'active') {
    connect()
  }
})
onUnmounted(() => {
  disconnect()
})
watch(auctionOverviewError, (err) => {
  if (err && String(err).includes('HTTP 404')) {
    router.replace({ name: 'not-found' })
  }
})
watch(latestEvent, () => {
  // On any live event, refresh the overview to stay in sync
  fetchAuctionOverview()
})

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
  }
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

// Function to handle participant button click
const handleParticipantModeClick = () => {
  // If already in participant mode with a selection, clear it to allow re-selection
  if (viewMode.value === 'participant' && selectedParticipantId.value) {
    selectedParticipantId.value = null
  }
}
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
    if (!nominationParticipantId.value || !list.find((p) => p.id === nominationParticipantId.value)) {
      nominationParticipantId.value = list[0].id
    }
  },
  { immediate: true },
)
watch(showDrawer, (open) => {
  if (!open) {
    importParticipantsError.value = null
    importParticipantsMessage.value = null
    importLotsError.value = null
    importLotsMessage.value = null
    nominationError.value = null
    nominationSuccess.value = null
    actionError.value = null
  }
})

const onSubmitBid = async () => {
  bidError.value = null
  bidSuccess.value = null
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
      <Button icon="pi pi-arrow-left" variant="outlined" severity="secondary" @click="router.push({ name: 'pool-season', params: { slug: auctionOverview?.pool.id, season: auctionOverview?.season } })" aria-label="Back" />
      <p class="text-xl font-bold">🏀 NBA Wins Pool 🏆</p>
      <Button icon="pi pi-bars" variant="outlined" severity="secondary" @click="showDrawer = true" aria-label="Menu" />
    </div>
  </header>
  
  <main>
    <div class="flex flex-col items-center my-2">
      <div class="flex items-center gap-4">
        <p class="text-4xl font-extrabold text-center text-primary">Auction Draft</p>
        <!-- <LiveDot v-if="auctionOverview?.status === 'active'" color="var(--p-red-500)" :size="16" /> -->
      </div>
      <p class="text-xl font-medium text-center">{{ auctionOverview?.pool.name }}</p>
      <p class="text-xl font-medium text-surface-400 italic text-center">{{ auctionOverview?.season }}</p>
    </div>

    <div class="px-4 max-w-5xl mx-auto">
      <!-- Current Lot Card -->
      <Card v-if="currentLot" class="mb-4 max-w-md mx-auto border-2 border-primary">
        <template #content>
          <div class="flex justify-between pb-2">
            <div class="flex items-center gap-1">
              <Avatar
                v-if="currentLot.team?.logo_url"
                :image="currentLot.team.logo_url"
                shape="circle"
                size="xlarge"
              />
              <div>
                <p class="text-2xl font-bold">{{ currentLot.team?.name }}</p>
                <!-- current winning bidder -->
                <p v-if="currentLot.winning_bid" class="text-sm text-surface-400">Bidder: {{ currentLot.winning_bid.bidder_name }}</p>
              </div>
            </div>
            <div class="flex items-center">
              <div class="text-right">
                <div v-if="currentLot.winning_bid">
                  <div class="text-3xl font-bold text-primary">{{ formatCurrency(currentLot.winning_bid.amount) }}</div>
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
            <div v-if="viewMode === 'participant' && selectedParticipant">
              <!-- <div class="text-sm font-semibold mb-2">Place Your Bid</div> -->
              
              <div v-if="!canBid" class="text-sm text-surface-500 italic">
                {{ nextMinBid > smartMaxBid ? 'Insufficient funds to bid on this lot' : 'You cannot bid at this time' }}
              </div>
              
              <div v-else class="flex flex-col gap-3 items-center">
                <!-- Bid Input -->
                <InputGroup>
                  <InputGroupAddon>
                    <Button
                      icon="pi pi-minus"
                      text
                      size="small"
                      :disabled="!bidAmount || bidAmount <= nextMinBid"
                      @click="bidAmount = Math.max(nextMinBid, (bidAmount || nextMinBid) - minIncrement)"
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
                  @click="onSubmitBid"
                  class="w-full"
                />

              </div>
            </div>
          </div>
        </template>
      </Card>
      <SelectButton
        v-model="viewMode"
        :options="viewModeOptions"
        optionLabel="label"
        optionValue="value"
        :allowEmpty="false"
        class="mb-4"
      >
        <template #option="slotProps">
          <div @click="() => {
            if (slotProps.option.value === 'participant' && viewMode === 'participant' && selectedParticipantId) {
              handleParticipantModeClick()
            }
          }">
            <i :class="[slotProps.option.icon, 'mr-2']" />
            <span>{{ slotProps.option.label }}</span>
          </div>
        </template>
      </SelectButton>
      <div v-if="participantSummaries.length" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card
          v-for="participant in participantSummaries"
          :key="participant.id"
          :class="[
            'border-2',
            viewMode === 'participant' && !selectedParticipantId ? 'cursor-pointer hover:opacity-75' : '',
            viewMode === 'participant' && !selectedParticipantId ? 'border-primary' : 'border-[var(--p-content-border-color)]',
            viewMode === 'participant' && selectedParticipantId === participant.id ? 'border-primary' : 'border-[var(--p-content-border-color)]'
          ]"
          @click="viewMode === 'participant' && !selectedParticipantId ? (() => { selectedParticipantId = participant.id })() : null"
        >
          <template #content>
            <div class="flex items-start gap-3">
              <div class="flex flex-col items-center gap-1">
                <Avatar
                  shape="circle"
                  :label="participant.initials"
                  class="font-bold"
                  :style="{ backgroundColor: participant.avatarColor }"
                />
                <div class="text-xs font-medium text-center text-surface-400">
                  {{ participant.name }}
                </div>
              </div>
              <div class="flex-1 flex flex-wrap items-center gap-2">
                <div v-for="lot in participant.lots_won" :key="lot.id" class="flex flex-col items-center gap-0.5">
                  <Avatar
                    shape="circle"
                    :image="lot.team?.logo_url"
                    :label="lot.team?.abbreviation || '??'"
                  />
                  <div class="text-[10px] font-medium text-center">
                    {{ lot.team?.abbreviation }} {{ formatCurrency(lot.winning_bid?.amount) }}
                  </div>
                </div>
                <Avatar
                  v-for="index in participant.remainingSlots"
                  :key="`empty-${participant.id}-${index}`"
                  shape="circle"
                  size="normal"
                  label="+"
                  class="border border-dashed opacity-50"
                />
              </div>
              <Tag :value="formatCurrency(participant.budget)" severity="primary" class="flex-shrink-0" />
            </div>
          </template>
        </Card>
      </div>
      <div v-else class="py-8 text-center">
        <p class="text-lg">No participants yet.</p>
      </div>
    </div>




    <div class="px-4 max-w-md mx-auto pt-4 min-h-min">
      <Card>
        <template #title>
          <div class="flex items-center justify-between">
            <div class="flex w-full items-center justify-between">
              <p>Feed</p>
              <Tag v-if="isConnected" class="text-xs" value="LIVE" severity="success" />
            </div>
            <span v-if="eventsLoading" class="text-xs text-surface-400">Loading...</span>
          </div>
        </template>
        <template #content>
          <div v-if="sseError" class="mb-2 text-sm text-red-500">⚠️ {{ sseError }}</div>
          <div v-if="!events.length && !eventsLoading" class="py-8 text-center text-surface-400">
            <i class="pi pi-inbox text-3xl mb-2"></i>
            <p class="text-sm">No activity yet</p>
          </div>
          <ScrollPanel v-else class="min-h-64 max-h-96">
            <ul class="flex list-none flex-col gap-2">
              <li
                v-for="(e, idx) in events"
                :key="idx"
                class="flex items-center gap-1 rounded-lg border-2 border-transparent hover:opacity-75"
              >
                <!-- Time -->
                <span class="text-xs text-surface-400 font-mono pr-2">
                  {{ formatTime(e.timestamp || e.created_at) }}
                </span>
                
                <!-- Participant Avatar (if applicable) -->
                <Avatar
                  v-if="formatEventMessage(e).participant"
                  :label="getInitials(formatEventMessage(e).participant || '')"
                  shape="circle"
                  class="size-6 font-semibold text-xs"
                  :style="{ backgroundColor: getAvatarColor(formatEventMessage(e).participant || '') }"
                />
                
                <!-- Event Icon (for system events) -->
                <Avatar v-else shape="circle" class="size-6 text-xs" :style="{ backgroundColor: 'var(--p-content-border-color)' }">
                  <i :class="`pi pi-${formatEventMessage(e).icon} text-xs`"></i>
                </Avatar>
                
                <!-- Message -->
                <span v-if="formatEventMessage(e).participant" class="text-sm">{{ formatEventMessage(e).participant }}</span>
                <span class="text-sm text-surface-400">{{ formatEventMessage(e).message }}</span>
                
                <!-- Team Logo & Name (if applicable) -->
                <Avatar
                  v-if="formatEventMessage(e).team"
                  :image="formatEventMessage(e).team.logo_url"
                  shape="circle"
                  class="size-6"
                />
                <span v-if="formatEventMessage(e).team" class="text-sm">
                  {{ formatEventMessage(e).team.abbreviation }}
                </span>
              </li>
            </ul>
          </ScrollPanel>
        </template>
      </Card>
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
          <p class="text-xl text-surface-400">{{ auctionOverview?.pool?.name }}</p>
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
              <div class="text-sm text-right font-semibold">{{ auctionOverview?.max_lots_per_participant }}</div>
              <div class="text-sm text-surface-400">Min Bid Increment</div>
              <div class="text-sm text-right font-semibold">${{ auctionOverview?.min_bid_increment }}</div>
              <div class="text-sm text-surface-400">Starting Budget</div>
              <div class="text-sm text-right font-semibold">${{ auctionOverview?.starting_participant_budget }}</div>
              <template v-if="auctionOverview?.started_at">
                <p class="text-sm text-surface-400">Started At</p>
                <div class="text-right font-semibold text-xs">
                  <p>{{ new Date(auctionOverview.started_at).toLocaleDateString() }}</p>
                  <p>{{ new Date(auctionOverview.started_at).toLocaleTimeString() }}</p>
                </div>
              </template>
              <template v-if="auctionOverview?.completed_at">
                <p class="text-sm text-surface-400">Completed At</p>
                <div class="text-right font-semibold text-xs">
                  <p>{{ new Date(auctionOverview.completed_at).toLocaleDateString() }}</p>
                  <p>{{ new Date(auctionOverview.completed_at).toLocaleTimeString() }}</p>
                </div>
              </template>
            </div>
          </div>
        </Panel>
        <Panel>
          <template #header>
            <p class="font-semibold text-lg text-surface-400"><i class="pi pi-user"></i> Participants</p>
          </template>
          <div class="flex flex-col gap-2">
            <ul v-if="participantSummaries?.length" class="flex flex-col gap-2">
              <li v-for="participant in participantSummaries" :key="participant.id">
                <div class="rounded-lg">
                    <div class="flex justify-between items-center">
                      <div class="flex items-center gap-1">
                        <Avatar class="size-6 text-xs font-semibold" :label="participant.initials" shape="circle" :style="{ backgroundColor: participant.avatarColor }" />
                        <p class="text-sm">{{ participant.name }}</p>
                      </div>
                      <Tag class="text-xs" rounded severity="success" :value="formatCurrency(participant.budget)" />
                    </div>
                </div>
              </li>
            </ul>
            <p v-else class="italic">No participants</p>
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
            <Message v-if="importParticipantsError" severity="error">{{ importParticipantsError }}</Message>
            <Message v-if="importParticipantsMessage" severity="success">{{ importParticipantsMessage }}</Message>
          </div>
        </Panel>
        <Panel>
          <template #header>
            <p class="font-semibold text-lg text-surface-400"><i class="pi pi-box"></i> Lots (Teams)</p>
          </template> 
          <div class="flex flex-col gap-2">
            <p v-if="!auctionOverview?.lots.length" class="text-sm italic text-surface-400">No lots to nominate.</p>
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
            <p v-if="nominationSuccess" class="text-xs text-emerald-500">{{ nominationSuccess }}</p>
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

    <!-- Edit Auction Dialog -->
    <Dialog v-model:visible="showEditDialog" modal :draggable="false" dismissableMask class="container min-w-min max-w-md mx-4">
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
        :auctionStatus="(auctionOverview?.status as AuctionStatus)"
        :submitting="editSubmitting"
        :error="editError"
        @submit="handleAuctionEditSubmit"
      />
    </Dialog>
  </main>
</template>
