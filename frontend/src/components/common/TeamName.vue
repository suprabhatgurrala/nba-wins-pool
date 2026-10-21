<script setup lang="ts">
/**
 * A team's full name when it fits the space available, otherwise its abbreviation. Inside a component that calls
 * `provideTeamNameGroup`, every team name there abbreviates as soon as one of them doesn't fit. With `lines`, the full
 * name may wrap onto that many lines (between words) before it abbreviates.
 */
import FitText from '@/components/common/FitText.vue'
import { useTeamNameGroup } from '@/composables/useFitGroup'

defineProps<{
  name: string
  abbreviation?: string | null
  /** How many lines the full name may wrap onto before abbreviating; defaults to 1. */
  lines?: number
}>()

const group = useTeamNameGroup()
</script>

<template>
  <FitText :full="name" :short="abbreviation" :group="group" :lines="lines" :wrap-full="!!lines" />
</template>
