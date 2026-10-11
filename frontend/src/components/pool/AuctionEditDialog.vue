<script setup lang="ts">
import { computed, ref } from 'vue'
import { useToast } from 'primevue/usetoast'
import Dialog from 'primevue/dialog'
import AuctionForm from '@/components/pool/AuctionForm.vue'
import { useAuctions } from '@/composables/useAuctions'
import type { AuctionCreate, AuctionOverview, AuctionStatus, AuctionUpdate } from '@/types/pool'

const props = defineProps<{
  visible: boolean
  auctionId: string
  auctionOverview: AuctionOverview | null
}>()

const emit = defineEmits<{
  'update:visible': [visible: boolean]
  updated: []
}>()

const toast = useToast()
const { updateAuction } = useAuctions()
const submitting = ref(false)
const error = ref<string | null>(null)

const isVisible = computed({
  get: () => props.visible,
  set: (visible: boolean) => emit('update:visible', visible),
})

async function handleSubmit(payload: AuctionCreate | AuctionUpdate) {
  submitting.value = true
  error.value = null
  try {
    await updateAuction(props.auctionId, payload as AuctionUpdate)
    emit('updated')
    isVisible.value = false
    toast.add({
      severity: 'success',
      summary: 'Auction Updated',
      detail: 'Auction configuration has been updated',
      life: 3000,
    })
  } catch (e: any) {
    error.value = e?.message || 'Failed to update auction'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Dialog
    v-model:visible="isVisible"
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
      :submitting="submitting"
      :error="error"
      @submit="handleSubmit"
    />
  </Dialog>
</template>
