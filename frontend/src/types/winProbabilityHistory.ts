import type { WinsRaceMilestone } from '@/types/pool'

export interface WinProbabilityHistory {
  rosters: { id: string; name: string }[]
  timestamps: number[]
  series: Record<string, (number | null)[]>
  milestones: WinsRaceMilestone[]
}
