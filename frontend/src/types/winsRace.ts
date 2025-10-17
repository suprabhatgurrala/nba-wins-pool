import type { WinsRaceMilestone } from '@/types/pool'

export interface WinsRaceRoster {
  name: string
}

export interface WinsRaceItem {
  date: string
  roster: string
  wins: number
}

export interface WinsRaceMetadata {
  rosters: WinsRaceRoster[]
  milestones: WinsRaceMilestone[]
}

export interface WinsRaceData {
  data: WinsRaceItem[]
  metadata: WinsRaceMetadata
}
