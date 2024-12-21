<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'

import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'

const leaderboard = ref<LeaderboardItem[] | null>(null)
const team_breakdown = ref<TeamBreakdownItem[] | null>(null)
const pool_metadata = ref<PoolMetadata | null>(null)
const error = ref<string | null>(null)

const route = useRoute()
const poolId = route.params.poolId

const leaderboardUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/leaderboard`
const teambreakdownUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/team_breakdown`
const poolMetadataUrl = `${import.meta.env.VITE_BACKEND_URL}/api/pool/${poolId}/metadata`

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
  } catch (error: any) {
    console.error('Error fetching leaderboard:', error)
    error.value = `Error fetching leaderboard: ${error}`
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
      <DataTable v-if="leaderboard" :value="leaderboard" scrollable >
        <Column header="Name" style="text-align: left !important;" frozen>
          <template #body="slotProps">
            <div style="text-align: left;">
              <b>{{ slotProps.data.rank }}</b>&nbsp;&nbsp;<span>{{ slotProps.data.name }}</span>
            </div>
          </template>
        </Column>
        <Column field="record" header="Record"></Column>
        <Column field="record_today" header="Today"></Column>
        <Column field="record_yesterday" header="Yesterday"></Column>
        <Column field="record_7d" header="Last 7"></Column>
        <Column field="record_30d" header="Last 30"></Column>
      </DataTable>
      <p v-else-if="error">{{ error }}</p>
      <p v-else>Loading...</p>

      <h1>Team Breakdown</h1>
      <DataTable
        v-if="team_breakdown"
        :value="team_breakdown"
        stripedRows
        scrollable
        rowGroupMode="rowspan"
        groupRowsBy="name"
      >
        <Column field="name" header="Name"></Column>
        <Column header="Team" frozen>
          <template #body="slotProps">
            <div class="multi-cell">
              <img :src="slotProps.data.logo_url" class="team-logo" :class="`${slotProps.data.team.toLowerCase()}-logo`"/>
              <span>{{ slotProps.data.team }}</span>
            </div>
          </template>
        </Column>
        <Column field="record" header="Record"></Column>
        <Column header="Today">
          <template #body="slotProps">
              <Tag :value="slotProps.data.result_today" :severity="getSeverity(slotProps.data.result_today)" />
          </template>
        </Column>
        <Column field="result_yesterday" header="Yesterday">
          <template #body="slotProps">
              <Tag :value="slotProps.data.result_yesterday" :severity="getSeverity(slotProps.data.result_yesterday)" />
          </template>
        </Column>
        <Column field="record_7d" header="Last 7"></Column>
        <Column field="record_30d" header="Last 30"></Column>
      </DataTable>
      <p v-else-if="error">{{ error }}</p>
      <p v-else>Loading...</p>
    </div>
  </main>
</template>

<style>
.home {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 0 auto;
  padding: 0 0.5rem;
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
.p-datatable-tbody > tr > td, .p-datatable-thead > tr > th {
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

@media (max-width: 768px) {
  .p-datatable {
    font-size: 1.4rem;
  }

  /* first 3 columns are full width of viewport */
  .p-datatable-header-cell:nth-child(-n+3) {
    min-width: calc((100vw - 2rem) / 3);
  }

  p {
    font-size: 1.4rem;
  }
}

.multi-cell {
  display: flex;
  justify-content: center;
  align-items: center; /* Vertically centers content */
  gap: 8px; /* Add space between logo and text */
}

.team-logo {
  align-items: center;
  width: 32px;
}

/* Utah Jazz logo is all black, invert */
.uta-logo {
  filter: invert(100%);
}
</style>
