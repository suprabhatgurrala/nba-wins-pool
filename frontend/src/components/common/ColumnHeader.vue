<script setup lang="ts">
/** A column header that wraps to two lines, then shortens to `short`. Use in a Column's `#header` slot. */
import FitText from '@/components/common/FitText.vue'

defineProps<{
  full: string
  short?: string
}>()
</script>

<template>
  <FitText class="p-datatable-column-title" :full="full" :short="short" :lines="2" collapse />
</template>
