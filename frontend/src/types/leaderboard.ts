// Leaderboard response types

export interface RosterRow {
  rank: number
  name: string
  wins: number
  losses: number
  wins_today: number
  losses_today: number
  wins_yesterday: number
  losses_yesterday: number
  wins_last7: number
  losses_last7: number
  wins_last30: number
  losses_last30: number
  auction_price: number
}

export interface TeamRow {
  name: string
  team: string
  logo_url: string
  wins: number
  losses: number
  today_result: string
  yesterday_result: string
  wins_today: number
  losses_today: number
  wins_last7: number
  losses_last7: number
  wins_last30: number
  losses_last30: number
  auction_price: number
}

export interface LeaderboardResponse {
  roster: RosterRow[]
  team: TeamRow[]
}
