export type LeaderboardItem = {
  rank: number
  name: string
  record: string
  record_today: string
  record_yesterday: string
  record_7d: string
  record_30d: string
  auction_price: string
}

export type TeamBreakdownItem = {
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

export type PoolMetadata = {
  name: string
  description: string
  rules: string
}

export type WinsRaceItem = {
  date: string
  owner: string
  wins: number
}

export type WinsRaceOwner = {
  name: string
}

export interface WinsRaceMilestone {
  slug: string
  date: string
  description: string
}

export type WinsRaceMetadata = {
  owners: WinsRaceOwner[]
  milestones: WinsRaceMilestone[]
}

export type WinsRaceData = {
  data: WinsRaceItem[]
  metadata: WinsRaceMetadata
}
