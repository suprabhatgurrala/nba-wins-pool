<script setup lang="ts">
import { ref, watch } from 'vue'
import { marked } from 'marked'
import Dialog from 'primevue/dialog'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void }>()

const markdown = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

watch(
  () => props.visible,
  async (open) => {
    if (!open || markdown.value !== null) return
    loading.value = true
    error.value = null
    try {
      const res = await fetch('/internal/docs/simulation')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      markdown.value = await res.text()
    } catch (e: any) {
      error.value = e?.message || 'Failed to load documentation'
    } finally {
      loading.value = false
    }
  },
)
</script>

<template>
  <Dialog
    :visible="visible"
    modal
    :draggable="false"
    dismissableMask
    class="container min-w-min w-full max-w-2xl mx-4"
    @update:visible="emit('update:visible', $event)"
  >
    <template #header>
      <p class="text-2xl font-semibold">How the simulation works</p>
    </template>

    <div class="py-2">
      <div v-if="loading" class="text-surface-400 text-sm py-6 text-center">
        <i class="pi pi-spin pi-spinner mr-2" />Loading…
      </div>
      <div v-else-if="error" class="text-red-400 text-sm py-4">
        <i class="pi pi-exclamation-triangle mr-1" />{{ error }}
      </div>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div v-else-if="markdown" class="prose prose-invert max-w-none text-sm" v-html="marked(markdown)" />
    </div>
  </Dialog>
</template>

<style scoped>
@reference "@/assets/main.css";
/* Markdown prose styles — scoped so they only apply inside this dialog */
.prose :deep(h1) { @apply text-xl font-bold mt-4 mb-2; }
.prose :deep(h2) { @apply text-lg font-semibold mt-6 mb-2 border-b border-surface-700 pb-1; }
.prose :deep(h3) { @apply text-base font-semibold mt-4 mb-1; }
.prose :deep(p)  { @apply mb-3 leading-relaxed text-surface-200; }
.prose :deep(ul) { @apply list-disc pl-5 mb-3 space-y-1 text-surface-200; }
.prose :deep(ol) { @apply list-decimal pl-5 mb-3 space-y-1 text-surface-200; }
.prose :deep(li) { @apply leading-relaxed; }
.prose :deep(strong) { @apply font-semibold text-white; }
.prose :deep(em) { @apply italic text-surface-300; }
.prose :deep(hr) { @apply border-surface-700 my-4; }
.prose :deep(code) { @apply text-xs bg-surface-800 px-1 py-0.5 rounded; }
</style>
