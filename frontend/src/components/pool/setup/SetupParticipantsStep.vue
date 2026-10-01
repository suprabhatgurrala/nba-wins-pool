<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Button from 'primevue/button'
import ImportRostersDialog from '@/components/pool/ImportRostersDialog.vue'
import ManageRostersDialog from '@/components/pool/ManageRostersDialog.vue'
import PlayerAvatar from '@/components/common/PlayerAvatar.vue'
import { useRosters } from '@/composables/useRosters'
import type { Auction, Pool, Roster } from '@/types/pool'

const props = defineProps<{
  pool: Pool
  season: string
  poolSeason: { id: string } | null
  previousSeasons: { id: string; season: string }[]
  rosters: Roster[]
  auction: Auction | null
}>()

const emit = defineEmits<{
  changed: []
  next: []
}>()

const showManage = ref(false)
const showImport = ref(false)

const { rosters: poolRosters, fetchRosters } = useRosters()
onMounted(() => fetchRosters({ pool_id: props.pool.id }))

const sourceSeasons = computed(() => {
  const withRosters = new Set(poolRosters.value.map((r) => r.season))
  return props.previousSeasons.filter((s) => withRosters.has(s.season))
})
const canImport = computed(
  () =>
    props.rosters.length === 0 &&
    sourceSeasons.value.length > 0 &&
    props.auction?.status !== 'active',
)
</script>

<template>
  <div class="flex flex-col gap-4">
    <ul v-if="rosters.length" class="flex flex-wrap gap-2" data-testid="setup-participants">
      <li
        v-for="r in rosters"
        :key="r.id"
        class="flex items-center gap-2 rounded-full border-2 border-[var(--p-content-border-color)] py-1 pl-1.5 pr-3"
      >
        <PlayerAvatar :name="r.name" size="small" />
        <span class="text-sm font-medium">{{ r.name }}</span>
      </li>
    </ul>
    <div
      v-else
      class="flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-[var(--p-content-border-color)] px-4 py-6 text-center"
    >
      <i class="pi pi-users text-2xl text-surface-400" aria-hidden="true"></i>
      <p class="text-sm text-surface-400">No one has been added yet.</p>
    </div>

    <div class="flex gap-2">
      <Button
        v-if="auction?.status !== 'active'"
        label="Manage Rosters"
        icon="pi pi-user-edit"
        class="flex-1"
        :variant="rosters.length ? 'outlined' : undefined"
        :severity="rosters.length ? 'contrast' : undefined"
        @click="showManage = true"
      />
      <Button
        v-if="canImport"
        label="Import from Season"
        icon="pi pi-download"
        class="flex-1"
        variant="outlined"
        severity="contrast"
        @click="showImport = true"
      />
    </div>

    <div class="flex items-center justify-between gap-2">
      <p class="text-sm text-surface-400">
        {{ rosters.length }} participant{{ rosters.length === 1 ? '' : 's' }}
      </p>
      <Button
        label="Next"
        icon="pi pi-arrow-right"
        icon-pos="right"
        :disabled="rosters.length === 0"
        @click="emit('next')"
      />
    </div>

    <ImportRostersDialog
      v-model:visible="showImport"
      :pool-season="poolSeason"
      :previous-seasons="sourceSeasons"
      :auction-will-reset="auction?.status === 'not_started'"
      @imported="emit('changed')"
    />

    <ManageRostersDialog
      v-model:visible="showManage"
      :pool="pool"
      :season="season"
      :pool-season="poolSeason"
      :previous-seasons="sourceSeasons"
      :rosters="rosters"
      :auction-will-reset="auction?.status === 'not_started'"
      @changed="emit('changed')"
    />
  </div>
</template>
