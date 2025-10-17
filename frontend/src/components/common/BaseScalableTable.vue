<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  density?: 'S' | 'M' | 'L'
  maxHeight?: string
  scrollHeight?: string
  isEmpty?: boolean
}>()

// Calculate scale factor based on density
const scale = computed(() => {
  const d = props.density || 'M'
  if (d === 'S') return 0.75
  if (d === 'L') return 1.25
  return 1
})

// Calculate scroll height inversely scaled to maintain visible area
const dtScrollHeight = computed(() => {
  if (props.scrollHeight) return props.scrollHeight
  if (props.maxHeight) return `calc(${props.maxHeight} / ${scale.value})`
  return undefined
})

// Wrapper style: don't apply maxHeight when empty to allow natural sizing
const wrapperStyle = computed(() => {
  if (props.isEmpty || !props.maxHeight) return undefined
  return { height: props.maxHeight }
})

// Scale transform style
const scaleStyle = computed(() => ({
  transform: `scale(${scale.value})`,
  transformOrigin: 'top left',
  width: `${(100 / scale.value).toFixed(4)}%`,
}))
</script>

<template>
  <div class="w-full" :style="wrapperStyle">
    <div class="origin-top-left" :style="scaleStyle">
      <slot :scrollHeight="dtScrollHeight" :scale="scale" />
    </div>
  </div>
</template>
