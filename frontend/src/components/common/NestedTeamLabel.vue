<script setup lang="ts">
/**
 * A team's logo and name in a row nested under its owner (an expandable owner row's team rows). It's left out of the
 * table's column sizing, so expanding rows never widens the column or changes the other columns' headers: the owner
 * rows set the column's width and the team name fits into it (abbreviating if needed). Give the column a minimum
 * width (`min-w-28`) so the logo and abbreviation always fit, and indent with a padding class.
 */
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
