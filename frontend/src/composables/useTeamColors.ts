import { ref } from 'vue'

type MatchupColors = Record<string, Record<string, { away: string; home: string }>>

const colors = ref<MatchupColors | null>(null)
let fetchPromise: Promise<void> | null = null

async function fetchColors(): Promise<void> {
  const res = await fetch('/api/team-colors')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  colors.value = await res.json()
}

export function useTeamColors() {
  if (!fetchPromise) {
    fetchPromise = fetchColors().catch((e) => {
      console.error('Failed to load team colors:', e)
      fetchPromise = null
    })
  }

  function getColors(awayTricode: string, homeTricode: string): { away: string; home: string } {
    return colors.value?.[awayTricode]?.[homeTricode] ?? { away: '#6b7280', home: '#6b7280' }
  }

  return { getColors }
}
