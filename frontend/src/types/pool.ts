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
  team_id?: string
  logo_url: string
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

export type AuctionOverviewBid = {
  bidder_name: string
  amount: number
}

export type AuctionOvervieTeam = {
  id: string
  name: string
  abbreviation: string
  logo_url: string
}

export type AuctionOverviewPool = {
  id: string
  name: string
}

export type AuctionOverviewLot = {
  id: string
  status: string
  team: AuctionOvervieTeam
  winning_bid: AuctionOverviewBid | undefined
}

export type AuctionOverviewParticipant = {
  id: string
  name: string
  budget: string // double check
  lots_won: AuctionOverviewLot[]
}

export type AuctionOverview = {
  id: string
  pool: AuctionOverviewPool
  season: string
  status: string
  lots: AuctionOverviewLot[]
  participants: AuctionOverviewParticipant[]
  current_lot: AuctionOverviewLot | undefined
  started_at: string | undefined
  completed_at: string | undefined
  max_lots_per_participant: number
  // check decimal
  min_bid_increment: string
  starting_participant_budget: string
}

// === New shared list/summary types ===
export interface Pool {
  id: string
  slug: string
  name: string
  description?: string | null
  rules?: string | null
  created_at: string
}

export interface PoolCreate {
  slug: string
  name: string
  description?: string | null
}

export interface PoolUpdate {
  name?: string
  description?: string | null
}

export type AuctionStatus = 'not_started' | 'active' | 'completed'

export interface PoolRosterTeamOverview {
  id: string
  name: string
  created_at: string
}

export interface PoolRosterSlotOverview {
  id: string
  name: string
  team: PoolRosterTeamOverview
  created_at: string
}

export interface PoolRosterOverview {
  id: string
  season: string
  name: string
  slots: PoolRosterSlotOverview[]
  created_at: string
}

export interface Roster {
  id: string
  pool_id: string
  season: string
  name: string
  created_at: string
}

export interface RosterCreate {
  name: string
  pool_id: string
  season: string
}

export interface RosterUpdate {
  name?: string
}

export type RosterQuery = {
  pool_id?: string
  season?: string
}

export interface PoolOverview {
  id: string
  slug: string
  name: string
  season: string
  description?: string | null
  rules?: string | null
  rosters: PoolRosterOverview[]
  created_at: string
}

export interface Auction {
  id: string
  pool_id: string
  season: string
  status: AuctionStatus
  max_lots_per_participant: number
  min_bid_increment: string
  starting_participant_budget: string
  created_at: string
  started_at?: string | null
  completed_at?: string | null
}

// Payloads for creating and updating auctions
export interface AuctionCreate {
  pool_id: string
  season: string
  max_lots_per_participant: number
  // Backend accepts Decimal; we send numbers and receive strings on read
  min_bid_increment: number
  starting_participant_budget: number
}

export interface AuctionUpdate {
  status?: AuctionStatus
  max_lots_per_participant?: number
  min_bid_increment?: number
  starting_participant_budget?: number
}
