<script setup lang="ts">
import { RouterLink, type RouteLocationRaw } from 'vue-router'

defineProps<{
  season: string
  to: RouteLocationRaw
  highlighted?: boolean
}>()
</script>

<template>
  <RouterLink
    :to="to"
    class="grid grid-cols-[1fr_auto] items-center gap-1 border-r border-content bg-surface-800/40 py-3 pl-2 pr-1.5 text-center transition-colors hover:bg-surface-700/40"
  >
    <div class="flex flex-col items-center">
      <span
        class="w-full border-b border-content pb-2 text-xs font-semibold"
        :class="highlighted ? 'text-primary' : 'text-surface-400'"
        >{{ season }}</span
      >
      <div class="flex flex-1 flex-col items-center justify-center gap-1 pt-2">
        <slot />
      </div>
    </div>
    <i class="pi pi-angle-right text-[0.6rem] text-surface-500"></i>
  </RouterLink>
</template>
