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

export type AuctionDataItem = {
  team: string
  conf: string
  reg_season_wins: number
  over_reg_season_wins_prob: number
  make_playoffs_prob: number
  conf_prob: number
  title_prob: number
  total_expected_wins: number
  auction_value: number
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
