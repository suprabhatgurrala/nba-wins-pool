<script setup lang="ts">
import { computed, ref } from 'vue'
import Dialog from 'primevue/dialog'
import PoolForm from '@/components/pool/PoolForm.vue'
import { usePools } from '@/composables/usePools'
import { usePoolSeasons } from '@/composables/usePoolSeasons'
import type { Pool, PoolCreate, PoolUpdate } from '@/types/pool'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [visible: boolean]
  created: [pool: Pool]
}>()

const { createPool } = usePools()
const { createPoolSeason } = usePoolSeasons()
const submitting = ref(false)
const submitError = ref<string | null>(null)

const isVisible = computed({
  get: () => props.visible,
  set: (visible: boolean) => emit('update:visible', visible),
})

function close() {
  submitError.value = null
  isVisible.value = false
}

async function handleCreate(payload: {
  pool: PoolCreate | PoolUpdate
  rules?: string | null
  season?: string
}) {
  submitting.value = true
  submitError.value = null
  try {
    const createdPool = await createPool(payload.pool as PoolCreate)

    if (payload.season) {
      try {
        await createPoolSeason(createdPool.id, {
          pool_id: createdPool.id,
          season: payload.season,
          rules: payload.rules || null,
        })
      } catch (error) {
        console.error('Failed to create pool season:', error)
      }
    }

    emit('created', createdPool)
    close()
  } catch (error) {
    submitError.value = error instanceof Error ? error.message : 'Failed to create pool'
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
    class="container max-w-lg m-2"
    @hide="close"
  >
    <template #header>
      <p class="text-2xl font-semibold">Create New Pool</p>
    </template>
    <PoolForm
      mode="create"
      :submitting="submitting"
      :error="submitError"
      @submit="handleCreate"
    />
  </Dialog>
</template>
