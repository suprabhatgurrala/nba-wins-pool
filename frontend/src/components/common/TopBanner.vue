<script setup lang="ts">
import { useRouter } from 'vue-router'
import LiveDot from '@/components/common/LiveDot.vue'

const props = withDefaults(
  defineProps<{
    to: string
    label?: string
    showDot?: boolean
    dotColor?: string
    dotSize?: number
    trailingIcon?: string
  }>(),
  {
    label: 'Auction Live Now',
    showDot: true,
    dotColor: 'var(--p-red-500)',
    dotSize: 10,
    trailingIcon: 'pi pi-arrow-right',
  },
)

const router = useRouter()
const go = () => router.push(props.to)
const onKey = (e: KeyboardEvent) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    go()
  }
}
</script>

<template>
  <div
    class="cursor-pointer bg-primary text-primary-contrast py-2"
    role="link"
    tabindex="0"
    @click="go"
    @keydown="onKey"
  >
    <div class="flex items-center justify-center gap-3 text-p-primary-contrast">
      <LiveDot
        v-if="props.showDot"
        :size="props.dotSize"
        :color="props.dotColor"
        aria-label="Live"
      />
      <span class="font-bold">{{ props.label }}</span>
      <i :class="props.trailingIcon" aria-hidden="true"></i>
    </div>
  </div>
</template>
