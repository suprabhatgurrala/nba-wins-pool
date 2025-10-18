<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useConfirm } from 'primevue/useconfirm'
import Drawer from 'primevue/drawer'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import { RouterLink } from 'vue-router'
import Panel from 'primevue/panel'
import Card from 'primevue/card'
import LeaderboardTable from '@/components/pool/LeaderboardTable.vue'
import WinsRaceChart from '@/components/pool/WinsRaceChart.vue'
import PlayerAvatar from '@/components/common/PlayerAvatar.vue'
import { useLeaderboard } from '@/composables/useLeaderboard'
import TopBanner from '@/components/common/TopBanner.vue'
import { useWinsRaceData } from '@/composables/useWinsRaceData'
import { useAuctions } from '@/composables/useAuctions'
import { usePoolSeasonOverview } from '@/composables/usePoolSeasonOverview'
import { usePools } from '@/composables/usePools'
import { usePool } from '@/composables/usePool'
import { useRosters } from '@/composables/useRosters'
import { usePoolSeasons } from '@/composables/usePoolSeasons'
import PoolForm from '@/components/pool/PoolForm.vue'
import AuctionForm from '@/components/pool/AuctionForm.vue'
import SeasonForm, { type SeasonFormData } from '@/components/pool/SeasonForm.vue'
import { getCurrentSeason } from '@/utils/season'
import type { AuctionCreate, AuctionUpdate, Roster, PoolUpdate } from '@/types/pool'
import { isUuid } from '@/utils/ids'
import Message from 'primevue/message'

const route = useRoute()
const router = useRouter()
const confirm = useConfirm()

const {
  roster,
  team,
  error: leaderboardError,
  loading: leaderboardLoading,
  fetchLeaderboard,
} = useLeaderboard()

const {
  winsRaceData,
  error: chartError,
  loading: chartLoading,
  fetchWinsRaceData,
} = useWinsRaceData()

// Resolved canonical slug for this view (may be set after resolving a UUID)
const slugRef = ref<string | null>(null)
// Pool state and fetchers
const { pool, error: poolError, loading: poolLoading, fetchPoolById, fetchPoolBySlug } = usePool()
const { auctions, fetchAuctions, createAuction } = useAuctions()

// Season overview (DB-backed) for the selected season
const {
  overview,
  error: overviewError,
  loading: overviewLoading,
  fetchPoolSeasonOverview,
} = usePoolSeasonOverview()
const {
  rosters,
  loading: rosterLoading,
  error: rosterError,
  fetchRosters,
  createRoster,
  updateRoster,
  deleteRoster,
} = useRosters()
const season = computed(() => (route.params.season as string) || getCurrentSeason())

const currentSeasonAuction = computed(
  () => auctions.value.find((a) => a.season === season.value) ?? null,
)
const activeAuction = computed(() =>
  currentSeasonAuction.value?.status === 'active' ? currentSeasonAuction.value : null,
)

// Drawer & modals
const showDrawer = ref(false)
const showEditDialog = ref(false)
const editSubmitting = ref(false)
const editError = ref<string | null>(null)
const showCreateAuctionDialog = ref(false)
const createSubmitting = ref(false)
const createError = ref<string | null>(null)
const showCreateSeasonDialog = ref(false)
const createSeasonSubmitting = ref(false)
const createSeasonError = ref<string | null>(null)
const showRosterDialog = ref(false)
const rosterActionError = ref<string | null>(null)
const rosterActionMessage = ref<string | null>(null)
const showRosterFormDialog = ref(false)
const rosterFormMode = ref<'create' | 'edit'>('create')
const rosterToEdit = ref<Roster | null>(null)
const rosterFormName = ref('')
const rosterFormSubmitting = ref(false)
const rosterFormError = ref<string | null>(null)

// Table density state controls internal table scaling (default to 'M' on all devices)
const tableScale = ref<'S' | 'M' | 'L'>('M')
const importAuctionSubmitting = ref(false)
const importAuctionError = ref<string | null>(null)
const importAuctionMessage = ref<string | null>(null)

function resetRosterFormState() {
  showRosterFormDialog.value = false
  rosterFormMode.value = 'create'
  rosterToEdit.value = null
  rosterFormName.value = ''
  rosterFormError.value = null
  rosterFormSubmitting.value = false
}

function resetRosterDialogState() {
  rosterActionError.value = null
  rosterActionMessage.value = null
  resetRosterFormState()
}

// Pools API for update/delete
const { updatePool, deletePool } = usePools()
const { updatePoolSeason, createPoolSeason, fetchPoolSeasons } = usePoolSeasons()

// Pool seasons list
const poolSeasons = ref<Array<{ id: string; season: string; rules: string | null }>>([])
const seasonsLoading = ref(false)

async function handleEditSubmit(payload: { pool: PoolUpdate; rules?: string | null }) {
  if (!pool.value?.id) return
  editSubmitting.value = true
  editError.value = null
  try {
    // Update pool (name, description)
    await updatePool(pool.value.id, payload.pool)

    // Update or create pool season rules if provided
    if (payload.rules !== undefined) {
      try {
        await updatePoolSeason(pool.value.id, season.value, { rules: payload.rules })
      } catch (e: any) {
        // If pool season doesn't exist (404), create it
        const errorMsg = e?.message?.toLowerCase() || ''
        if (errorMsg.includes('404') || errorMsg.includes('not found')) {
          await createPoolSeason(pool.value.id, {
            pool_id: pool.value.id,
            season: season.value,
            rules: payload.rules,
          })
        } else {
          throw e
        }
      }
    }

    await resolvePoolAndSlug()
    await fetchPoolSeasonOverview({ poolId: pool.value.id, season: season.value as string })
    showEditDialog.value = false
  } catch (e: any) {
    editError.value = e?.message || 'Failed to update pool'
  } finally {
    editSubmitting.value = false
  }
}

async function handleCreateAuction(payload: AuctionCreate | AuctionUpdate) {
  if (!pool.value?.id) return
  createSubmitting.value = true
  createError.value = null
  try {
    const p = payload as AuctionCreate
    if (!p.pool_id) p.pool_id = pool.value.id
    await createAuction(p)
    await fetchAuctions({ pool_id: pool.value.id })
    showCreateAuctionDialog.value = false
  } catch (e: any) {
    createError.value = e?.message || 'Failed to create auction'
  } finally {
    createSubmitting.value = false
  }
}

async function handleCreateSeason(payload: SeasonFormData) {
  if (!pool.value?.id) return
  createSeasonSubmitting.value = true
  createSeasonError.value = null
  try {
    await createPoolSeason(pool.value.id, {
      pool_id: pool.value.id,
      season: payload.season,
      rules: payload.rules || null,
    })
    // Reload pool seasons list
    await loadPoolSeasons(pool.value.id)
    // Navigate to the newly created season
    await router.push({
      name: 'pool-season',
      params: { slug: pool.value.slug, season: payload.season },
    })
    showCreateSeasonDialog.value = false
  } catch (e: any) {
    createSeasonError.value = e?.message || 'Failed to create season'
  } finally {
    createSeasonSubmitting.value = false
  }
}

async function handleImportAuctionRosters() {
  if (!currentSeasonAuction.value?.id) return
  importAuctionSubmitting.value = true
  importAuctionError.value = null
  importAuctionMessage.value = null
  try {
    const res = await fetch('/api/roster-slots/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: 'auction',
        source_id: currentSeasonAuction.value.id,
      }),
    })
    if (!res.ok) {
      let message = `Failed to import rosters (HTTP ${res.status})`
      try {
        const data = await res.json()
        message = data?.detail || message
      } catch (_) {}
      throw new Error(message)
    }
    const imported = await res.json()
    if (Array.isArray(imported)) {
      const count = imported.length
      importAuctionMessage.value = count
        ? `Imported ${count} roster slot${count === 1 ? '' : 's'} from auction.`
        : 'No new roster slots were added.'
    } else {
      importAuctionMessage.value = 'Imported roster slots from auction.'
    }
    // Refresh overview to show updated rosters
    if (pool.value?.id) {
      await fetchPoolSeasonOverview({ poolId: pool.value.id, season: season.value })
      await fetchRosters({ pool_id: pool.value.id, season: season.value })
      // Refresh leaderboard data as it depends on roster slots
      await fetchLeaderboard(pool.value.id, season.value)
    }
  } catch (e: any) {
    importAuctionError.value = e?.message || 'Failed to import rosters from auction'
  } finally {
    importAuctionSubmitting.value = false
  }
}

async function openRosterDialog() {
  rosterActionError.value = null
  rosterActionMessage.value = null
  showRosterDialog.value = true
  if (pool.value?.id) {
    await fetchRosters({ pool_id: pool.value.id, season: season.value })
  }
}

function openCreateRosterDialog() {
  rosterFormMode.value = 'create'
  rosterToEdit.value = null
  rosterFormName.value = ''
  rosterFormError.value = null
  showRosterFormDialog.value = true
}

function openRosterEditDialog(roster: Roster) {
  rosterFormMode.value = 'edit'
  rosterToEdit.value = roster
  rosterFormName.value = roster.name
  rosterFormError.value = null
  showRosterFormDialog.value = true
}

async function handleRosterFormSubmit() {
  if (!pool.value?.id) return
  const trimmedName = rosterFormName.value.trim()
  if (!trimmedName) {
    rosterFormError.value = 'Please enter a roster name'
    return
  }
  rosterFormSubmitting.value = true
  rosterFormError.value = null
  rosterActionError.value = null
  rosterActionMessage.value = null
  try {
    if (rosterFormMode.value === 'create') {
      await createRoster({ name: trimmedName, pool_id: pool.value.id, season: season.value })
      rosterActionMessage.value = 'Roster added successfully'
    } else if (rosterFormMode.value === 'edit' && rosterToEdit.value) {
      await updateRoster(rosterToEdit.value.id, { name: trimmedName })
      rosterActionMessage.value = 'Roster updated'
    }
    showRosterFormDialog.value = false
    await fetchRosters({ pool_id: pool.value.id, season: season.value })
    await fetchPoolSeasonOverview({ poolId: pool.value.id, season: season.value })
  } catch (e: any) {
    rosterFormError.value = e?.message || 'Failed to save roster'
  } finally {
    rosterFormSubmitting.value = false
  }
}

function confirmDeleteRoster() {
  if (!rosterToEdit.value) return
  confirm.require({
    message: `Are you sure you want to delete ${rosterToEdit.value.name}? This action cannot be undone.`,
    header: 'Delete Roster',
    rejectLabel: 'Cancel',
    acceptLabel: 'Delete',
    icon: 'pi pi-trash',
    accept: async () => {
      if (!pool.value?.id || !rosterToEdit.value) return
      rosterFormError.value = null
      rosterActionError.value = null
      rosterActionMessage.value = null
      try {
        await deleteRoster(rosterToEdit.value.id)
        rosterActionMessage.value = 'Roster removed'
        showRosterFormDialog.value = false
        await fetchRosters({ pool_id: pool.value.id, season: season.value })
        await fetchPoolSeasonOverview({ poolId: pool.value.id, season: season.value })
      } catch (e: any) {
        rosterActionError.value = e?.message || 'Failed to delete roster'
      } finally {
        rosterToEdit.value = null
      }
    },
  })
}

async function resolvePoolAndSlug() {
  poolLoading.value = true
  poolError.value = null
  try {
    const idOrSlug = (route.params.slug as string) || (route.params.id as string) || ''
    if (!idOrSlug) throw new Error('Missing pool identifier')
    if (isUuid(idOrSlug)) {
      await fetchPoolById(idOrSlug)
    } else {
      await fetchPoolBySlug(idOrSlug)
    }
    const p = pool.value
    if (!p) throw new Error('Failed to resolve pool')
    slugRef.value = p.slug

    // If no season in URL, redirect to most recent season
    if (!route.params.season) {
      try {
        const seasons = await fetchPoolSeasons(p.id)
        if (seasons && seasons.length > 0) {
          // Seasons are returned in descending order, so first one is most recent
          const mostRecentSeason = seasons[0].season
          await router.replace({
            name: 'pool-season',
            params: { slug: p.slug, season: mostRecentSeason },
          })
          return
        }
      } catch (e) {
        console.warn('Could not fetch pool seasons, using current season:', e)
      }
    }

    // Replace visible URL to canonical slug route
    if ((route.params.slug as string) !== p.slug) {
      if (route.params.season) {
        await router.replace({
          name: 'pool-season',
          params: { slug: p.slug, season: route.params.season },
        })
      } else {
        await router.replace({ name: 'pool', params: { slug: p.slug } })
      }
    }
  } catch (e: any) {
    console.error('Error resolving pool:', e)
    poolError.value = e?.message || 'Failed to resolve pool'
  } finally {
    poolLoading.value = false
  }
}

// Redirect to NotFound when backend signals missing resources
watch(poolError, (err) => {
  if (err && String(err).includes('HTTP 404')) {
    router.replace({ name: 'not-found' })
  }
})

watch(overviewError, (err) => {
  if (err && String(err).includes('HTTP 404')) {
    router.replace({ name: 'not-found' })
  }
})

onMounted(() => {
  resolvePoolAndSlug()
})

watch(
  [() => pool.value?.id, () => season.value],
  ([id, s]) => {
    if (id) {
      fetchLeaderboard(id, s as string)
      fetchPoolSeasonOverview({ poolId: id, season: s as string })
      fetchAuctions({ pool_id: id })
      fetchRosters({ pool_id: id, season: s as string })
      fetchWinsRaceData(id, s as string)
      loadPoolSeasons(id)
    }
  },
  { immediate: true },
)

async function loadPoolSeasons(poolId: string) {
  seasonsLoading.value = true
  try {
    poolSeasons.value = await fetchPoolSeasons(poolId)
  } catch (e) {
    console.error('Failed to load pool seasons:', e)
  } finally {
    seasonsLoading.value = false
  }
}
</script>

<template>
  <header>
    <TopBanner v-if="activeAuction" :to="`/auctions/${activeAuction.id}`" />
    <div class="flex items-center justify-between px-4 pt-4">
      <Button
        icon="pi pi-home"
        variant="outlined"
        severity="secondary"
        @click="router.push({ name: 'pools' })"
        aria-label="Home"
      />
      <p class="text-xl font-bold">🏀 NBA Wins Pool 🏆</p>
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
    <!-- Pool name and season -->
    <div class="flex flex-col items-center pb-2">
      <p v-if="!overviewLoading" class="text-3xl font-extrabold text-center">
        {{ overview?.name || pool?.name }}
      </p>
      <p v-else-if="overviewError">{{ overviewError }}</p>
      <p v-else>Loading pool overview...</p>
      <p class="text-xl font-medium text-surface-400 italic text-center">{{ season }}</p>
    </div>

    <!-- Main content -->
    <div class="flex flex-col px-4 gap-4 mx-auto max-w-5xl w-full">
      <!-- Leaderboard -->
      <Card
        class="border-2 rounded-xl overflow-hidden border-[var(--p-content-border-color)]"
        :pt="{ body: 'p-0', header: 'px-4 pt-3' }"
      >
        <template #header>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <i class="pi pi-trophy"></i>
              <p class="text-sm font-semibold">Leaderboard</p>
            </div>
            <div v-if="roster && team && roster.length > 0" class="flex gap-1">
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
          <div v-if="leaderboardError" class="text-sm text-red-500 p-4">
            ⚠️ {{ leaderboardError }}
          </div>
          <div v-else-if="leaderboardLoading" class="py-8 text-center text-surface-400">
            <i class="pi pi-spinner pi-spin text-3xl mb-2"></i>
            <p class="text-sm">Loading leaderboard...</p>
          </div>
          <div v-else-if="roster && team">
            <LeaderboardTable
              :roster="roster"
              :team="team"
              :density="tableScale"
              maxHeight="calc(50vh - 4rem)"
            />
          </div>
          <div v-else class="p-4 text-surface-400">
            <p class="text-sm">No data available</p>
          </div>
        </template>
      </Card>

      <!-- Wins race chart -->
      <Card
        class="border-2 rounded-xl overflow-hidden border-[var(--p-content-border-color)]"
        :pt="{ body: 'p-0', header: 'px-4 pt-3' }"
      >
        <template #header>
          <div class="flex items-center gap-2">
            <i class="pi pi-chart-line"></i>
            <p class="text-sm font-semibold">Wins Race</p>
          </div>
        </template>
        <template #content>
          <div v-if="chartError" class="text-sm text-red-500 p-4">⚠️ {{ chartError }}</div>
          <div v-else-if="chartLoading" class="py-8 text-center text-surface-400">
            <i class="pi pi-spinner pi-spin text-3xl mb-2"></i>
            <p class="text-sm">Loading chart data...</p>
          </div>
          <div v-else-if="winsRaceData" class="p-4">
            <WinsRaceChart :wins-race-data="winsRaceData" />
          </div>
          <div v-else class="p-4 text-surface-400">
            <p class="text-sm">No data available</p>
          </div>
        </template>
      </Card>
    </div>

    <!-- Right Drawer -->
    <Drawer v-model:visible="showDrawer" dismissable position="right">
      <template #header>
        <div class="flex gap-2">
          <Button
            icon="pi pi-pencil"
            label="Edit"
            size="small"
            variant="outlined"
            @click="
              () => {
                showEditDialog = true
              }
            "
          />
        </div>
      </template>
      <div class="flex flex-col gap-4">
        <div>
          <p class="font-extrabold text-2xl text-primary">{{ pool?.name || overview?.name }}</p>
          <p class="italic">{{ season }}</p>
          <p class="text-surface-400">{{ pool?.description || overview?.description }}</p>
        </div>

        <Panel toggleable>
          <template #header>
            <p class="font-semibold text-lg text-surface-400">
              <i class="pi pi-clipboard" /> Rules
            </p>
          </template>
          <p
            v-if="pool?.rules || overview?.rules"
            class="whitespace-pre-line max-h-24 md:max-h-none overflow-y-auto"
          >
            {{ pool?.rules || overview?.rules }}
          </p>
          <p v-else class="italic">No rules!</p>
        </Panel>

        <Panel toggleable>
          <template #header>
            <p class="font-semibold text-lg text-surface-400">
              <i class="pi pi-calendar" /> Seasons
            </p>
          </template>
          <ul v-if="poolSeasons.length">
            <li v-for="s in poolSeasons" :key="s.id">
              <RouterLink
                v-if="s.season !== season"
                :to="{ name: 'pool-season', params: { slug: pool?.slug, season: s.season } }"
                class="flex items-center gap-2 hover:opacity-75"
              >
                <p>{{ s.season }}</p>
                <i class="pi pi-arrow-right"></i>
              </RouterLink>
              <div v-else class="flex items-center gap-2">
                <p class="font-semibold text-surface-400">{{ s.season }}</p>
              </div>
            </li>
          </ul>
          <p v-else class="italic">No seasons</p>
          <Button
            class="w-full mt-2"
            iconPos="right"
            icon="pi pi-plus"
            label="Create Season"
            variant="outlined"
            severity="contrast"
            @click="showCreateSeasonDialog = true"
          />
        </Panel>

        <Panel toggleable>
          <template #header>
            <p class="font-semibold text-lg text-surface-400">
              <i class="pi pi-hammer" /> Auction Draft
            </p>
          </template>
          <div class="flex flex-col gap-2">
            <Button
              v-if="currentSeasonAuction"
              class="w-full"
              icon="pi pi-arrow-right"
              iconPos="right"
              :label="`View ${season} Auction`"
              variant="outlined"
              @click="
                router.push({
                  name: 'auction-overview',
                  params: { auctionId: currentSeasonAuction.id },
                })
              "
            />
            <Button
              v-else
              class="w-full"
              iconPos="right"
              icon="pi pi-plus"
              label="Create Auction"
              variant="outlined"
              severity="contrast"
              @click="showCreateAuctionDialog = true"
            />
            <Button
              v-if="currentSeasonAuction?.status === 'completed'"
              class="w-full"
              icon="pi pi-download"
              iconPos="right"
              label="Load Rosters from Auction"
              variant="outlined"
              severity="contrast"
              :loading="importAuctionSubmitting"
              :disabled="importAuctionSubmitting"
              @click="handleImportAuctionRosters"
            />
            <Message v-if="importAuctionError" severity="error" size="small">{{
              importAuctionError
            }}</Message>
            <Message v-if="importAuctionMessage" severity="success" size="small">{{
              importAuctionMessage
            }}</Message>
          </div>
        </Panel>
        <Panel toggleable>
          <template #header>
            <p class="font-semibold text-lg text-surface-400 items-center">
              <i class="pi pi-users"></i> Rosters
            </p>
          </template>
          <ul v-if="overview?.rosters.length" class="flex flex-col gap-2">
            <li v-for="roster in overview?.rosters" :key="roster.id" class="flex items-center gap-2">
              <PlayerAvatar :name="roster.name" size="small" />
              <p class="text-sm font-medium">{{ roster.name }}</p>
            </li>
          </ul>
          <p v-else class="italic text-surface-400">No rosters</p>
          <Button
            class="w-full mt-2"
            icon="pi pi-user-edit"
            iconPos="right"
            label="Manage Rosters"
            variant="outlined"
            severity="contrast"
            @click="openRosterDialog"
          />
        </Panel>
      </div>
    </Drawer>

    <!-- Edit Dialog -->
    <Dialog
      v-model:visible="showEditDialog"
      modal
      :draggable="false"
      dismissableMask
      class="container min-w-min max-w-lg mx-4"
    >
      <template #header>
        <p class="text-2xl font-semibold">Edit Pool & Season</p>
      </template>
      <PoolForm
        mode="edit"
        :initial="{
          name: pool?.name,
          description: pool?.description ?? undefined,
          rules: overview?.rules ?? undefined,
        }"
        :season="season"
        :submitting="editSubmitting"
        :error="editError"
        @submit="handleEditSubmit"
      />
    </Dialog>

    <!-- Create Auction Dialog -->
    <Dialog
      v-model:visible="showCreateAuctionDialog"
      modal
      :draggable="false"
      dismissable
      class="container min-w-min max-w-md mx-4"
    >
      <template #header>
        <p class="text-2xl font-semibold">Create Auction</p>
      </template>
      <AuctionForm
        mode="create"
        :initial="{ pool_id: pool?.id || '', season: season }"
        :submitting="createSubmitting"
        :error="createError"
        @submit="handleCreateAuction"
      />
    </Dialog>

    <!-- Create Season Dialog -->
    <Dialog
      v-model:visible="showCreateSeasonDialog"
      modal
      :draggable="false"
      dismissableMask
      class="container min-w-min max-w-md mx-4"
    >
      <template #header>
        <p class="text-2xl font-semibold">Create Season</p>
      </template>
      <SeasonForm
        :existing-seasons="poolSeasons.map((s) => s.season)"
        :submitting="createSeasonSubmitting"
        :error="createSeasonError"
        @submit="handleCreateSeason"
        @cancel="showCreateSeasonDialog = false"
      />
    </Dialog>

    <!-- Manage Rosters Dialog -->
    <Dialog
      v-model:visible="showRosterDialog"
      modal
      :draggable="false"
      dismissableMask
      class="container min-w-min max-w-lg mx-4 max-h-full"
      @hide="resetRosterDialogState"
    >
      <template #header>
        <p class="text-2xl font-semibold">Manage Rosters</p>
      </template>
      <div class="flex flex-col gap-2 pt-2">
        <Message v-if="rosterError" severity="error" class="text-sm break-all">{{
          rosterError
        }}</Message>
        <Message v-if="rosterActionError" severity="error" class="text-sm break-all">{{
          rosterActionError
        }}</Message>
        <Message v-if="rosterActionMessage" severity="success" class="text-sm break-all">{{
          rosterActionMessage
        }}</Message>
        <p v-if="rosterLoading" class="text-surface-400 text-sm">Loading rosters...</p>
        <p v-else-if="!rosters.length" class="italic text-sm">No rosters yet.</p>
        <div v-else class="flex flex-col gap-2 max-h-full overflow-y-auto pb-4">
          <Card
            v-for="roster in rosters"
            :key="roster.id"
            class="border-2 border-[var(--p-content-border-color)] hover:border-primary"
            :pt="{ body: 'py-2 px-4' }"
          >
            <template #content>
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-3">
                  <PlayerAvatar :name="roster.name" size="normal" />
                  <p class="font-semibold text-lg">{{ roster.name }}</p>
                </div>
                <Button icon="pi pi-pencil" variant="text" @click="openRosterEditDialog(roster)" />
              </div>
            </template>
          </Card>
        </div>
        <div class="flex justify-end">
          <Button label="Add Roster" icon="pi pi-plus" @click="openCreateRosterDialog" />
        </div>
      </div>
    </Dialog>

    <!-- Roster Form Dialog -->
    <Dialog
      v-model:visible="showRosterFormDialog"
      modal
      :draggable="false"
      dismissableMask
      class="container min-w-min max-w-md mx-4"
      @hide="resetRosterFormState"
    >
      <template #header>
        <p class="text-2xl font-semibold">
          {{ rosterFormMode === 'edit' ? 'Edit Roster' : 'Add Roster' }}
        </p>
      </template>
      <form @submit.prevent="handleRosterFormSubmit" class="flex flex-col gap-4">
        <div class="flex flex-col gap-2">
          <label for="roster-form-name" class="flex w-full justify-between">
            <span>Name <span class="text-red-400">*</span></span>
          </label>
          <InputText
            id="roster-form-name"
            v-model="rosterFormName"
            maxlength="100"
            placeholder="Roster name"
            :disabled="rosterFormSubmitting"
          />
          <Message v-if="rosterFormError" class="break-all" severity="error" size="small">{{
            rosterFormError
          }}</Message>
        </div>
        <div class="flex justify-between gap-2 mt-2">
          <Button
            v-if="rosterFormMode === 'edit'"
            icon="pi pi-trash"
            label="Delete"
            severity="danger"
            variant="outlined"
            :disabled="rosterFormSubmitting"
            @click="confirmDeleteRoster"
          />
          <div class="flex gap-2 ml-auto">
            <Button
              v-if="rosterFormMode === 'edit'"
              type="button"
              label="Cancel"
              severity="secondary"
              variant="text"
              :disabled="rosterFormSubmitting"
              @click="resetRosterFormState"
            />
            <Button
              type="submit"
              icon="pi pi-save"
              :label="rosterFormMode === 'edit' ? 'Save' : 'Create'"
              :loading="rosterFormSubmitting"
            />
          </div>
        </div>
      </form>
    </Dialog>
  </main>
</template>
