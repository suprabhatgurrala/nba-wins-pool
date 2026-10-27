export interface PoolHistoryStanding {
  name: string
  wins: number
  losses: number
}

export interface PoolHistorySeason {
  season: string
  champions: PoolHistoryStanding[]
  runner_up: PoolHistoryStanding | null
  auction_status: 'not_started' | 'active' | 'completed' | null
  in_progress: boolean
}

export interface PoolHistoryParticipant {
  name: string
  seasons_played: number
  championships: number
  average_wins: number | null
  average_finish: number | null
  average_projected_wins: number | null
}

export interface PoolHistory {
  seasons: PoolHistorySeason[]
  participants: PoolHistoryParticipant[]
  wins_normalized: boolean
  baseline_team_count: number | null
}

export interface ParticipantSeasonTeam {
  name: string
  abbreviation: string
  logo_url: string
  wins: number
  losses: number
  auction_price: number | null
  projected_wins: number | null
}

export interface ParticipantHistorySeason {
  season: string
  wins: number
  losses: number
  rank: number | null
  rank_tied: boolean
  in_progress: boolean
  teams: ParticipantSeasonTeam[]
}

export interface ParticipantHistory {
  name: string
  seasons: ParticipantHistorySeason[]
  blurb: string | null
}
