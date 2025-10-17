// Utility to compute the current NBA season string in format YYYY-YY
// Example: for Oct 2024 -> "2024-25"
export function getCurrentSeason(date: Date = new Date()): string {
  const year = date.getUTCFullYear()
  const month = date.getUTCMonth() + 1 // 1-12
  // NBA season starts in Oct; treat Aug (8) and later as upcoming season start year
  const startYear = month >= 8 ? year : year - 1
  const nextYY = String((startYear + 1) % 100).padStart(2, '0')
  return `${startYear}-${nextYY}`
}

function parseSeasonStart(season: string): number {
  const m = season.match(/^(\d{4})-\d{2}$/)
  if (!m) throw new Error(`Invalid season format: ${season}`)
  return parseInt(m[1], 10)
}

export function getPrevSeason(season: string): string {
  const start = parseSeasonStart(season) - 1
  const nextYY = String((start + 1) % 100).padStart(2, '0')
  return `${start}-${nextYY}`
}

export function getNextSeason(season: string): string {
  const start = parseSeasonStart(season) + 1
  const nextYY = String((start + 1) % 100).padStart(2, '0')
  return `${start}-${nextYY}`
}

export function getRecentSeasons(count: number = 5): string[] {
  const current = getCurrentSeason()
  const seasons: string[] = [current]
  let season = current
  for (let i = 1; i < count; i++) {
    season = getPrevSeason(season)
    seasons.push(season)
  }
  return seasons
}
