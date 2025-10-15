<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import type { RosterRow, TeamRow } from '@/types/leaderboard'
import type { LeaderboardItem, TeamBreakdownItem } from '@/types/pool'

const props = defineProps<{
  roster: RosterRow[] | null
  team: TeamRow[] | null
  density?: 'S' | 'M' | 'L'
  scrollHeight?: string
  maxHeight?: string
}>()

const expandedPlayers = ref(new Set<string>())
const tableData = ref<(LeaderboardItem | TeamBreakdownItem)[]>([])
const allExpanded = ref(false)

const isRosterRow = (item: LeaderboardItem | TeamBreakdownItem): item is LeaderboardItem => {
  return 'rank' in item
}

const rowClass = (item: LeaderboardItem | TeamBreakdownItem) => {
  return isRosterRow(item) ? 'hover:cursor-pointer' : 'cursor-default'
}

const handleRowClick = (event: { data: LeaderboardItem | TeamBreakdownItem }) => {
  if (isRosterRow(event.data)) {
    togglePlayer(event.data)
  }
}

const leaderboard = computed<LeaderboardItem[] | null>(() => {
  if (!props.roster) return null
  return props.roster.map((o) => ({
    rank: o.rank,
    name: o.name,
    auction_price: `$${o.auction_price}`,
    record: `${o.wins}-${o.losses}`,
    record_today: `${o.wins_today}-${o.losses_today}`,
    record_yesterday: `${o.wins_yesterday}-${o.losses_yesterday}`,
    record_7d: `${o.wins_last7}-${o.losses_last7}`,
    record_30d: `${o.wins_last30}-${o.losses_last30}`,
  }))
})

const teamBreakdown = computed<TeamBreakdownItem[] | null>(() => {
  if (!props.team) return null
  return props.team.map((t) => ({
    name: t.name,
    team: t.team,
    logo_url: t.logo_url,
    record: `${t.wins}-${t.losses}`,
    result_today: t.today_result,
    result_yesterday: t.yesterday_result,
    record_7d: `${t.wins_last7}-${t.losses_last7}`,
    record_30d: `${t.wins_last30}-${t.losses_last30}`,
    auction_price: `$${t.auction_price}`,
  }))
})

const getSeverity = (result: string) => {
  switch (result[0]) {
    case 'W':
      return 'success'
    case 'L':
      return 'danger'
    default:
      return 'secondary'
  }
}

const togglePlayer = (player: LeaderboardItem) => {
  if (expandedPlayers.value.has(player.name)) {
    expandedPlayers.value.delete(player.name)
    allExpanded.value = false
  } else {
    expandedPlayers.value.add(player.name)
    allExpanded.value = leaderboard.value?.every((p) => expandedPlayers.value.has(p.name)) || false
  }
  updateTableData()
}

const toggleAllPlayers = () => {
  if (allExpanded.value) {
    expandedPlayers.value.clear()
  } else {
    leaderboard.value?.forEach((player) => {
      expandedPlayers.value.add(player.name)
    })
  }
  allExpanded.value = !allExpanded.value
  updateTableData()
}

const updateTableData = () => {
  if (!leaderboard.value) return

  const data: (LeaderboardItem | TeamBreakdownItem)[] = []
  leaderboard.value.forEach((player) => {
    data.push(player)
    if (expandedPlayers.value.has(player.name)) {
      const teams = teamBreakdown.value?.filter((team) => team.name === player.name) || []
      data.push(...teams)
    }
  })
  tableData.value = data
}

watch(
  () => leaderboard.value,
  () => {
    updateTableData()
  },
  { immediate: true },
)

// Determine DataTable scroll behavior
const dtScrollable = computed(() => !!(props.scrollHeight || props.maxHeight))

// Scaling logic: parent controls density; we scale the table content while keeping the surrounding Card header unaffected
const scale = computed(() => {
  const d = props.density || 'M'
  if (d === 'S') return 0.75
  if (d === 'L') return 1.25
  return 1
})

// Calculate dynamic height based on actual table content
// Row height is determined by CSS: td padding (.15rem * 2) + line-height
// Approximate: 0.3rem padding + ~1.5rem content ≈ 1.8rem per row
const estimatedRowHeight = 1.8 // rem units
const estimatedHeaderHeight = 2.5 // rem units

const dynamicTableHeight = computed(() => {
  if (!tableData.value.length) return undefined
  const totalRows = tableData.value.length
  const contentHeight = estimatedHeaderHeight + totalRows * estimatedRowHeight
  return `${contentHeight}rem`
})

// Scroll height must be inversely scaled to keep visible area consistent and enable vertical scrolling
const dtScrollHeight = computed(() => {
  if (props.scrollHeight) return props.scrollHeight
  if (props.maxHeight) return `calc(${props.maxHeight} / ${scale.value})`
  return undefined as unknown as string
})

const wrapperStyle = computed(() => {
  if (!props.maxHeight) return undefined
  // Use the smaller of maxHeight or dynamic height to eliminate extra space
  if (dynamicTableHeight.value) {
    return { height: `min(${props.maxHeight}, calc(${dynamicTableHeight.value} * ${scale.value}))` }
  }
  return { height: props.maxHeight }
})

const scaleStyle = computed(() => ({
  transform: `scale(${scale.value})`,
  transformOrigin: 'top left',
  width: `${(100 / scale.value).toFixed(4)}%`,
}))
</script>

<template>
  <div class="w-full" :style="wrapperStyle">
    <div class="origin-top-left" :style="scaleStyle">
      <DataTable
        v-if="tableData.length"
        :value="tableData"
        size="small"
        :scrollable="dtScrollable"
        :scrollHeight="dtScrollHeight"
        rowHover
        :row-class="rowClass"
        @row-click="handleRowClick"
        class="text-sm w-full whitespace-nowrap"
      >
        <Column frozen class="w-max" headerClass="cursor-pointer" bodyClass="bg-inherit">
          <template #header>
            <div class="flex items-center gap-2 cursor-pointer" @click="toggleAllPlayers">
              <i
                class="pi pi-angle-right transition-transform duration-200 text-surface-400"
                :class="{ 'rotate-90': allExpanded }"
              />
              <p class="font-semibold">Name</p>
            </div>
          </template>
          <template #body="slotProps">
            <div
              class="flex items-center"
              :class="{
                'pl-4': 'team' in slotProps.data,
                'gap-2': 'rank' in slotProps.data,
              }"
            >
              <template v-if="'rank' in slotProps.data">
                <i
                  class="pi pi-angle-right transition-transform duration-200 text-surface-400"
                  :class="{ 'rotate-90': expandedPlayers.has(slotProps.data.name) }"
                />
                <span v-if="slotProps.data.rank" class="font-bold">{{ slotProps.data.rank }}</span>
                <span>{{ slotProps.data.name }}</span>
              </template>
              <template v-else>
                <div class="flex items-center gap-1">
                  <img
                    :src="slotProps.data.logo_url"
                    class="size-6"
                    :class="{ invert: slotProps.data.team.toLowerCase() === 'utah jazz' }"
                    :alt="slotProps.data.team"
                  />
                  <p>{{ slotProps.data.team }}</p>
                </div>
              </template>
            </div>
          </template>
        </Column>
        <Column field="record" header="Record" bodyClass="text-center">
          <template #body="slotProps">
            <p class="text-center">{{ slotProps.data.record }}</p>
          </template>
        </Column>
        <Column field="record_today" header="Today">
          <template #body="slotProps">
            <template v-if="'result_today' in slotProps.data">
              <Tag
                :value="slotProps.data.result_today"
                :severity="getSeverity(slotProps.data.result_today)"
              />
            </template>
            <template v-else>
              <p>{{ slotProps.data.record_today }}</p>
            </template>
          </template>
        </Column>
        <Column field="record_yesterday" header="Yesterday">
          <template #body="slotProps">
            <div class="text-center">
              <template v-if="'result_yesterday' in slotProps.data">
                <Tag
                  :value="slotProps.data.result_yesterday"
                  :severity="getSeverity(slotProps.data.result_yesterday)"
                />
              </template>
              <template v-else>
                <p>{{ slotProps.data.record_yesterday }}</p>
              </template>
            </div>
          </template>
        </Column>
        <Column field="record_7d" header="Last 7">
          <template #body="slotProps">
            <p>{{ slotProps.data.record_7d }}</p>
          </template>
        </Column>
        <Column field="record_30d" header="Last 30">
          <template #body="slotProps">
            <p>{{ slotProps.data.record_30d }}</p>
          </template>
        </Column>
        <Column field="auction_price" header="Price">
          <template #body="slotProps">
            <p>{{ slotProps.data.auction_price }}</p>
          </template>
        </Column>
      </DataTable>
      <p v-else class="text-surface-400">No leaderboard data available. Please check back later.</p>
    </div>
  </div>
</template>

<style scoped>
:deep(td) {
  padding: 0.15rem;
  height: 1.8rem;
  vertical-align: middle;
}
:deep(.p-datatable-frozen-column) {
  padding-left: 0.75rem;
}
:deep(tr) {
  height: 1.8rem;
}
</style>
