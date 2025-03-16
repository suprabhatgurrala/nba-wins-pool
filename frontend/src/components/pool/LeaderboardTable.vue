<script setup lang="ts">
import { ref, watch } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import type { LeaderboardItem, TeamBreakdownItem } from '@/types/pool'

const props = defineProps<{
  leaderboard: LeaderboardItem[] | null
  teamBreakdown: TeamBreakdownItem[] | null
}>()

const expandedPlayers = ref(new Set<string>())
const tableData = ref<(LeaderboardItem | TeamBreakdownItem)[]>([])
const allExpanded = ref(false)

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
    allExpanded.value = props.leaderboard?.every((p) => expandedPlayers.value.has(p.name)) || false
  }
  updateTableData()
}

const toggleAllPlayers = () => {
  if (allExpanded.value) {
    expandedPlayers.value.clear()
  } else {
    props.leaderboard?.forEach((player) => {
      expandedPlayers.value.add(player.name)
    })
  }
  allExpanded.value = !allExpanded.value
  updateTableData()
}

const updateTableData = () => {
  if (!props.leaderboard) return

  const data: (LeaderboardItem | TeamBreakdownItem)[] = []
  props.leaderboard.forEach((player) => {
    data.push(player)
    if (expandedPlayers.value.has(player.name)) {
      const teams = props.teamBreakdown?.filter((team) => team.name === player.name) || []
      data.push(...teams)
    }
  })
  tableData.value = data
}

watch(
  () => props.leaderboard,
  () => {
    updateTableData()
  },
  { immediate: true },
)
</script>

<template>
  <DataTable v-if="tableData.length" :value="tableData" scrollable>
    <Column frozen>
      <template #header>
        <div class="header-cell">
          <button
            class="expand-button"
            :class="{ expanded: allExpanded }"
            @click.stop="toggleAllPlayers"
            type="button"
          >
            ›
          </button>
          <span>Name</span>
        </div>
      </template>
      <template #body="slotProps">
        <div
          class="name-cell"
          :class="{ 'team-row': 'team' in slotProps.data }"
          @click="'rank' in slotProps.data && togglePlayer(slotProps.data)"
        >
          <template v-if="'rank' in slotProps.data">
            <button
              class="expand-button"
              :class="{ expanded: expandedPlayers.has(slotProps.data.name) }"
              type="button"
            >
              ›
            </button>
            <b>{{ slotProps.data.rank }}</b
            ><span>&nbsp;{{ slotProps.data.name }}</span>
          </template>
          <template v-else>
            <img
              :src="slotProps.data.logo_url"
              class="team-logo"
              :class="`${slotProps.data.team.toLowerCase()}-logo`"
            />
            <span>{{ slotProps.data.team }}</span>
          </template>
        </div>
      </template>
    </Column>
    <Column field="record" header="Record"></Column>
    <Column header="Today">
      <template #body="slotProps">
        <template v-if="'result_today' in slotProps.data">
          <Tag
            :value="slotProps.data.result_today"
            :severity="getSeverity(slotProps.data.result_today)"
          />
        </template>
        <template v-else>
          {{ slotProps.data.record_today }}
        </template>
      </template>
    </Column>
    <Column header="Yesterday">
      <template #body="slotProps">
        <template v-if="'result_yesterday' in slotProps.data">
          <Tag
            :value="slotProps.data.result_yesterday"
            :severity="getSeverity(slotProps.data.result_yesterday)"
          />
        </template>
        <template v-else>
          {{ slotProps.data.record_yesterday }}
        </template>
      </template>
    </Column>
    <Column field="record_7d" header="Last 7"></Column>
    <Column field="record_30d" header="Last 30"></Column>
    <Column field="auction_price" header="Auction Price"></Column>
  </DataTable>
  <p v-else>No leaderboard data available.</p>
</template>

<style scoped>
.name-cell {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.5rem 0.35rem 1.25rem;
  height: 2.25rem;
  cursor: pointer;
  position: relative;
}

.name-cell.team-row {
  padding-left: 0.75rem;
  background: var(--surface-ground);
  cursor: default;
}

.header-cell {
  display: flex;
  align-items: center;
  padding-left: 0.5rem;
  position: relative;
  font-weight: 600;
  justify-content: left;
}

.header-cell .expand-button {
  font-size: 1.25rem;
  font-weight: 450;
  position: absolute;
  left: 0rem;
  width: 0.1rem;
}

.expand-button {
  font-size: 1.25rem;
  width: 1rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s ease;
  color: var(--text-color-secondary);
  background: none;
  border: none;
  padding: 0;
  position: absolute;
  left: 0.15rem;
}

.expand-button.expanded {
  transform: rotate(90deg);
}

.team-logo {
  width: 30px;
  height: 30px;
  object-fit: contain;
}

.uta-logo {
  filter: invert(100%);
}

@media (max-width: 768px) {
  .header-cell .expand-button {
    font-size: 1.25rem;
    position: absolute;
    left: -0.1rem;
    width: 0rem;
  }
}
</style>

<style>
.p-datatable {
  max-width: 100%;
  white-space: nowrap;
}

/* center text horizontally within cells */
.p-datatable-tbody > tr > td,
.p-datatable-thead > tr > th {
  text-align: center !important;
}

/* make column header take full width for centering */
.p-datatable-column-header-content {
  display: block !important;
}

/* explicitly specify striped rows due to frozen column not being striped */
.p-row-odd > td {
  background: var(--p-datatable-row-striped-background) !important;
}

.p-datatable .p-datatable-tbody > tr > td {
  padding: 0.25rem 0.5rem;
}

/* Mobile adjustments */
@media (max-width: 768px) {
  .p-datatable {
    font-size: 1.4rem;
  }

  /* first 3 columns are full width of viewport */
  .p-datatable-header-cell:nth-child(-n + 3) {
    min-width: calc((100vw - 2rem) / 3);
  }

  .p-datatable .p-datatable-tbody > tr > td {
    padding: 0.6rem 0.25rem;
  }
}
</style>
