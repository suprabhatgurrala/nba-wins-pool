<script setup lang="ts">
/**
 * A table column's header label: `full` when the column has room for it, otherwise `short`. Use it in a Column's
 * `#header` slot (not its `header` prop) so every table shortens its headers the same way, column by column, as space
 * runs out. A label may wrap onto two lines before it shortens.
 */
import FitText from '@/components/common/FitText.vue'

defineProps<{
  full: string
  short?: string
}>()
</script>

<template>
  <FitText class="p-datatable-column-title" :full="full" :short="short" :lines="2" collapse />
</template>
