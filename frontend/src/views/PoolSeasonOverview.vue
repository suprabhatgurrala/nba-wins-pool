<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Drawer from 'primevue/drawer'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import { RouterLink } from 'vue-router'
import Panel from 'primevue/panel'
import Card from 'primevue/card'
import LeaderboardTable from '@/components/pool/LeaderboardTable.vue'
import WinsRaceChart from '@/components/pool/WinsRaceChart.vue'
import { useLeaderboard } from '@/composables/useLeaderboard'
import TopBanner from '@/components/common/TopBanner.vue'
import BaseToolbar from '@/components/common/BaseToolbar.vue'
import { useWinsRaceData } from '@/composables/useWinsRaceData'
import { usePoolMetadata } from '@/composables/usePoolMetadata'
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
import DeleteConfirmDialog from '@/components/common/DeleteConfirmDialog.vue'


const route = useRoute()
const router = useRouter()

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

const {
  poolMetadata,
  error: metadataError,
  loading: metadataLoading,
  fetchPoolMetadata,
} = usePoolMetadata()

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
const season = computed(
  () => (route.params.season as string) || getCurrentSeason(),
)

const currentSeasonAuction = computed(() => auctions.value.find((a) => a.season === season.value) ?? null)
const activeAuction = computed(() =>
  currentSeasonAuction.value?.status === 'active'
    ? currentSeasonAuction.value
    : null,
)

// Drawer & modals
const showDrawer = ref(false)
const showEditDialog = ref(false)
const editSubmitting = ref(false)
const editError = ref<string | null>(null)
const showDeleteConfirm = ref(false)
const deleteSubmitting = ref(false)
const deleteError = ref<string | null>(null)
const poolDeleteName = computed(() => pool.value?.name ?? 'this pool')
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
const rosterDeleteSubmitting = ref(false)
const showRosterDeleteDialog = ref(false)
const rosterDeleteName = computed(() => rosterToEdit.value?.name ?? 'this roster')

function resetRosterFormState() {
  showRosterFormDialog.value = false
  rosterFormMode.value = 'create'
  rosterToEdit.value = null
  rosterFormName.value = ''
  rosterFormError.value = null
  rosterFormSubmitting.value = false
  rosterDeleteSubmitting.value = false
  showRosterDeleteDialog.value = false
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
            rules: payload.rules
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

function cancelDeletePool() {
  showDeleteConfirm.value = false
  deleteSubmitting.value = false
  deleteError.value = null
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
    await router.push({ name: 'pool-season', params: { slug: pool.value.slug, season: payload.season } })
    showCreateSeasonDialog.value = false
  } catch (e: any) {
    createSeasonError.value = e?.message || 'Failed to create season'
  } finally {
    createSeasonSubmitting.value = false
  }
}

async function confirmDeletePool() {
  if (!pool.value?.id) return
  deleteSubmitting.value = true
  deleteError.value = null
  try {
    await deletePool(pool.value.id)
    showDeleteConfirm.value = false
    // Navigate to pools list after delete
    router.replace({ name: 'pools' })
  } catch (e: any) {
    deleteError.value = e?.message || 'Failed to delete pool'
  } finally {
    deleteSubmitting.value = false
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

function cancelRosterDelete() {
  showRosterDeleteDialog.value = false
  rosterDeleteSubmitting.value = false
}

async function handleDeleteRosterFromForm() {
  if (!pool.value?.id || !rosterToEdit.value) return
  rosterDeleteSubmitting.value = true
  rosterFormError.value = null
  rosterActionError.value = null
  rosterActionMessage.value = null
  try {
    await deleteRoster(rosterToEdit.value.id)
    rosterActionMessage.value = 'Roster removed'
    showRosterFormDialog.value = false
    showRosterDeleteDialog.value = false
    await fetchRosters({ pool_id: pool.value.id, season: season.value })
    await fetchPoolSeasonOverview({ poolId: pool.value.id, season: season.value })
  } catch (e: any) {
    rosterFormError.value = e?.message || 'Failed to delete roster'
  } finally {
    rosterDeleteSubmitting.value = false
    rosterToEdit.value = null
  }
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
          await router.replace({ name: 'pool-season', params: { slug: p.slug, season: mostRecentSeason } })
          return
        }
      } catch (e) {
        console.warn('Could not fetch pool seasons, using current season:', e)
      }
    }
    
    // Replace visible URL to canonical slug route
    if ((route.params.slug as string) !== p.slug) {
      if (route.params.season) {
        await router.replace({ name: 'pool-season', params: { slug: p.slug, season: route.params.season } })
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
      fetchAuctions({ pool_id: id})
      fetchRosters({ pool_id: id, season: s as string })
      fetchWinsRaceData(id, s as string)
      loadPoolSeasons(id)
    }
  },
  { immediate: true }
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

// When slug becomes available or changes, fetch slug-based datasets
watch(
  [slugRef, season],
  ([s, v]) => {
    if (s) {
      fetchPoolMetadata(s as string)
    }
  },
  { immediate: true },
)
</script>

<template>
  <header>
    <TopBanner v-if="activeAuction" :to="`/auctions/${activeAuction.id}`" />
    <div class="flex items-center justify-between p-4">
      <Button icon="pi pi-home" variant="outlined" severity="secondary" @click="router.push({ name: 'pools' })" aria-label="Home" />
      <p class="text-xl font-bold">🏀 NBA Wins Pool 🏆</p>
      <Button icon="pi pi-bars" variant="outlined" severity="secondary" @click="showDrawer = true" aria-label="Menu" />
    </div>
  
  </header>
  <main>
    <!-- Pool name and season -->
    <div class="flex flex-col items-center my-2">
      <p v-if="!overviewLoading" class="text-4xl font-extrabold text-center">{{ overview?.name || pool?.name }}</p>
      <p v-else-if="overviewError">{{ overviewError }}</p>
      <p v-else>Loading pool overview...</p>
      <p class="text-xl font-medium text-surface-400 italic text-center">{{ season }}</p>
    </div>

    <!-- Main content -->
    <div class="flex flex-col p-4 gap-4 mx-auto max-w-3xl min-w-min">
      <!-- Leaderboard -->
      <div class="flex flex-col gap-2">
        <p class="text-2xl font-semibold w-full pt-2">Leaderboard</p>
        <p v-if="leaderboardLoading" class="text-surface-400">Loading leaderboard...</p>
        <p v-else-if="leaderboardError" class="text-surface-400">{{ leaderboardError }}</p>
        <LeaderboardTable
          v-else
          :roster="roster"
          :team="team"
        />
      </div>

      <!-- Wins race chart -->
      <div class="flex flex-col gap-2">

        <p class="text-2xl font-semibold w-full">Wins</p>
        <p v-if="chartLoading" class="text-surface-400">Loading chart data...</p>
        <p v-else-if="chartError" class="text-surface-400">{{ chartError }}</p>
        <WinsRaceChart v-else :wins-race-data="winsRaceData" />

      </div>
    </div>

    <!-- Right Drawer -->
    <Drawer v-model:visible="showDrawer" dismissable position="right">
    <template #header>
      <div class="flex gap-2">
        <Button icon="pi pi-pencil" label="Edit" size="small" variant="outlined" @click="() => { showEditDialog = true }" />
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
          <p class="font-semibold text-lg text-surface-400"><i class="pi pi-clipboard"/> Rules</p>
        </template>
        <p v-if="pool?.rules || overview?.rules" class="whitespace-pre-line max-h-24 md:max-h-none overflow-y-auto">{{ pool?.rules || overview?.rules }}</p>
        <p v-else class="italic">No rules!</p>
      </Panel>

      <Panel toggleable>
        <template #header>
          <p class="font-semibold text-lg text-surface-400"><i class="pi pi-calendar"/> Seasons</p>
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
          <p class="font-semibold text-lg text-surface-400"><i class="pi pi-hammer"/> Auction Draft</p>
        </template>
        <Button
          v-if="currentSeasonAuction"
          class="w-full"
          icon="pi pi-arrow-right"
          iconPos="right"
          :label="`View ${season} Auction`"
          variant="outlined"
          @click="router.push({ name: 'auction', params: { auctionId: currentSeasonAuction.id } })"
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
      </Panel>
      <Panel toggleable>
        <template #header>
          <p class="font-semibold text-lg text-surface-400 items-center"><i class="pi pi-users"></i> Rosters</p>
        </template>
        <ul v-if="overview?.rosters.length">
          <li v-for="roster in overview?.rosters" :key="roster.id">
            <p class=""><i class="pi pi-user" style="font-size: 0.8rem"/> {{ roster.name }}</p>
          </li>
        </ul>
        <p v-else class="italic">No rosters</p>
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
    <Dialog v-model:visible="showEditDialog" modal :draggable="false" dismissableMask class="container min-w-min max-w-lg mx-4">
      <template #header>
        <p class="text-2xl font-semibold">Edit Pool & Season</p>
      </template>
      <PoolForm
        mode="edit"
        :initial="{ name: pool?.name, description: pool?.description ?? undefined, rules: overview?.rules ?? undefined }"
        :season="season"
        :submitting="editSubmitting"
        :error="editError"
        @submit="handleEditSubmit"
        @delete="showDeleteConfirm = true"
      />
    </Dialog>

    <DeleteConfirmDialog
      v-model:visible="showDeleteConfirm"
      title="Delete Pool"
      :confirmLoading="deleteSubmitting"
      :confirmDisabled="deleteSubmitting"
      @confirm="confirmDeletePool"
      @cancel="cancelDeletePool"
    >
      <template #message>
        <div class="flex flex-col gap-2">
          <p class="text-sm">
            Are you sure you want to delete <span class="font-semibold">{{ poolDeleteName }}</span>? This action cannot be undone.
          </p>
          <p v-if="deleteError" class="text-red-500 text-sm">{{ deleteError }}</p>
        </div>
      </template>
    </DeleteConfirmDialog>

    <!-- Create Auction Dialog -->
    <Dialog v-model:visible="showCreateAuctionDialog" modal :draggable="false" dismissable class="container min-w-min max-w-md mx-4">
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
    <Dialog v-model:visible="showCreateSeasonDialog" modal :draggable="false" dismissableMask class="container min-w-min max-w-md mx-4">
      <template #header>
        <p class="text-2xl font-semibold">Create Season</p>
      </template>
      <SeasonForm
        :existing-seasons="poolSeasons.map(s => s.season)"
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
      <div class="flex flex-col gap-4">
        <Message v-if="rosterError" severity="error" class="text-red-500 text-sm break-all">{{ rosterError }}</Message>
        <Message v-if="rosterActionError" severity="error" class="text-red-500 text-sm break-all">{{ rosterActionError }}</Message>
        <Message v-if="rosterActionMessage" severity="success" class="text-emerald-500 text-sm break-all">{{ rosterActionMessage }}</Message>
        <p v-if="rosterLoading" class="text-surface-400 text-sm">Loading rosters...</p>
        <p v-else-if="!rosters.length" class="italic text-sm">No rosters yet.</p>
        <div v-else class="flex flex-col gap-2 max-h-full overflow-y-auto pr-1">
          <Card
            v-for="roster in rosters"
            :key="roster.id"
            class="border-content hover:border-primary"
          >
            <template #content>
              <div class="flex items-center justify-between">
                <div class="flex flex-col gap-1 items-start justify-start">
                  <p class="font-semibold text-lg">{{ roster.name }}</p>
                </div>
                <Button icon="pi pi-pencil" variant="outlined" @click="openRosterEditDialog(roster)" />
              </div>
            </template>
          </Card>
        </div>
        <div class="flex justify-end">
          <Button
            label="Add Roster"
            icon="pi pi-plus"
            @click="openCreateRosterDialog"
          />
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
        <p class="text-2xl font-semibold">{{ rosterFormMode === 'edit' ? 'Edit Roster' : 'Add Roster' }}</p>
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
          <Message v-if="rosterFormError" class="break-all" severity="error" size="small">{{ rosterFormError }}</Message>
        </div>
        <div class="flex justify-between gap-2 mt-2">
          <Button
            v-if="rosterFormMode === 'edit'"
            icon="pi pi-trash"
            label="Delete"
            severity="danger"
            variant="outlined"
            :loading="rosterDeleteSubmitting"
            :disabled="rosterFormSubmitting || rosterDeleteSubmitting"
            @click.prevent="showRosterDeleteDialog = true"
          />
          <div class="flex gap-2 ml-auto">
            <Button
              v-if="rosterFormMode === 'edit'"
              type="button"
              label="Cancel"
              severity="secondary"
              variant="text"
              :disabled="rosterFormSubmitting || rosterDeleteSubmitting"
              @click="resetRosterFormState"
            /> 
            <Button
              type="submit"
              icon="pi pi-save"
              :label="rosterFormMode === 'edit' ? 'Save' : 'Create'"
              :loading="rosterFormSubmitting"
              :disabled="rosterDeleteSubmitting"
            />
          </div>
        </div>
      </form>
    </Dialog>

    <DeleteConfirmDialog
      v-model:visible="showRosterDeleteDialog"
      title="Delete Roster"
      :confirmLoading="rosterDeleteSubmitting"
      :confirmDisabled="rosterDeleteSubmitting"
      @confirm="handleDeleteRosterFromForm"
      @cancel="cancelRosterDelete"
    >
      <template #message>
        <p class="text-sm">
          Are you sure you want to delete <span class="font-semibold">{{ rosterDeleteName }}</span>? This action cannot be undone.
        </p>
      </template>
    </DeleteConfirmDialog>
  </main>
</template>


