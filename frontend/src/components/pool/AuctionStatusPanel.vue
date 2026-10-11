<script setup lang="ts">
import { computed } from 'vue'
import Panel from 'primevue/panel'
import Tag from 'primevue/tag'
import { formatUTCDate, formatUTCTime } from '@/utils/time'
import type { AuctionOverview } from '@/types/pool'

const props = defineProps<{
  auctionOverview: AuctionOverview | null
}>()

const statusDisplay = computed(() =>
  String(props.auctionOverview?.status || '')
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' '),
)

const statusSeverity = computed(() => {
  const s = String(props.auctionOverview?.status || '')
  if (s === 'active') return 'success'
  if (s === 'completed') return 'info'
  return 'secondary'
})
</script>

<template>
  <Panel>
    <template #header>
      <div class="flex items-center justify-between w-full">
        <p class="font-semibold text-lg text-surface-400">Status</p>
        <Tag class="text-sm" :value="statusDisplay" :severity="statusSeverity" />
      </div>
    </template>
    <div class="flex flex-col gap-2">
      <div class="grid grid-cols-[1fr_auto] gap-x-4 gap-y-2">
        <div class="text-sm text-surface-400">Teams per Participant</div>
        <div class="text-sm text-right font-semibold">
          {{ auctionOverview?.max_lots_per_participant }}
        </div>
        <div class="text-sm text-surface-400">Min Bid Increment</div>
        <div class="text-sm text-right font-semibold">
          ${{ auctionOverview?.min_bid_increment }}
        </div>
        <div class="text-sm text-surface-400">Starting Budget</div>
        <div class="text-sm text-right font-semibold">
          ${{ auctionOverview?.starting_participant_budget }}
        </div>
        <template v-if="auctionOverview?.started_at">
          <p class="text-sm text-surface-400">Started At</p>
          <div class="text-right font-semibold text-xs">
            <p>{{ formatUTCDate(auctionOverview.started_at) }}</p>
            <p>{{ formatUTCTime(auctionOverview.started_at) }}</p>
          </div>
        </template>
        <template v-if="auctionOverview?.completed_at">
          <p class="text-sm text-surface-400">Completed At</p>
          <div class="text-right font-semibold text-xs">
            <p>{{ formatUTCDate(auctionOverview.completed_at) }}</p>
            <p>{{ formatUTCTime(auctionOverview.completed_at) }}</p>
          </div>
        </template>
      </div>
    </div>
  </Panel>
</template>
