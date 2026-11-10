<script setup lang="ts">
import { computed } from 'vue'
import PoolTimelineChart, { type TimelineLine } from '@/components/pool/PoolTimelineChart.vue'
import type { WinProbabilityHistory } from '@/types/winProbabilityHistory'

const props = defineProps<{
  history: WinProbabilityHistory
}>()

const latest = (values: (number | null)[]) => [...values].reverse().find((v) => v != null) ?? -1

const lines = computed<TimelineLine[]>(() => {
  const { rosters, timestamps, series } = props.history
  return rosters
    .map((r) => ({ name: r.name, values: series[r.id] ?? [] }))
    .sort((a, b) => latest(b.values) - latest(a.values))
    .map(({ name, values }) => ({ name, points: timestamps.map((t, i) => [t, values[i] ?? null]) }))
})
</script>

<template>
  <PoolTimelineChart
    :lines="lines"
    :milestones="props.history.milestones"
    :ranges="['1D', '1W', '1M', 'ALL']"
    :format-value="(v) => `${v.toFixed(1)}%`"
    :format-axis-value="(v) => `${Math.round(v)}%`"
    hourly
    :y-min="0"
    :y-step="10"
  />
</template>
