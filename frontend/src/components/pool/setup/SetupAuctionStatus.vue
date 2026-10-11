<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Button from 'primevue/button'
import Message from 'primevue/message'
import AuctionEditDialog from '@/components/pool/AuctionEditDialog.vue'
import AuctionStatusPanel from '@/components/pool/AuctionStatusPanel.vue'
import { useAuctionImports } from '@/composables/useAuctionImports'
import { useAuctionOverview } from '@/composables/useAuctionOverview'
import type { Auction } from '@/types/pool'

const props = defineProps<{
  auction: Auction
  importingRosters: boolean
}>()

const emit = defineEmits<{
  changed: []
  back: []
  'import-rosters': []
}>()

const { auctionOverview, fetchAuctionOverview } = useAuctionOverview(props.auction.id)
const {
  importParticipantsSubmitting,
  importParticipantsError,
  importLotsSubmitting,
  importLotsError,
  handleImportParticipants,
  handleImportLotsFromLeague,
} = useAuctionImports(props.auction.id, fetchAuctionOverview)

onMounted(fetchAuctionOverview)

const showEditDialog = ref(false)

async function handleUpdated() {
  await fetchAuctionOverview()
  emit('changed')
}

const participantCount = computed(() => auctionOverview.value?.participants.length ?? 0)
const lotCount = computed(() => auctionOverview.value?.lots.length ?? 0)
const canImport = computed(() => !!auctionOverview.value && props.auction.status === 'not_started')
</script>

<template>
  <div class="flex flex-col gap-4">
    <AuctionStatusPanel :auction-overview="auctionOverview" />

    <Button
      v-if="canImport && !participantCount"
      label="Import Pool Rosters"
      icon="pi pi-user-plus"
      class="w-full"
      variant="outlined"
      severity="contrast"
      :loading="importParticipantsSubmitting"
      :disabled="importParticipantsSubmitting"
      @click="handleImportParticipants"
    />
    <Button
      v-if="canImport && !lotCount"
      label="Load All NBA Teams"
      icon="pi pi-download"
      class="w-full"
      variant="outlined"
      severity="contrast"
      :loading="importLotsSubmitting"
      :disabled="importLotsSubmitting"
      @click="handleImportLotsFromLeague"
    />
    <Message v-if="importParticipantsError" severity="error" size="small">{{
      importParticipantsError
    }}</Message>
    <Message v-if="importLotsError" severity="error" size="small">{{ importLotsError }}</Message>

    <div class="flex items-center justify-between gap-2">
      <Button label="Back" severity="secondary" variant="text" @click="emit('back')" />
      <div class="flex gap-2">
        <Button
          v-if="auction.status === 'not_started'"
          icon="pi pi-pencil"
          label="Edit"
          variant="outlined"
          @click="showEditDialog = true"
        />
        <Button
          v-if="auction.status === 'completed'"
          label="Load rosters from auction"
          icon="pi pi-download"
          :loading="importingRosters"
          @click="emit('import-rosters')"
        />
        <RouterLink v-else :to="{ name: 'auction-overview', params: { auctionId: auction.id } }">
          <Button label="Open auction" icon="pi pi-arrow-right" icon-pos="right" />
        </RouterLink>
      </div>
    </div>

    <AuctionEditDialog
      v-model:visible="showEditDialog"
      :auction-id="auction.id"
      :auction-overview="auctionOverview"
      @updated="handleUpdated"
    />
  </div>
</template>
