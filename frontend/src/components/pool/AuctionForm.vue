<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import type { AuctionCreate, AuctionUpdate, AuctionStatus } from '@/types/pool'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import InputGroup from 'primevue/inputgroup'
import InputGroupAddon from 'primevue/inputgroupaddon'
import Dropdown from 'primevue/dropdown'
import Button from 'primevue/button'
import Message from 'primevue/message'

const props = withDefaults(defineProps<{
  mode?: 'create' | 'edit'
  initial?: Partial<AuctionCreate & { status?: AuctionStatus }>
  submitting?: boolean
  error?: string | null
  auctionStatus?: AuctionStatus
}>(), {
  mode: 'create',
  initial: () => ({}),
  submitting: false,
  error: null,
  auctionStatus: 'not_started',
})

const emit = defineEmits<{
  (e: 'submit', payload: AuctionCreate | AuctionUpdate): void
}>()

const isEdit = computed(() => props.mode === 'edit')
const canEditConfig = computed(() => props.auctionStatus === 'not_started')

const form = reactive<Required<AuctionCreate>>({
  pool_id: props.initial?.pool_id || '',
  season: props.initial?.season || '',
  max_lots_per_participant: props.initial?.max_lots_per_participant ?? 1,
  min_bid_increment: props.initial?.min_bid_increment ?? 1,
  starting_participant_budget: props.initial?.starting_participant_budget ?? 200,
})

const statusValue = ref<AuctionStatus>((props.initial?.status as AuctionStatus) || 'active')

const touched = reactive({
  season: false,
  max_lots_per_participant: false,
  min_bid_increment: false,
  starting_participant_budget: false,
})
const hasSubmitted = ref(false)

const validations = computed(() => {
  const errors: Record<string, string | null> = {
    season: null,
    max_lots_per_participant: null,
    min_bid_increment: null,
    starting_participant_budget: null,
  }
  if (!isEdit.value || canEditConfig.value) {
    if (!isEdit.value) {
      if (!form.season) errors.season = 'Required'
      // Minimal format check: YYYY-YY e.g., 2024-25
      else if (!/^[0-9]{4}-[0-9]{2}$/.test(form.season)) errors.season = 'Format YYYY-YY (e.g., 2024-25)'
    }

    if (!Number.isInteger(form.max_lots_per_participant) || form.max_lots_per_participant <= 0) {
      errors.max_lots_per_participant = 'Must be greater than 0'
    }
    if (!Number.isInteger(form.min_bid_increment) || form.min_bid_increment < 1) {
      errors.min_bid_increment = 'Must be greater than 0'
    }
    if (!Number.isInteger(form.starting_participant_budget) || form.starting_participant_budget <= 0) {
      errors.starting_participant_budget = 'Must be greater than 0'
    }
  }
  return errors
})

const isValid = computed(() => Object.values(validations.value).every((v) => !v))

function onSubmit() {
  hasSubmitted.value = true
  if (isEdit.value) {
    const payload: AuctionUpdate = {}
    
    // Include config fields if auction hasn't started
    if (canEditConfig.value) {
      payload.max_lots_per_participant = Math.max(1, Math.floor(Number(form.max_lots_per_participant)))
      payload.min_bid_increment = Math.max(1, Math.floor(Number(form.min_bid_increment)))
      payload.starting_participant_budget = Math.max(1, Math.floor(Number(form.starting_participant_budget)))
    }
    
    emit('submit', payload)
    return
  }
  if (!isValid.value) return
  const payload: AuctionCreate = {
    pool_id: form.pool_id,
    season: form.season,
    max_lots_per_participant: Math.max(1, Math.floor(Number(form.max_lots_per_participant))),
    min_bid_increment: Math.max(1, Math.floor(Number(form.min_bid_increment))),
    starting_participant_budget: Math.max(1, Math.floor(Number(form.starting_participant_budget))),
  }
  emit('submit', payload)
}

const showSeasonError = computed(() => !isEdit.value && (touched.season || hasSubmitted.value) && !!validations.value.season)
const showMaxLotsError = computed(() => (!isEdit.value || canEditConfig.value) && (touched.max_lots_per_participant || hasSubmitted.value) && !!validations.value.max_lots_per_participant)
const showMinIncError = computed(() => (!isEdit.value || canEditConfig.value) && (touched.min_bid_increment || hasSubmitted.value) && !!validations.value.min_bid_increment)
const showBudgetError = computed(() => (!isEdit.value || canEditConfig.value) && (touched.starting_participant_budget || hasSubmitted.value) && !!validations.value.starting_participant_budget)

const statusOptions: { label: string; value: AuctionStatus }[] = [
  { label: 'Start Auction', value: 'active' },
  { label: 'Complete Auction', value: 'completed' },
]
</script>

<template>
  <form @submit.prevent="onSubmit" class="flex flex-col gap-4 min-w-full">
    <!-- Season -->
    <div v-if="!isEdit" class="flex flex-col gap-2">
      <label for="season" class="flex w-full justify-between">
        <p>Season <span class="text-red-400">*</span></p>
        <Message v-if="showSeasonError" size="small" severity="error" variant="simple">{{ validations.season }}</Message>
      </label>
      <InputText
        disabled
        id="season"
        v-model="form.season"
        placeholder="e.g. 2024-25"
        :invalid="showSeasonError"
        @blur="touched.season = true"
      />
    </div>

    <div v-if="!isEdit || canEditConfig" class="flex flex-col gap-2">
      <!-- Max Lots per Participant -->
      <div class="flex flex-col gap-2">
        <label for="maxLots" class="flex w-full justify-between">
          <p>Max Teams per Participant <span class="text-red-400">*</span></p>
          <Message v-if="showMaxLotsError" size="small" severity="error" variant="simple">{{ validations.max_lots_per_participant }}</Message>
        </label>
        <InputNumber
          inputId="maxLots"
          v-model="form.max_lots_per_participant"
          :min="1"
          :step="1"
          :useGrouping="false"
          :invalid="showMaxLotsError as any"
          @blur="touched.max_lots_per_participant = true"
        />
      </div>
      
      <!-- Starting Budget -->
      <div class="flex flex-col gap-2">
        <label for="budget" class="flex w-full justify-between">
          <p>Starting Budget <span class="text-red-400">*</span></p>
          <Message v-if="showBudgetError" size="small" severity="error" variant="simple">{{ validations.starting_participant_budget }}</Message>
        </label>
        <InputGroup>  
          <InputGroupAddon>$</InputGroupAddon>
          <InputNumber
            inputId="budget"
            v-model="form.starting_participant_budget"
            :min="1"
            :step="1"
            :useGrouping="false"
            :invalid="showBudgetError as any"
            @blur="touched.starting_participant_budget = true"
          />
          <InputGroupAddon>.00</InputGroupAddon>
          </InputGroup>
      </div>

      <!-- Min Bid Increment -->
      <div class="flex flex-col gap-2">
        <label for="minInc" class="flex w-full justify-between">
          <p>Min Bid Increment <span class="text-red-400">*</span></p>
          <Message v-if="showMinIncError" size="small" severity="error" variant="simple">{{ validations.min_bid_increment }}</Message>
        </label>
        <InputGroup>  
          <InputGroupAddon>$</InputGroupAddon>
          <InputNumber
            inputId="minInc"
            v-model="form.min_bid_increment"
            :min="1"
            :step="1"
            :useGrouping="false"
            :invalid="showMinIncError as any"
            @blur="touched.min_bid_increment = true"
          />
          <InputGroupAddon>.00</InputGroupAddon>
        </InputGroup>
      </div>
    </div>

    <!-- Read-only status display -->
    <div v-if="isEdit && !canEditConfig" class="flex flex-col gap-2">
      <p class="text-sm text-surface-400">Auction configuration cannot be modified after it has started.</p>
    </div>

    <!-- Status (removed, now handled by confirmation dialogs) -->
    <div v-if="false" class="flex flex-col gap-2">
      <label for="status" class="flex w-full justify-between">
        <p>Change Status</p>
      </label>
      <Dropdown
        inputId="status"
        v-model="statusValue"
        :options="statusOptions"
        optionLabel="label"
        optionValue="value"
        class="w-full"
      />
      <p class="text-xs text-surface-400">Select <b>Start Auction</b> to begin, or <b>Complete Auction</b> when the draft is finished.</p>
    </div>

    <!-- Error Message -->
    <Message v-if="error" class="break-all" severity="error">{{ error }}</Message>

    <!-- Submit Button -->
    <div class="flex justify-end mt-2">
      <Button
        type="submit"
        icon="pi pi-check"
        :label="isEdit ? 'Save' : 'Create'"
        :loading="submitting"
        :disabled="!isEdit && (!isValid || hasSubmitted)"
      />
    </div>
  </form>
</template>
