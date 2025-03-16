<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useColorMode } from '@vueuse/core'
import { use } from 'echarts/core'

import {
  DatasetComponent,
  TooltipComponent,
  TransformComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent,
  ToolboxComponent,
} from 'echarts/components'

import type { EChartsOption, SeriesOption } from 'echarts'

import { LineChart } from 'echarts/charts'
import { LabelLayout, UniversalTransition } from 'echarts/features'
import { SVGRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'

import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import Card from 'primevue/card'

// Register ECharts components and theme
use([
  DatasetComponent,
  DataZoomComponent,
  TooltipComponent,
  GridComponent,
  TransformComponent,
  LegendComponent,
  LineChart,
  SVGRenderer,
  LabelLayout,
  UniversalTransition,
  ToolboxComponent,
])

const leaderboard = ref<LeaderboardItem[] | null>(null)
const team_breakdown = ref<TeamBreakdownItem[] | null>(null)
const pool_metadata = ref<PoolMetadata | null>(null)
const error = ref<string | null>(null)
const winsChartData = ref<WinsTimeseriesData | null>(null)
const chartOption = ref<EChartsOption>({})

const colorMode = useColorMode()

const route = useRoute()
const poolId = route.params.poolId

const leaderboardUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/leaderboard`
const poolMetadataUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/metadata`
const winsTimeseriesUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/wins_timeseries`

const expandedPlayers = ref(new Set())
const tableData = ref<(LeaderboardItem | TeamBreakdownItem)[]>([])
const allExpanded = ref(false)

type LeaderboardItem = {
  rank: number
  name: string
  record: string
  record_today: string
  record_yesterday: string
  record_7d: string
  record_30d: string
  auction_price: string
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
  auction_price: string
}

type PoolMetadata = {
  name: string
  description: string
  rules: string
}

type WinsTimeseriesItem = {
  date: string
  owner: string
  wins: number
}

type WinsTimeseriesOwner = {
  name: string
}

type WinsTimeseriesMetadata = {
  owners: WinsTimeseriesOwner[]
}

type WinsTimeseriesData = {
  data: WinsTimeseriesItem[]
  metadata: WinsTimeseriesMetadata
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

const updateChartData = () => {
  if (!winsChartData.value) return

  const rawData = winsChartData.value.data
  const metadata = winsChartData.value.metadata
  const dataset = [
    { id: 'raw', source: rawData },
    ...metadata.owners.map((owner) => ({
      id: owner.name,
      fromDatasetId: 'raw',
      transform: {
        type: 'filter',
        config: { dimension: 'owner', value: owner.name },
      },
    })),
  ]
  const series: SeriesOption[] = metadata.owners.map((owner) => ({
    type: 'line',
    name: owner.name,
    encode: {
      x: 'date',
      y: 'wins',
    },
    datasetId: owner.name,
    showSymbol: false,
    emphasis: { focus: 'series' },
  }))

  chartOption.value = {
    dataset: dataset,
    series: series,
    backgroundColor: 'transparent',
    tooltip: {
      // override to empty values to let p-card handle styling
      backgroundColor: '',
      borderWidth: 0,
      textStyle: undefined,
      order: 'valueDesc',
      trigger: 'axis',
      className: 'p-card',
    },
    legend: {
      icon: 'circle',
      top: 'top',
      textStyle: {
        fontSize: 14,
      },
    },
    grid: {
      left: 'left',
      right: 0,
      top: '15%',
      bottom: 60,
      containLabel: true,
    },
    dataZoom: {
      type: 'slider',
      filterMode: 'weakFilter',
      minSpan: 7,
      left: 'center',
      moveHandleSize: 15,
      labelFormatter: '',
    },
    toolbox: {
      itemSize: 20,
      // orient: 'vertical',
      left: 'right',
      // top: 'bottom',
      feature: {
        dataZoom: {
          show: true,
          title: {
            zoom: 'Zoom Select',
            back: 'Undo Zoom',
          },
          yAxisIndex: false,
        },
        restore: {
          show: true,
          title: 'Reset',
        },
        saveAsImage: {
          show: true,
          title: 'Save',
          excludeComponents: ['toolbox', 'dataZoom'],
        },
      },
    },
    xAxis: {
      type: 'category',
      axisLine: {
        show: false,
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        margin: 10,
        formatter: (value: string) => {
          const date = new Date(`${value}T00:00:00`)
          return date.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' })
        },
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
    },
    media: [
      {
        query: {
          maxWidth: 500,
        },
        option: {
          toolbox: {
            show: false,
            top: 'bottom',
            left: 'center',
          },
          dataZoom: {
            throttle: 50,
            startValue: 100,
            minValueSpan: 14,
          },
          legend: {
            width: '75%',
            textStyle: {
              fontSize: 17,
            },
          },
          grid: {},
        },
      },
    ],
  }
}

onMounted(async () => {
  try {
    const metadata_response = await fetch(poolMetadataUrl)
    pool_metadata.value = await metadata_response.json()

    const leaderboard_response = await fetch(leaderboardUrl)
    const data = await leaderboard_response.json()

    leaderboard.value = data['owner'].map((item: any) => ({
      rank: item.rank,
      name: item.name,
      auction_price: '$' + item.auction_price,
      record: item['wins'] + '-' + item['losses'],
      record_today: item['wins_today'] + '-' + item['losses_today'],
      record_yesterday: item['wins_yesterday'] + '-' + item['losses_yesterday'],
      record_7d: item['wins_last7'] + '-' + item['losses_last7'],
      record_30d: item['wins_last30'] + '-' + item['losses_last30'],
    }))

    const team_breakdown_data = data['team']
    team_breakdown.value = team_breakdown_data.map((item: any) => ({
      name: item.name,
      team: item.team,
      logo_url: item.logo_url,
      record: item['wins'] + '-' + item['losses'],
      auction_price: '$' + item.auction_price,
      result_today: item['result_today'],
      result_yesterday: item['result_yesterday'],
      record_7d: item['wins_last7'] + '-' + item['losses_last7'],
      record_30d: item['wins_last30'] + '-' + item['losses_last30'],
    }))

    // Initialize tableData with leaderboard
    updateTableData()

    // Fetch the wins timeseries data
    const wins_ts_response = await fetch(winsTimeseriesUrl)
    winsChartData.value = await wins_ts_response.json()
    updateChartData()
    window.addEventListener('resize', updateChartData)
  } catch (error: any) {
    console.error('Error fetching data:', error)
    error.value = `Error fetching data: ${error}`
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', updateChartData)
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
        <Column field="auction_price" header="Auction Price"></Column>
      </DataTable>
      <p v-else-if="error">{{ error }}</p>
      <p v-else>Loading...</p>

      <h1>Wins</h1>

      <Card v-if="winsChartData">
        <template #content>
          <v-chart :option="chartOption" :theme="colorMode" class="wins-chart" autoresize />
        </template>
      </Card>
      <p v-else>Loading chart data...</p>
    </div>
  </main>
</template>

<style>
.home {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 0 auto;
  padding: 0 0.5rem 1rem;
}

.title {
  margin: 0;
  padding-top: 1rem;
  padding-bottom: 0rem;
}

h1 {
  font-size: 2rem;
  text-align: center;
  min-width: 300px;
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

.team-logo {
  width: 30px;
  height: 30px;
  object-fit: contain;
}

/* Utah Jazz logo is all black, invert */
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

.p-datatable .p-datatable-tbody > tr > td {
  padding: 0.25rem 0.5rem;
}

/* Wins Chart styles */
.wins-chart {
  width: 80vw;
  min-height: 40vh;
  max-width: 700px;
}

.chart-tooltip {
  background-color: var(--p-card-background);
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

  .header-cell .expand-button {
    font-size: 1.25rem;
    position: absolute;
    left: -0.1rem;
    width: 0rem;
  }

  .wins-chart {
    min-height: 55vh;
  }
}
</style>
