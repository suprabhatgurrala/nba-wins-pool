<script setup lang="ts">
import { computed, ref } from 'vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Message from 'primevue/message'
import Select from 'primevue/select'
import { useRosters } from '@/composables/useRosters'

const props = defineProps<{
  visible: boolean
  poolSeason: { id: string } | null
  previousSeasons: { id: string; season: string }[]
  auctionWillReset?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [visible: boolean]
  imported: [message: string]
}>()

const { importRostersFromSeason } = useRosters()
const submitting = ref(false)
const error = ref<string | null>(null)
const selectedSourceId = ref<string | null>(null)

const isVisible = computed({
  get: () => props.visible,
  set: (visible: boolean) => emit('update:visible', visible),
})

function reset() {
  isVisible.value = false
  submitting.value = false
  error.value = null
  selectedSourceId.value = null
}

async function handleImport() {
  if (!props.poolSeason?.id || !selectedSourceId.value) return
  submitting.value = true
  error.value = null
  try {
    const source = props.previousSeasons.find((s) => s.id === selectedSourceId.value)
    const imported = await importRostersFromSeason(selectedSourceId.value, props.poolSeason.id)
    const count = imported.length
    const message = `Successfully imported ${count} roster${count === 1 ? '' : 's'} from ${source?.season || 'other season'}`
    reset()
    emit('imported', message)
  } catch (e: any) {
    error.value = e?.message || 'Failed to import rosters'
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
    @hide="reset"
  >
    <template #header>
      <p class="text-2xl font-semibold">Import Rosters</p>
    </template>
    <form @submit.prevent="handleImport" class="flex flex-col gap-4">
      <Message v-if="auctionWillReset" severity="warn" class="text-sm">
        Importing rosters requires re-creating the auction.
      </Message>
      <div class="flex flex-col gap-2">
        <label for="source-season" class="flex w-full justify-between">
          <span>Select Season <span class="text-red-400">*</span></span>
        </label>
        <Select
          id="source-season"
          v-model="selectedSourceId"
          :options="previousSeasons"
          optionLabel="season"
          optionValue="id"
          placeholder="Choose a season"
          :disabled="submitting"
          class="w-full"
        />
        <Message v-if="error" class="break-all" severity="error" size="small">{{ error }}</Message>
      </div>
      <div class="flex justify-end gap-2 mt-2">
        <Button
          type="button"
          label="Cancel"
          severity="secondary"
          variant="text"
          :disabled="submitting"
          @click="reset"
        />
        <Button
          type="submit"
          icon="pi pi-download"
          label="Import"
          :loading="submitting"
          :disabled="!selectedSourceId"
        />
      </div>
    </form>
  </Dialog>
</template>
