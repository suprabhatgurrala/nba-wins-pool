<script setup lang="ts">
/** Logo and team name for an expanded row; excluded from column sizing so expanding doesn't resize the column. */
import TeamName from '@/components/common/TeamName.vue'

defineProps<{
  name: string
  abbreviation?: string | null
  logoUrl?: string | null
}>()
</script>

<template>
  <div class="flex min-w-0 items-center gap-1 [contain:inline-size]">
    <img
      v-if="logoUrl"
      :src="logoUrl"
      :alt="abbreviation ?? name"
      width="20"
      height="20"
      class="size-5 shrink-0 object-contain"
    />
    <TeamName :name="name" :abbreviation="abbreviation" />
  </div>
</template>
