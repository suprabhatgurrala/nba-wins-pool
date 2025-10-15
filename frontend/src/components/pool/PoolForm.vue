<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { PoolCreate, PoolUpdate } from '@/types/pool'
import InputText from 'primevue/inputtext'
import InputGroup from 'primevue/inputgroup'
import InputGroupAddon from 'primevue/inputgroupaddon'
import Select from 'primevue/select'
import Textarea from 'primevue/textarea'
import Button from 'primevue/button'
import Message from 'primevue/message'
import Popover, { type PopoverMethods } from 'primevue/popover'
import { getRecentSeasons } from '@/utils/season'

const props = withDefaults(
  defineProps<{
    mode?: 'create' | 'edit'
    initial?: Partial<PoolCreate & PoolUpdate> & { rules?: string | null; season?: string }
    season?: string | null // Current season for rules editing
    submitting?: boolean
    error?: string | null
  }>(),
  {
    mode: 'create',
    initial: () => ({}),
    season: null,
    submitting: false,
    error: null,
  },
)

const availableSeasons = getRecentSeasons(5)
const emit = defineEmits<{
  (
    e: 'submit',
    payload: { pool: PoolCreate | PoolUpdate; rules?: string | null; season?: string },
  ): void
}>()

const form = reactive<Required<PoolCreate> & { rules: string; season: string }>({
  slug: props.initial?.slug?.toLowerCase() || '',
  name: props.initial?.name || '',
  description: props.initial?.description ?? '',
  rules: props.initial?.rules ?? '',
  season: props.initial?.season || availableSeasons[0],
})
const touched = reactive({ slug: false, name: false })
const hasSubmitted = ref(false)
const isSlugManuallyModified = ref(false)

// Reset hasSubmitted when submitting prop changes from true to false (submission complete)
watch(
  () => props.submitting,
  (newVal, oldVal) => {
    if (oldVal === true && newVal === false) {
      hasSubmitted.value = false
    }
  },
)

// Watch name field to auto-populate slug if not manually modified
watch(
  () => form.name,
  (newName) => {
    if (!isEdit.value && (!isSlugManuallyModified.value || !form.slug)) {
      const slugFromName = newName
        .toLowerCase()
        .replace(/\s+/g, '-')
        .replace(/[^a-z0-9-]/g, '')
        .substring(0, 20)
      form.slug = slugFromName
    }
  },
)

// Normalize slug when changed
watch(
  () => form.slug,
  (v) => {
    // Only normalize if there's a value to avoid clearing the field
    if (v) {
      const normalized = v
        .toLowerCase()
        .replace(/\s+/g, '-')
        .replace(/[^a-z0-9-]/g, '')
      if (normalized !== v) form.slug = normalized
    } else {
      // If slug is cleared, reset the modified flag to allow auto-fill again
      isSlugManuallyModified.value = false
    }
  },
)

const isEdit = computed(() => props.mode === 'edit')

// TODO: use some validation library like zod
const validations = computed(() => {
  const errors: Record<string, string | null> = {
    slug: null,
    name: null,
    description: null,
    rules: null,
  }
  if (!isEdit.value) {
    if (!form.slug) errors.slug = 'Required'
    else if (form.slug.length > 20) errors.slug = 'Max 20 characters'
    else if (!/^[a-z0-9-]+$/.test(form.slug))
      errors.slug = 'Use lowercase letters, numbers, and hyphens only'
  }
  if (!form.name) errors.name = 'Required'
  else if (form.name.length > 100) errors.name = 'Max 100 characters'
  if (form.description && form.description.length > 500) errors.description = 'Max 500 characters'
  if (form.rules && form.rules.length > 500) errors.rules = 'Max 500 characters'
  return errors
})

const isValid = computed(() => Object.values(validations.value).every((v) => !v))
const slugInfo = ref<PopoverMethods>()
const toggleSlugInfo = (event: Event) => {
  slugInfo.value?.toggle(event)
}

function onSubmit() {
  hasSubmitted.value = true
  if (!isValid.value) return
  if (isEdit.value) {
    const poolPayload: PoolUpdate = {
      name: form.name,
      description: form.description || null,
    }
    // Rules are handled separately via pool season
    emit('submit', { pool: poolPayload, rules: form.rules || null })
  } else {
    const poolPayload: PoolCreate = {
      slug: form.slug,
      name: form.name,
      description: form.description || null,
    }
    // For create mode, pass season and rules to create pool season
    emit('submit', { pool: poolPayload, rules: form.rules || null, season: form.season })
  }
}

const showSlugError = computed(
  () => !isEdit.value && (touched.slug || hasSubmitted.value) && !!validations.value.slug,
)
const showNameError = computed(
  () => (touched.name || hasSubmitted.value) && !!validations.value.name,
)
const showDescriptionError = computed(() => hasSubmitted.value && !!validations.value.description)
const showRulesError = computed(() => hasSubmitted.value && !!validations.value.rules)
</script>

<template>
  <form @submit.prevent="onSubmit" class="flex flex-col gap-4 min-w-full">
    <div class="flex flex-col gap-2">
      <label for="name" class="flex w-full justify-between">
        <p>Name <span class="text-red-400">*</span></p>
        <Message v-if="showNameError" size="small" severity="error" variant="simple">{{
          validations.name
        }}</Message>
      </label>
      <InputText
        id="name"
        v-model="form.name"
        maxlength="100"
        placeholder="e.g. My Cool Pool"
        :invalid="showNameError"
        @blur="touched.name = true"
      />
    </div>

    <div v-if="!isEdit" class="flex flex-col gap-2">
      <label for="slug" class="flex w-full justify-between">
        <p>Unique ID <span class="text-red-400">*</span></p>
        <Message v-if="showSlugError" size="small" severity="error" variant="simple">{{
          validations.slug
        }}</Message>
      </label>
      <InputGroup class="focus-within">
        <InputText
          class="w-full"
          id="slug"
          v-model="form.slug"
          maxlength="20"
          placeholder="e.g. my-cool-pool"
          :invalid="showSlugError"
          @blur="touched.slug = true"
          @input="isSlugManuallyModified = true"
        />
        <InputGroupAddon>
          <Button
            severity="secondary"
            icon="pi pi-info-circle"
            @click="toggleSlugInfo"
            variant="text"
          />
          <Popover ref="slugInfo">
            <div class="text-center text-sm">
              <p>Unique identifier for your pool.</p>
              <p>Can only contain lowercase letters, numbers, and hyphens</p>
            </div>
          </Popover>
        </InputGroupAddon>
      </InputGroup>
    </div>

    <div class="flex flex-col gap-2">
      <label for="description">Description</label>
      <Message v-if="showDescriptionError" size="small" severity="error" variant="simple">{{
        validations.description
      }}</Message>
      <Textarea
        id="description"
        name="description"
        rows="2"
        maxlength="500"
        autoResize
        v-model="form.description"
        placeholder="e.g. Annual NBA wins pool with friends"
      />
    </div>

    <div v-if="!isEdit" class="flex flex-col gap-2">
      <label for="season">Season</label>
      <Select
        id="season"
        v-model="form.season"
        :options="availableSeasons"
        placeholder="Select a season"
      />
    </div>

    <div class="flex flex-col gap-2">
      <label for="rules">Season Rules</label>
      <Message v-if="showRulesError" size="small" severity="error" variant="simple">{{
        validations.rules
      }}</Message>
      <Textarea
        id="rules"
        name="rules"
        rows="2"
        maxlength="500"
        autoResize
        v-model="form.rules"
        placeholder="e.g. 1st place gets a ticket to the Finals"
      />
    </div>

    <Message v-if="error" class="break-all" severity="error">{{ error }}</Message>

    <div class="flex justify-end gap-2 mt-2">
      <Button
        type="submit"
        icon="pi pi-check"
        :label="isEdit ? 'Save' : 'Create'"
        :loading="submitting"
        :disabled="!isValid"
      />
    </div>
  </form>
</template>
