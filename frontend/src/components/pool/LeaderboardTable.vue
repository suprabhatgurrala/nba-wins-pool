<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import BaseScalableTable from '@/components/common/BaseScalableTable.vue'
import type { RosterRow, TeamRow } from '@/types/leaderboard'
import type { LeaderboardItem, TeamBreakdownItem } from '@/types/pool'

const props = defineProps<{
  roster: RosterRow[] | null
  team: TeamRow[] | null
  density?: 'S' | 'M' | 'L'
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

// Determine if table is empty
const isEmpty = computed(() => !tableData.value.length)

// DataTable is scrollable when maxHeight is set
const dtScrollable = computed(() => !!props.maxHeight)
</script>

<template>
  <BaseScalableTable
    :density="props.density"
    :maxHeight="props.maxHeight"
    :isEmpty="isEmpty"
  >
    <template #default="{ scrollHeight }">
      <DataTable
        v-if="tableData.length"
        :value="tableData"
        size="small"
        :scrollable="dtScrollable"
        :scrollHeight="scrollHeight"
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
      <p v-else class="text-surface-400 p-4">No leaderboard data available. Please check back later.</p>
    </template>
  </BaseScalableTable>
</template>

<style scoped>
/* LeaderboardTable uses .scalable-table class from BaseScalableTable for common scaling */
/* No custom overrides needed - all defaults work perfectly! */
</style>
