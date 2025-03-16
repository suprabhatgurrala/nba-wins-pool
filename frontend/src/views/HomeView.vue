<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import LeaderboardTable from '@/components/pool/LeaderboardTable.vue'
import WinsRaceChart from '@/components/pool/WinsRaceChart.vue'
import { useLeaderboardData } from '@/composables/useLeaderboardData'
import { useWinsRaceData } from '@/composables/useWinsRaceData'
import { usePoolMetadata } from '@/composables/usePoolMetadata'

const route = useRoute()
const poolId = route.params.poolId as string

const {
  leaderboard,
  teamBreakdown,
  error: leaderboardError,
  loading: leaderboardLoading,
  fetchLeaderboardData,
} = useLeaderboardData(poolId)

const {
  winsRaceData,
  error: chartError,
  loading: chartLoading,
  fetchWinsRaceData,
} = useWinsRaceData(poolId)

const {
  poolMetadata,
  error: metadataError,
  loading: metadataLoading,
  fetchPoolMetadata,
} = usePoolMetadata(poolId)

onMounted(() => {
  fetchLeaderboardData()
  fetchWinsRaceData()
  fetchPoolMetadata()
})
</script>

<template>
  <main>
    <div class="home">
      <span>
        <h1 class="title">🏀 NBA Wins Pool 🏆</h1>
        <h3 v-if="!metadataLoading" class="pool-name">
          <i>{{ poolMetadata?.name }}</i>
        </h3>
        <p v-else-if="metadataError">{{ metadataError }}</p>
        <p v-else>Loading pool metadata...</p>
      </span>
      <h1>Leaderboard</h1>

      <LeaderboardTable
        v-if="!leaderboardLoading"
        :leaderboard="leaderboard"
        :team-breakdown="teamBreakdown"
      />
      <p v-else-if="leaderboardError">{{ leaderboardError }}</p>
      <p v-else>Loading leaderboard...</p>

      <h1>Wins</h1>

      <WinsRaceChart v-if="!chartLoading" :wins-race-data="winsRaceData" />
      <p v-else-if="chartError">{{ chartError }}</p>
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
</style>
