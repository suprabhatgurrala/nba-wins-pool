<script setup lang="ts">
/** A team's full name, or its abbreviation when it doesn't fit (together with its `provideTeamNameGroup` group). */
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
