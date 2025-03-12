<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'

import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import Chart from 'primevue/chart'
import Card from 'primevue/card'

// Import and register Chart.js annotation plugin
import { Chart as ChartJS } from 'chart.js'
import annotationPlugin from 'chartjs-plugin-annotation'
// Import types from chartjs-plugin-annotation
import type { LineAnnotationOptions } from 'chartjs-plugin-annotation'

ChartJS.register(annotationPlugin)

const leaderboard = ref<LeaderboardItem[] | null>(null)
const team_breakdown = ref<TeamBreakdownItem[] | null>(null)
const pool_metadata = ref<PoolMetadata | null>(null)
const race_plot_data = ref<any[] | null>(null)
const error = ref<string | null>(null)

const route = useRoute()
const poolId = route.params.poolId

const leaderboardUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/leaderboard`
const teambreakdownUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/team_breakdown`
const poolMetadataUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/metadata`
const racePlotUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/race_plot`

const expandedPlayers = ref(new Set())
const tableData = ref<(LeaderboardItem | TeamBreakdownItem)[]>([])
const allExpanded = ref(false)

// Chart.js configuration
const chartOptions = ref({
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'bottom',
      labels: {
        boxHeight: 7,
        usePointStyle: true,
        font: {
          size: 16,
        },
      },
    },
    tooltip: {
      usePointStyle: true,
      boxPadding: 3,
      titleFont: {
        size: 14,
      },
      bodyFont: {
        size: 13,
      },
      itemSort: (a: { parsed: { y: number } }, b: { parsed: { y: number } }) => b.parsed.y - a.parsed.y,
    },
    annotation: {
      annotations: {} as Record<string, LineAnnotationOptions> // Use imported type
    }
  },
  scales: {
    x: {
      border: {
        display: false,
      },
      grid: {
        display: false,
      },
      ticks: {
        maxTicksLimit: 8,
        font: {
          size: 13,
        },
      },
    },
    y: {
      border: {
        display: false,
      },
      grid: {
        display: false,
      },
      title: {
        display: false,
      },
      min: 0,
    },
  },
  elements: {
    line: {
      borderWidth: 3,
    },
    point: {
      radius: 0,
      hoverRadius: 5,
    },
  },
  interaction: {
    mode: 'index',
    intersect: false,
  },
})

const chartData = computed(() => {
  if (!race_plot_data.value || race_plot_data.value.length === 0) {
    return { labels: [], datasets: [] }
  }

  // Extract dates for x-axis
  const allData = race_plot_data.value

  let filteredData = allData

  // For category scale, we just need the date strings
  const labels = filteredData.map((item) => {
    const date = new Date(item.date + 'T00:00:00Z')
    return date.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', timeZone: 'UTC' })
  })

  // Get all owner names (excluding the 'date' property)
  const owners = Object.keys(race_plot_data.value[0]).filter((key) => key !== 'date')

  // Get the most recent data for sorting
  const mostRecentData = filteredData[filteredData.length - 1]

  // Create dataset for each owner and sort by current win totals
  const datasets = owners
    .map((owner) => {
      return {
        label: owner,
        data: filteredData.map((item) => item[owner] || 0),
      }
    })
    .sort((a, b) => mostRecentData[b.label] - mostRecentData[a.label]) // Sort by most recent win total (descending)

  // Add milestone annotations if available
  addMilestoneAnnotations()
  
  return { labels, datasets }
})

// Function to add milestone annotations to the chart
const addMilestoneAnnotations = () => {
  // Clear any existing annotations
  chartOptions.value.plugins.annotation.annotations = {}
  
  // If there's no data or no milestones, return early
  if (!race_plot_data.value?.length || !pool_metadata.value?.milestones) return
  
  const dataDateStrings = race_plot_data.value.map(item => item.date)
  const startDate = new Date(dataDateStrings[0])
  const endDate = new Date(dataDateStrings[dataDateStrings.length - 1])
  
  // Process each milestone
  Object.entries(pool_metadata.value.milestones).forEach(([id, milestone]) => {
    const milestoneDate = new Date(milestone.date)
    
    // Only add milestone if it falls within the date range of our data
    if (milestoneDate >= startDate && milestoneDate <= endDate) {
      // Find the closest data point to this milestone date
      const closestDateIndex = dataDateStrings.findIndex(dateStr => {
        return new Date(dateStr) >= milestoneDate
      })
      
      if (closestDateIndex >= 0) {
        // Get the formatted date string that matches our labels
        const formattedDate = new Date(dataDateStrings[closestDateIndex] + 'T00:00:00Z')
          .toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', timeZone: 'UTC' })
        
        // Add the vertical line annotation
        chartOptions.value.plugins.annotation.annotations[id] = {
          xMin: formattedDate,
          xMax: formattedDate,
          borderColor: 'rgba(150, 150, 150, 0.7)',
          borderWidth: 2,
          borderDash: [6, 3],
          label: {
            display: true,
            content: milestone.description,
            position: 'start',
            backgroundColor: 'rgba(150, 150, 150, 0.7)',
            color: '#ffffff',
            font: {
              size: 11
            },
            padding: 4
          }
        }
      }
    }
  })
}

type LeaderboardItem = {
  rank: number
  name: string
  record: string
  record_today: string
  record_yesterday: string
  record_7d: string
  record_30d: string
}

type TeamBreakdownItem = {
  name: string
  team: string
  logo_url: string
  record: string
  result_today: string
  result_yesterday: string
  record_7d: string
  record_30d: string
}

type PoolMetadata = {
  name: string
  description: string
  rules: string
  milestones?: {
    [key: string]: {
      date: string
      description: string
    }
  }
}

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
      const teams = team_breakdown.value?.filter((team) => team.name === player.name) || []
      data.push(...teams)
    }
  })
  tableData.value = data
}

onMounted(async () => {
  try {
    const metadata_response = await fetch(poolMetadataUrl)
    pool_metadata.value = await metadata_response.json()

    const leaderboard_response = await fetch(leaderboardUrl)
    const data = await leaderboard_response.json()
    leaderboard.value = data.map((item: any) => ({
      rank: item.rank,
      name: item.name,
      record: item['W-L'],
      record_today: item['Today'],
      record_yesterday: item['Yesterday'],
      record_7d: item['7d'],
      record_30d: item['30d'],
    }))

    const team_breakdown_response = await fetch(teambreakdownUrl)
    const team_breakdown_data = await team_breakdown_response.json()
    team_breakdown.value = team_breakdown_data.map((item: any) => ({
      name: item.name,
      team: item.team,
      logo_url: item.logo_url,
      record: item['W-L'],
      result_today: item['Today'],
      result_yesterday: item['Yesterday'],
      record_7d: item['7d'],
      record_30d: item['30d'],
    }))

    // Get race plot data without sampling factor
    const race_plot_response = await fetch(`${racePlotUrl}`)
    race_plot_data.value = await race_plot_response.json()

    // Initialize tableData with leaderboard
    updateTableData()

    // After loading all data, update annotations
    addMilestoneAnnotations()
    
  } catch (error: any) {
    console.error('Error fetching data:', error)
    error.value = `Error fetching data: ${error}`
  }
})
</script>

<template>
  <main>
    <div class="home">
      <span>
        <h1 class="title">🏀 NBA Wins Pool 🏆</h1>
        <h3 class="pool-name">
          <i>{{ pool_metadata?.name }}</i>
        </h3>
      </span>
      <h1>Leaderboard</h1>
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
      </DataTable>
      <p v-else-if="error">{{ error }}</p>
      <p v-else>Loading leaderboard...</p>

      <h1 class="section-title">Wins</h1>
      <Card v-if="race_plot_data && race_plot_data.length > 0">
        <template #content>
          <Chart type="line" :data="chartData" :options="chartOptions" class="chart-container" />
        </template>
      </Card>
      <p v-else-if="race_plot_data && race_plot_data.length === 0">
        No game data available yet for wins chart.
      </p>
      <p v-else>Loading chart data...</p>
    </div>
  </main>
</template>

<style>
/* Base layout */
.home {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 0 auto;
  padding: 0 0.5rem 1rem;
}

/* Typography */
h1 {
  font-size: 2rem;
  text-align: center;
  min-width: 300px;
}

.title {
  margin: 0;
  padding-top: 1rem;
  padding-bottom: 0;
}

.pool-name {
  font-size: 1rem;
  text-align: center;
  font-variant: caps;
  font-weight: 400;
  margin: 0 0;
}

.p-datatable {
  max-width: 100%;
  white-space: nowrap;
}

.p-datatable-tbody > tr > td,
.p-datatable-thead > tr > th {
  text-align: center !important;
}

.p-datatable-column-header-content {
  display: block !important;
}

.p-row-odd > td {
  background: var(--p-datatable-row-striped-background) !important;
}

.team-logo {
  width: 30px;
  height: 30px;
  object-fit: contain;
}

.uta-logo {
  filter: invert(100%);
}

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

/* Expand button styling */
.expand-button {
  font-size: 1.25rem;
  background: none;
  border: none;
  padding: 0;
  color: var(--text-color-secondary);
  transition: transform 0.2s ease;
  position: absolute;
}

.header-cell .expand-button {
  left: 0rem;
  width: 0.1rem;
}

.name-cell .expand-button {
  left: 0.15rem;
  width: 1rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.expand-button.expanded {
  transform: rotate(90deg);
}

.chart-container {
  width: 80vw;
  min-height: 35vh;
  max-width: 700px;
}

/* Mobile adjustments - simplified without legend-specific styles */
@media (max-width: 768px) {
  .p-datatable {
    font-size: 1.4rem;
  }

  .p-datatable-header-cell:nth-child(-n + 3) {
    min-width: calc((100vw - 2rem) / 3);
  }

  .p-datatable .p-datatable-tbody > tr > td {
    padding: 0.6rem 0.25rem;
  }

  .header-cell .expand-button {
    left: -0.1rem;
    width: 0;
  }

  .chart-container {
    min-height: 50vh;
  }
}
</style>
