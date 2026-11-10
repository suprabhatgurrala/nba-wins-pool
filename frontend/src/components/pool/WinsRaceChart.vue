<script setup lang="ts">
import { computed } from 'vue'
import PoolTimelineChart, { type TimelineLine } from '@/components/pool/PoolTimelineChart.vue'
import type { WinsRaceData } from '@/types/winsRace'

const props = defineProps<{
  winsRaceData: WinsRaceData | null
}>()

const lines = computed<TimelineLine[]>(() => {
  const data = props.winsRaceData
  if (!data?.metadata?.rosters) return []
  const points = new Map<string, [number, number][]>(data.metadata.rosters.map((r) => [r.name, []]))
  for (const d of data.data) {
    points.get(d.roster)?.push([new Date(`${d.date}T00:00:00`).getTime(), d.wins])
  }
  return data.metadata.rosters.map((r) => ({ name: r.name, points: points.get(r.name) ?? [] }))
})
</script>

<template>
  <PoolTimelineChart
    v-if="props.winsRaceData && props.winsRaceData.data.length > 0"
    :lines="lines"
    :milestones="props.winsRaceData.metadata?.milestones ?? []"
    :ranges="['1W', '1M', 'ALL']"
    :format-value="(v) => String(v)"
  />
  <p
    v-else-if="props.winsRaceData && props.winsRaceData.data.length === 0"
    class="text-surface-400"
    role="alert"
  >
    No data available
  </p>
  <p v-else class="text-surface-400" role="alert">Chart could not be loaded.</p>
</template>
