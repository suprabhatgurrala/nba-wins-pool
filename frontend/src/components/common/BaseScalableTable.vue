<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCompactTable } from '@/composables/useCompactTable'

const props = defineProps<{
  density?: 'S' | 'M' | 'L'
  maxHeight?: string
  isEmpty?: boolean
}>()

// Calculate scale factor
const scale = computed(() => {
  const d = props.density || 'M'
  if (d === 'S') return 0.75
  if (d === 'L') return 1.25
  return 1
})

// DataTable scroll height - use maxHeight directly
const dtScrollHeight = computed(() => props.maxHeight)

// Wrapper style with CSS custom property for scaling
// This allows child components to scale proportionally using calc()
const wrapperStyle = computed(() => {
  const styles: Record<string, string> = {
    '--table-scale': scale.value.toString(),
  }

  if (!props.isEmpty && props.maxHeight) {
    styles.maxHeight = props.maxHeight
  }

  return styles
})

const root = ref<HTMLElement>()
const compact = useCompactTable(root)
</script>

<template>
  <div
    ref="root"
    class="@container w-full scalable-table tabular-nums"
    :style="wrapperStyle"
    :data-compact="compact || undefined"
  >
    <slot :scrollHeight="dtScrollHeight" :scale="scale" />
  </div>
</template>
