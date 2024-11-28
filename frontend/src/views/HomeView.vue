<script setup lang="ts">
import { ref, onMounted } from 'vue'

import DataTable from 'primevue/datatable'
import Column from 'primevue/column'

const leaderboard: LeaderboardItem[] = ref<LeaderboardItem[]>([])
const team_breakdown: TeamBreakdownItem[] = ref<TeamBreakdownItem[]>([])
const error: string | null = ref(null)

const leaderboardUrl = `${import.meta.env.VITE_BACKEND_URL}/api/sg/leaderboard`
const teambreakdownUrl = `${import.meta.env.VITE_BACKEND_URL}/api/sg/team_breakdown`

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
  record_today: string
  record_yesterday: string
  record_7d: string
  record_30d: string
}

onMounted(async () => {
  try {
    const response = await fetch(leaderboardUrl)
    const data = await response.json()
    leaderboard.value = data.map((item) => ({
      rank: item.rank,
      name: item.name,
      record: item['W-L'],
      record_today: item['Today'],
      record_yesterday: item['Yesterday'],
      record_7d: item['7d'],
      record_30d: item['30d']
    }))

    const team_breakdown_response = await fetch(teambreakdownUrl)
    const team_breakdown_data = await team_breakdown_response.json()
    team_breakdown.value = team_breakdown_data.map((item) => ({
      name: item.name,
      team: item.team,
      record: item['W-L'],
      record_today: item['Today'],
      record_yesterday: item['Yesterday'],
      record_7d: item['7d'],
      record_7d: item['30d'],
    }))
  } catch (error) {
    console.error('Error fetching leaderboard:', error)
    error.value = `Error fetching leaderboard: ${error}`
  }
})
</script>

<template>
  <main>
    <div class="home">
      <h1>NBA Wins Pool Leaderboard 🏀</h1>
      <DataTable v-if="leaderboard" :value="leaderboard">
        <Column field="rank" header="Rank"></Column>
        <Column field="name" header="Name"></Column>
        <Column field="record" header="Record"></Column>
        <Column field="record_today" header="Today"></Column>
        <Column field="record_yesterday" header="Yesterday"></Column>
        <Column field="record_7d" header="Week"></Column>
        <Column field="record_30d" header="Last 30 days"></Column>
      </DataTable>

      <h1>Team Breakdown</h1>
      <DataTable v-if="team_breakdown" :value="team_breakdown">
        <Column field="name" header="Rank"></Column>
        <Column field="team" header="Name"></Column>
        <Column field="record" header="Record"></Column>
        <Column field="record_today" header="Today"></Column>
        <Column field="record_yesterday" header="Yesterday"></Column>
        <Column field="record_7d" header="Week"></Column>
        <Column field="record_30d" header="Last 30 days"></Column>
      </DataTable>

      <p v-else-if="error">{{ error }}</p>
      <p v-else>Loading...</p>
    </div>
  </main>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 0 auto;
  padding: 1rem;
}

h1 {
  font-size: 2rem;
  margin-bottom: 1rem;
  text-align: center;
}
</style>
