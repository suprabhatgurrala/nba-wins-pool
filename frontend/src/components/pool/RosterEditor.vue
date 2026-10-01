<script setup lang="ts">
import { ref } from 'vue'
import { useConfirm } from 'primevue/useconfirm'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Message from 'primevue/message'
import Select from 'primevue/select'
import PlayerAvatar from '@/components/common/PlayerAvatar.vue'
import { useRosters } from '@/composables/useRosters'
import type { Pool, Roster } from '@/types/pool'

const props = withDefaults(
  defineProps<{
    pool: Pool
    season: string
    poolSeason: { id: string } | null
    previousSeasons: { id: string; season: string }[]
    rosters: Roster[]
    loading?: boolean
    auctionWillReset?: boolean
    showDone?: boolean
  }>(),
  { loading: false, auctionWillReset: false, showDone: false },
)

const emit = defineEmits<{
  changed: []
  done: []
}>()

const AUCTION_RESET_WARNING = 'This also deletes the auction.'

const confirm = useConfirm()
const { createRoster, updateRoster, deleteRoster, importRostersFromSeason } = useRosters()

const actionError = ref<string | null>(null)
const actionMessage = ref<string | null>(null)

function resetMessages() {
  actionError.value = null
  actionMessage.value = null
}

const showFormDialog = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const rosterToEdit = ref<Roster | null>(null)
const formName = ref('')
const formSubmitting = ref(false)
const formError = ref<string | null>(null)

function resetFormState() {
  showFormDialog.value = false
  formMode.value = 'create'
  rosterToEdit.value = null
  formName.value = ''
  formError.value = null
  formSubmitting.value = false
}

function openCreateDialog() {
  formMode.value = 'create'
  rosterToEdit.value = null
  formName.value = ''
  formError.value = null
  showFormDialog.value = true
}

function openEditDialog(roster: Roster) {
  formMode.value = 'edit'
  rosterToEdit.value = roster
  formName.value = roster.name
  formError.value = null
  showFormDialog.value = true
}

async function handleFormSubmit() {
  const trimmedName = formName.value.trim()
  if (!trimmedName) {
    formError.value = 'Please enter a roster name'
    return
  }
  formSubmitting.value = true
  formError.value = null
  resetMessages()
  try {
    if (formMode.value === 'create') {
      await createRoster({ name: trimmedName, pool_id: props.pool.id, season: props.season })
      actionMessage.value = 'Roster added successfully'
    } else if (formMode.value === 'edit' && rosterToEdit.value) {
      await updateRoster(rosterToEdit.value.id, { name: trimmedName })
      actionMessage.value = 'Roster updated'
    }
    showFormDialog.value = false
    emit('changed')
  } catch (e: any) {
    formError.value = e?.message || 'Failed to save roster'
  } finally {
    formSubmitting.value = false
  }
}

function confirmDelete(roster: Roster) {
  confirm.require({
    message:
      `Are you sure you want to delete ${roster.name}? This action cannot be undone.` +
      (props.auctionWillReset ? ` ${AUCTION_RESET_WARNING}` : ''),
    header: 'Delete Roster',
    rejectLabel: 'Cancel',
    acceptLabel: 'Delete',
    icon: 'pi pi-trash',
    accept: async () => {
      formError.value = null
      resetMessages()
      try {
        await deleteRoster(roster.id)
        actionMessage.value = 'Roster removed'
        showFormDialog.value = false
        emit('changed')
      } catch (e: any) {
        actionError.value = e?.message || 'Failed to delete roster'
      } finally {
        rosterToEdit.value = null
      }
    },
  })
}

const showImportDialog = ref(false)
const importSubmitting = ref(false)
const importError = ref<string | null>(null)
const selectedSourceId = ref<string | null>(null)

function resetImportDialog() {
  showImportDialog.value = false
  importSubmitting.value = false
  importError.value = null
  selectedSourceId.value = null
}

function openImportDialog() {
  importError.value = null
  selectedSourceId.value = null
  showImportDialog.value = true
}

async function handleImport() {
  if (!props.poolSeason?.id || !selectedSourceId.value) return
  importSubmitting.value = true
  importError.value = null
  resetMessages()
  try {
    const source = props.previousSeasons.find((s) => s.id === selectedSourceId.value)
    const imported = await importRostersFromSeason(selectedSourceId.value, props.poolSeason.id)
    const count = imported.length
    actionMessage.value = `Successfully imported ${count} roster${count === 1 ? '' : 's'} from ${source?.season || 'other season'}`
    showImportDialog.value = false
    emit('changed')
  } catch (e: any) {
    importError.value = e?.message || 'Failed to import rosters'
  } finally {
    importSubmitting.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <Message v-if="actionError" severity="error" class="text-sm break-all">{{
      actionError
    }}</Message>
    <Message v-if="actionMessage" severity="success" class="text-sm break-all">{{
      actionMessage
    }}</Message>

    <p v-if="loading" class="text-surface-400 text-sm">Loading rosters...</p>
    <p v-else-if="!rosters.length" class="italic text-sm text-surface-400">No rosters yet.</p>
    <div v-else class="flex flex-col gap-2 max-h-full overflow-y-auto pb-2" data-testid="rosters">
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
            <div class="flex">
              <Button
                icon="pi pi-pencil"
                variant="text"
                :aria-label="`Edit ${roster.name}`"
                @click="openEditDialog(roster)"
              />
              <Button
                icon="pi pi-trash"
                variant="text"
                severity="danger"
                :aria-label="`Delete ${roster.name}`"
                @click="confirmDelete(roster)"
              />
            </div>
          </div>
        </template>
      </Card>
    </div>

    <div class="flex flex-wrap justify-end gap-2">
      <Button
        v-if="previousSeasons.length > 0 && !rosters.length"
        label="Import from Season"
        icon="pi pi-download"
        variant="outlined"
        severity="contrast"
        @click="openImportDialog"
      />
      <Button label="Add Roster" icon="pi pi-plus" @click="openCreateDialog" />
      <Button v-if="showDone" label="Done" icon="pi pi-check" @click="emit('done')" />
    </div>

    <Dialog
      v-model:visible="showFormDialog"
      modal
      :draggable="false"
      dismissableMask
      class="container min-w-min max-w-md mx-4"
      @hide="resetFormState"
    >
      <template #header>
        <p class="text-2xl font-semibold">
          {{ formMode === 'edit' ? 'Edit Roster' : 'Add Roster' }}
        </p>
      </template>
      <form @submit.prevent="handleFormSubmit" class="flex flex-col gap-4">
        <Message v-if="auctionWillReset && formMode === 'create'" severity="warn" class="text-sm">
          Adding a roster deletes the auction.
        </Message>
        <div class="flex flex-col gap-2">
          <label for="roster-form-name" class="flex w-full justify-between">
            <span>Name <span class="text-red-400">*</span></span>
          </label>
          <InputText
            id="roster-form-name"
            v-model="formName"
            maxlength="100"
            placeholder="Roster name"
            :disabled="formSubmitting"
          />
          <Message v-if="formError" class="break-all" severity="error" size="small">{{
            formError
          }}</Message>
        </div>
        <div class="flex justify-between gap-2 mt-2">
          <Button
            v-if="formMode === 'edit'"
            icon="pi pi-trash"
            label="Delete"
            severity="danger"
            variant="outlined"
            :disabled="formSubmitting"
            @click="rosterToEdit && confirmDelete(rosterToEdit)"
          />
          <div class="flex gap-2 ml-auto">
            <Button
              v-if="formMode === 'edit'"
              type="button"
              label="Cancel"
              severity="secondary"
              variant="text"
              :disabled="formSubmitting"
              @click="resetFormState"
            />
            <Button
              type="submit"
              icon="pi pi-save"
              :label="formMode === 'edit' ? 'Save' : 'Create'"
              :loading="formSubmitting"
            />
          </div>
        </div>
      </form>
    </Dialog>

    <Dialog
      v-model:visible="showImportDialog"
      modal
      :draggable="false"
      dismissableMask
      class="container min-w-min max-w-md mx-4"
      @hide="resetImportDialog"
    >
      <template #header>
        <p class="text-2xl font-semibold">Import Rosters</p>
      </template>
      <form @submit.prevent="handleImport" class="flex flex-col gap-4">
        <Message v-if="auctionWillReset" severity="warn" class="text-sm">
          Importing rosters deletes the auction.
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
            :disabled="importSubmitting"
            class="w-full"
          />
          <Message v-if="importError" class="break-all" severity="error" size="small">{{
            importError
          }}</Message>
        </div>
        <div class="flex justify-end gap-2 mt-2">
          <Button
            type="button"
            label="Cancel"
            severity="secondary"
            variant="text"
            :disabled="importSubmitting"
            @click="resetImportDialog"
          />
          <Button
            type="submit"
            icon="pi pi-download"
            label="Import"
            :loading="importSubmitting"
            :disabled="!selectedSourceId"
          />
        </div>
      </form>
    </Dialog>
  </div>
</template>
