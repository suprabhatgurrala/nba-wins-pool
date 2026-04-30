<script setup lang="ts">
import { computed, ref } from 'vue'
import Button from 'primevue/button'
import type { RosterRow, TeamRow } from '@/types/leaderboard'
import SimulationMethodologyDialog from './SimulationMethodologyDialog.vue'

const props = defineProps<{
  roster: RosterRow[]
  team: TeamRow[]
}>()

const hasSimData = computed(() => props.roster.some((r) => r.expected_wins != null))

interface ProjectionRow {
  rank: number
  name: string
  record: string
  currentWins: number
  currentLosses: number
  projectedWins: number | null
  winProbability: number | null
  teams: TeamProjection[]
}

interface TeamProjection {
  name: string
  abbreviation: string
  logo_url: string
  record: string
  currentWins: number
  projectedWins: number | null
}

const rows = computed<ProjectionRow[]>(() => {
  const teamsByOwner = new Map<string, TeamRow[]>()
  for (const t of props.team) {
    if (!teamsByOwner.has(t.name)) teamsByOwner.set(t.name, [])
    teamsByOwner.get(t.name)!.push(t)
  }

  return props.roster.map((r) => ({
    rank: r.rank,
    name: r.name,
    record: `${r.wins}-${r.losses}`,
    currentWins: r.wins,
    currentLosses: r.losses,
    projectedWins: r.expected_wins ?? null,
    winProbability: r.win_probability ?? null,
    teams: (teamsByOwner.get(r.name) ?? []).map((t) => ({
      name: t.team,
      abbreviation: t.abbreviation,
      logo_url: t.logo_url,
      record: `${t.wins}-${t.losses}`,
      currentWins: t.wins,
      projectedWins: t.expected_wins ?? null,
    })),
  }))
})

const expandedRows = ref(new Set<string>())
const showMethodology = ref(false)
const allExpanded = ref(false)

function toggleRow(name: string) {
  if (expandedRows.value.has(name)) {
    expandedRows.value.delete(name)
    allExpanded.value = false
  } else {
    expandedRows.value.add(name)
    allExpanded.value = rows.value.every((r) => expandedRows.value.has(r.name))
  }
  expandedRows.value = new Set(expandedRows.value)
}

function toggleAll() {
  if (allExpanded.value) {
    expandedRows.value = new Set()
  } else {
    expandedRows.value = new Set(rows.value.map((r) => r.name))
  }
  allExpanded.value = !allExpanded.value
}

function fmtProb(p: number | null): string {
  if (p == null) return '—'
  const pct = p * 100
  if (pct > 0 && pct < 0.1) return '<0.1%'
  if (pct > 99.95 && pct < 100) return '>99.9%'
  return pct.toFixed(1) + '%'
}

function fmtWins(w: number | null): string {
  if (w == null) return '—'
  return w.toFixed(1)
}

function probColor(p: number | null): string {
  if (p == null) return 'text-surface-400'
  if (p >= 0.4) return 'text-green-400'
  if (p >= 0.15) return 'text-yellow-400'
  return 'text-surface-300'
}
</script>

<template>
  <div v-if="!hasSimData" class="p-6 text-center text-surface-400 text-sm">
    <i class="pi pi-info-circle mr-1.5"></i>No simulation data available yet.
  </div>
  <div v-else class="overflow-x-auto">
    <table class="w-full text-sm whitespace-nowrap">
      <thead>
        <tr class="text-left text-xs text-surface-400 border-b border-[var(--p-content-border-color)]">
          <th class="px-4 py-2 font-semibold cursor-pointer" @click="toggleAll">
            <div class="flex items-center gap-2">
              <i
                class="pi pi-angle-right transition-transform duration-200"
                :class="{ 'rotate-90': allExpanded }"
              />
              Name
            </div>
          </th>
          <th class="px-4 py-2 font-semibold text-center">Record</th>
          <th class="px-4 py-2 font-semibold text-center">Projected</th>
          <th class="px-4 py-2 font-semibold text-center">
            <div class="flex items-center justify-center gap-1">
              Win Prob
              <Button
                icon="pi pi-info-circle"
                text
                rounded
                size="small"
                class="!p-0 !w-4 !h-4 text-surface-400 hover:text-surface-200"
                aria-label="How win probability is calculated"
                @click.stop="showMethodology = true"
              />
            </div>
          </th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="row.name">
          <!-- Roster row -->
          <tr
            class="border-b border-[var(--p-content-border-color)] cursor-pointer hover:cursor-pointer"
            @click="toggleRow(row.name)"
          >
            <td class="px-4 py-2.5">
              <div class="flex items-center gap-2">
                <i
                  class="pi pi-angle-right transition-transform duration-200 text-surface-400"
                  :class="{ 'rotate-90': expandedRows.has(row.name) }"
                />
                <span v-if="row.rank" class="font-bold">{{ row.rank }}</span>
                <span>{{ row.name }}</span>
              </div>
            </td>
            <td class="px-4 py-2.5 text-center">{{ row.record }}</td>
            <td class="px-4 py-2.5 text-center">{{ fmtWins(row.projectedWins) }}</td>
            <td class="px-4 py-2.5 text-center font-semibold" :class="probColor(row.winProbability)">
              {{ fmtProb(row.winProbability) }}
            </td>
          </tr>

          <!-- Team breakdown rows -->
          <template v-if="expandedRows.has(row.name)">
            <tr
              v-for="t in row.teams"
              :key="t.abbreviation"
              class="border-b border-[var(--p-content-border-color)]"
            >
              <td class="px-4 py-2">
                <div class="flex items-center gap-1 pl-4">
                  <img v-if="t.logo_url" :src="t.logo_url" :alt="t.abbreviation" class="w-5 h-5 object-contain" />
                  <span class="text-surface-300 hidden sm:inline">{{ t.name }}</span>
                  <span class="text-surface-300 sm:hidden">{{ t.abbreviation }}</span>
                </div>
              </td>
              <td class="px-4 py-2 text-center text-surface-300">{{ t.record }}</td>
              <td class="px-4 py-2 text-center text-surface-300">{{ fmtWins(t.projectedWins) }}</td>
              <td class="px-4 py-2"></td>
            </tr>
          </template>
        </template>
      </tbody>
    </table>
  </div>

  <SimulationMethodologyDialog v-model:visible="showMethodology" />
</template>
