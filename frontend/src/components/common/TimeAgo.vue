<script setup lang="ts">
/** A relative time ("5 minutes ago") that shortens to "5m ago" when it doesn't fit. */
import { computed } from 'vue'
import FitText from '@/components/common/FitText.vue'
import { timeAgo, timeAgoShort } from '@/utils/time'

const props = defineProps<{
  date: Date
  now?: Date
  /** Tooltip; defaults to the date in the viewer's locale. */
  title?: string
}>()

const full = computed(() => timeAgo(props.date, props.now))
const short = computed(() => timeAgoShort(props.date, props.now))
</script>

<template>
  <time :datetime="date.toISOString()" class="flex min-w-0">
    <FitText :full="full" :short="short" :title="title ?? date.toLocaleString()" />
  </time>
</template>
