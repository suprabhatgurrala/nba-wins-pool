export interface PoolHistoryStanding {
  name: string
  wins: number
  losses: number
}

export interface PoolHistorySeason {
  season: string
  champion: PoolHistoryStanding | null
  runner_up: PoolHistoryStanding | null
}

export interface PoolHistoryParticipant {
  name: string
  seasons_played: number
  championships: number
  average_wins: number
  average_finish: number
}

export interface PoolHistory {
  seasons: PoolHistorySeason[]
  participants: PoolHistoryParticipant[]
  wins_normalized: boolean
  baseline_team_count: number | null
}
