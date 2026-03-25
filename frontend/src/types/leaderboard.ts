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
  expected_wins?: number
}

export interface TeamRow {
  name: string
  team: string
  abbreviation: string
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
  expected_wins?: number
}

export interface LeaderboardResponse {
  roster: RosterRow[]
  team: TeamRow[]
}

export interface TodayGame {
  game_id: string
  game_url: string | null
  status: 1 | 2 | 3 // 1=PREGAME, 2=INGAME, 3=FINAL
  status_text: string
  game_clock: string
  home_team_id: number | null
  home_team_name: string
  home_team_tricode: string
  home_team_logo_url: string | null
  home_score: number | null
  home_owner: string | null
  home_owner_wins: number | null
  home_owner_today_wins: number | null
  home_owner_today_losses: number | null
  away_team_id: number | null
  away_team_name: string
  away_team_tricode: string
  away_team_logo_url: string | null
  away_score: number | null
  away_owner: string | null
  away_owner_wins: number | null
  away_owner_today_wins: number | null
  away_owner_today_losses: number | null
}
