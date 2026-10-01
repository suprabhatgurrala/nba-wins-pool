<script setup lang="ts">
import { computed, ref } from 'vue'
import Button from 'primevue/button'
import Message from 'primevue/message'
import AuctionForm from '@/components/pool/AuctionForm.vue'
import SetupAuctionStatus from '@/components/pool/setup/SetupAuctionStatus.vue'
import { useAuctions } from '@/composables/useAuctions'
import { addNbaTeams, addPoolRosters } from '@/composables/useAuctionImports'
import type { Auction, AuctionCreate, AuctionUpdate, Pool } from '@/types/pool'

const props = defineProps<{
  pool: Pool
  season: string
  auction: Auction | null
  participantCount: number
  importingRosters: boolean
}>()

const emit = defineEmits<{
  changed: []
  back: []
  'import-rosters': []
}>()

const { createAuction } = useAuctions()
const DEFAULT_BUDGET = 200
const suggested = computed(() => ({
  max_lots_per_participant: Math.max(1, Math.floor(30 / Math.max(1, props.participantCount))),
  starting_participant_budget: DEFAULT_BUDGET,
}))

const submitting = ref(false)
const error = ref<string | null>(null)

async function handleSubmit(payload: AuctionCreate | AuctionUpdate) {
  submitting.value = true
  error.value = null
  try {
    const created = await createAuction(payload as AuctionCreate)
    await Promise.allSettled([addPoolRosters(created.id), addNbaTeams(created.id)])
    emit('changed')
  } catch (e: any) {
    error.value = e?.message || 'Failed to create auction'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <SetupAuctionStatus
      v-if="auction"
      :auction="auction"
      :importing-rosters="importingRosters"
      @changed="emit('changed')"
      @back="emit('back')"
      @import-rosters="emit('import-rosters')"
    />
    <template v-else>
      <p class="text-lg font-semibold">Auction settings</p>
      <AuctionForm
        mode="create"
        hide-season
        :initial="{ pool_id: props.pool.id, season: props.season, ...suggested }"
        :submitting="submitting"
        :error="error"
        @submit="handleSubmit"
      >
        <template #actions>
          <Button label="Back" severity="secondary" variant="text" @click="emit('back')" />
        </template>
      </AuctionForm>
    </template>
  </div>
</template>
