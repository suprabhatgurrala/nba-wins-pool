<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import Select from 'primevue/select'
import Textarea from 'primevue/textarea'
import Button from 'primevue/button'
import Message from 'primevue/message'
import { getRecentSeasons } from '@/utils/season'

export interface SeasonFormData {
  season: string
  rules?: string | null
}

const props = withDefaults(defineProps<{
  initial?: Partial<SeasonFormData>
  existingSeasons?: string[]  // List of seasons that already exist
  submitting?: boolean
  error?: string | null
}>(), {
  initial: () => ({}),
  existingSeasons: () => [],
  submitting: false,
  error: null,
})

const emit = defineEmits<{
  (e: 'submit', payload: SeasonFormData): void
  (e: 'cancel'): void
}>()

const availableSeasons = computed(() => {
  // Get recent seasons and filter out existing ones
  const recent = getRecentSeasons(5)
  return recent.filter(s => !props.existingSeasons.includes(s))
})

const form = reactive<SeasonFormData>({
  season: props.initial?.season || availableSeasons.value[0] || '',
  rules: props.initial?.rules ?? '',
})

const hasSubmitted = ref(false)

// Reset hasSubmitted when submitting prop changes from true to false (submission complete)
watch(() => props.submitting, (newVal, oldVal) => {
  if (oldVal === true && newVal === false) {
    hasSubmitted.value = false
  }
})

const validations = computed(() => {
  const errors: Record<string, string | null> = {
    season: null,
    rules: null,
  }
  if (!form.season) errors.season = 'Required'
  if (form.rules && form.rules.length > 500) errors.rules = 'Max 500 characters'
  return errors
})

const isValid = computed(() => Object.values(validations.value).every((v) => !v))
const showSeasonError = computed(() => hasSubmitted.value && !!validations.value.season)
const showRulesError = computed(() => hasSubmitted.value && !!validations.value.rules)

function onSubmit() {
  hasSubmitted.value = true
  if (!isValid.value) return
  emit('submit', {
    season: form.season,
    rules: form.rules || null,
  })
}

function onCancel() {
  emit('cancel')
}
</script>

<template>
  <form @submit.prevent="onSubmit" class="flex flex-col gap-4 min-w-full">
    <div class="flex flex-col gap-2">
      <label for="season" class="flex w-full justify-between">
        <p>Season <span class="text-red-400">*</span></p>
        <Message v-if="showSeasonError" size="small" severity="error" variant="simple">{{ validations.season }}</Message>
      </label>
      <Select
        v-if="availableSeasons.length > 0"
        id="season"
        v-model="form.season"
        :options="availableSeasons"
        placeholder="Select a season"
        :invalid="showSeasonError"
      />
      <Message v-else severity="warn" size="small">
        All recent seasons already exist for this pool
      </Message>
    </div>

    <div class="flex flex-col gap-2">
      <label for="rules">Rules</label>
      <Message v-if="showRulesError" size="small" severity="error" variant="simple">{{ validations.rules }}</Message>
      <Textarea
        id="rules"
        name="rules"
        rows="3"
        maxlength="500"
        autoResize
        v-model="form.rules"
        placeholder="e.g. 1st place gets a ticket to the Finals"
      />
    </div>

    <Message v-if="error" class="break-all" severity="error">{{ error }}</Message>

    <div class="flex justify-end gap-2 mt-2">
      <Button
        type="button"
        label="Cancel"
        severity="secondary"
        variant="outlined"
        @click="onCancel"
      />
      <Button
        type="submit"
        icon="pi pi-check"
        label="Create"
        :loading="submitting"
        :disabled="!isValid || availableSeasons.length === 0"
      />
    </div>
  </form>
</template>
