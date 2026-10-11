<script setup lang="ts">
import { computed } from 'vue'
import Dialog from 'primevue/dialog'
import Message from 'primevue/message'
import RosterEditor from '@/components/pool/RosterEditor.vue'
import type { Pool, Roster } from '@/types/pool'

const props = defineProps<{
  visible: boolean
  pool: Pool
  season: string
  poolSeason: { id: string } | null
  previousSeasons: { id: string; season: string }[]
  rosters: Roster[]
  loading?: boolean
  error?: string | null
  auctionWillReset?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [visible: boolean]
  changed: []
}>()

const isVisible = computed({
  get: () => props.visible,
  set: (visible: boolean) => emit('update:visible', visible),
})
</script>

<template>
  <Dialog
    v-model:visible="isVisible"
    modal
    :draggable="false"
    dismissableMask
    class="container min-w-min max-w-lg mx-4 max-h-full"
  >
    <template #header>
      <p class="text-2xl font-semibold">Manage Rosters</p>
    </template>
    <div class="flex flex-col gap-2 pt-2">
      <Message v-if="error" severity="error" class="text-sm break-all">{{ error }}</Message>
      <RosterEditor
        :pool="pool"
        :season="season"
        :pool-season="poolSeason"
        :previous-seasons="previousSeasons"
        :rosters="rosters"
        :loading="loading"
        :auction-will-reset="auctionWillReset"
        show-done
        @changed="emit('changed')"
        @done="isVisible = false"
      />
    </div>
  </Dialog>
</template>
