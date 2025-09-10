import { ref } from 'vue'
import type { LeaderboardItem, TeamBreakdownItem } from '@/types/pool'

export function useLeaderboardData(poolId: string) {
  const leaderboard = ref<LeaderboardItem[] | null>(null)
  const teamBreakdown = ref<TeamBreakdownItem[] | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(true)

  const baseUrl = import.meta.env.VITE_BACKEND_URL
  const leaderboardUrl = `${baseUrl}/api/pool/${poolId}/leaderboard`

  const fetchLeaderboardData = async () => {
    loading.value = true
    error.value = null

    try {
      const response = await fetch(leaderboardUrl)
      const data = await response.json()

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

      const teamBreakdownData = data['team']
      teamBreakdown.value = teamBreakdownData.map((item: any) => ({
        name: item.name,
        team: item.team,
        logo_url: item.logo_url,
        record: item['wins'] + '-' + item['losses'],
        auction_price: '$' + item.auction_price,
        result_today: item['today_result'],
        result_yesterday: item['yesterday_result'],
        record_7d: item['wins_last7'] + '-' + item['losses_last7'],
        record_30d: item['wins_last30'] + '-' + item['losses_last30'],
      }))
    } catch (err: any) {
      console.error('Error fetching leaderboard data:', err)
      error.value = `Error fetching leaderboard data: ${err.message}`
    } finally {
      loading.value = false
    }
  }

  return {
    leaderboard,
    teamBreakdown,
    error,
    loading,
    fetchLeaderboardData,
  }
}
