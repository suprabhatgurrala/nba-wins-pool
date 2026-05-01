<script setup lang="ts">
import { computed, ref } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import BaseScalableTable from '@/components/common/BaseScalableTable.vue'
import type { RosterRow, TeamRow } from '@/types/leaderboard'

const props = defineProps<{
  roster: RosterRow[]
  team: TeamRow[]
  density?: 'S' | 'M' | 'L'
}>()

const hasSimData = computed(() => props.roster.some((r) => r.expected_wins != null))

interface OwnerFlatRow {
  _key: string
  _isTeam: false
  name: string
  record: string
  projectedWins: number | null
  winProbability: number | null
  rosterEliminated: boolean
  // Dedicated sort fields — Undrafted gets ±Infinity so it always sorts last
  _sortWins: number
  _sortProjected: number
  _sortWinProb: number
}

interface TeamFlatRow {
  _key: string
  _isTeam: true
  ownerName: string
  teamName: string
  abbreviation: string
  logo_url: string
  eliminated: boolean
  teamRecord: string
  teamProjectedWins: number | null
  // Inherit parent's sort values so stable sort keeps team rows adjacent to their owner
  _sortWins: number
  _sortProjected: number
  _sortWinProb: number
}

type FlatRow = OwnerFlatRow | TeamFlatRow

const allOwners = computed(() => {
  const teamsByOwner = new Map<string, TeamRow[]>()
  for (const t of props.team) {
    if (!teamsByOwner.has(t.name)) teamsByOwner.set(t.name, [])
    teamsByOwner.get(t.name)!.push(t)
  }
  return props.roster.map((r) => ({
    name: r.name,
    record: `${r.wins}-${r.losses}`,
    currentWins: r.wins,
    projectedWins: r.expected_wins ?? null,
    winProbability: r.win_probability ?? null,
    eliminated: r.eliminated ?? false,
    teams: (teamsByOwner.get(r.name) ?? []).map((t) => ({
      teamName: t.team,
      abbreviation: t.abbreviation,
      logo_url: t.logo_url,
      eliminated: t.eliminated ?? false,
      teamRecord: `${t.wins}-${t.losses}`,
      teamProjectedWins: t.expected_wins ?? null,
      teamCurrentWins: t.wins,
    })),
  }))
})

const sortField = ref('_sortWinProb')
const sortOrder = ref(-1)

function handleSort(event: { sortField?: string | null | ((item: unknown) => string); sortOrder?: number | null }) {
  const field = typeof event.sortField === 'string' ? event.sortField : null
  if (!field) {
    sortField.value = '_sortWinProb'
    sortOrder.value = -1
  } else {
    sortField.value = field
    sortOrder.value = event.sortOrder ?? -1
  }
}

const expandedNames = ref(new Set<string>())

const allExpanded = computed(
  () => allOwners.value.length > 0 && allOwners.value.every((o) => expandedNames.value.has(o.name)),
)

function toggleOwner(name: string) {
  if (expandedNames.value.has(name)) {
    expandedNames.value.delete(name)
  } else {
    expandedNames.value.add(name)
  }
  expandedNames.value = new Set(expandedNames.value)
}

function toggleAll() {
  if (allExpanded.value) {
    expandedNames.value = new Set()
  } else {
    expandedNames.value = new Set(allOwners.value.map((o) => o.name))
  }
}

const tableData = computed<FlatRow[]>(() => {
  // Sentinel pushes Undrafted to the bottom regardless of sort direction
  const bottom = sortOrder.value === 1 ? Infinity : -Infinity

  const rows: FlatRow[] = []
  for (const owner of allOwners.value) {
    const isUndrafted = owner.name === 'Undrafted'
    const sortWins     = isUndrafted ? bottom : owner.currentWins
    const sortProj     = isUndrafted ? bottom : (owner.projectedWins ?? bottom)
    const sortWinProb  = isUndrafted ? bottom : (owner.winProbability ?? bottom)

    rows.push({
      _key: owner.name,
      _isTeam: false,
      name: owner.name,
      record: owner.record,
      projectedWins: owner.projectedWins,
      winProbability: owner.winProbability,
      rosterEliminated: owner.eliminated,
      _sortWins: sortWins,
      _sortProjected: sortProj,
      _sortWinProb: sortWinProb,
    })

    if (expandedNames.value.has(owner.name)) {
      const teams = sortField.value === '_sortProjected'
        ? [...owner.teams].sort((a, b) => {
            const av = a.teamProjectedWins ?? bottom
            const bv = b.teamProjectedWins ?? bottom
            return (av - bv) * sortOrder.value
          })
        : owner.teams
      for (const t of teams) {
        rows.push({
          _key: `${owner.name}_${t.abbreviation}`,
          _isTeam: true,
          ownerName: owner.name,
          teamName: t.teamName,
          abbreviation: t.abbreviation,
          logo_url: t.logo_url,
          eliminated: t.eliminated,
          teamRecord: t.teamRecord,
          teamProjectedWins: t.teamProjectedWins,
          _sortWins: sortWins,
          _sortProjected: sortProj,
          _sortWinProb: sortWinProb,
        })
      }
    }
  }
  return rows
})

const rowClass = (row: FlatRow) => {
  if (!row._isTeam) return ['hover:cursor-pointer', row.rosterEliminated ? 'opacity-50' : ''].filter(Boolean).join(' ')
  return ['cursor-default', row.eliminated ? 'opacity-50' : ''].join(' ')
}

function handleRowClick({ data }: { data: FlatRow }) {
  if (!data._isTeam) toggleOwner(data.name)
}

// Returns [integerPart, decimalAndSuffix] for decimal-aligned rendering
function winProbParts(p: number | null): [string, string] {
  if (p == null) return ['', '—']
  const pct = p * 100
  if (pct > 0 && pct < 0.1) return ['<0', '.1%']
  if (pct >= 100) return ['100', '.0%']
  if (pct > 99.95) return ['>99', '.9%']
  const [int, dec] = pct.toFixed(1).split('.')
  return [int, `.${dec}%`]
}

function fmtWins(w: number | null): string {
  if (w == null) return '—'
  return w.toFixed(1)
}


</script>

<template>
  <div v-if="!hasSimData" class="p-6 text-center text-surface-400 text-sm">
    <i class="pi pi-info-circle mr-1.5"></i>No simulation data available yet.
  </div>
  <BaseScalableTable v-else :density="density">
    <DataTable
      :value="tableData"
      dataKey="_key"
      :sortField="sortField"
      :sortOrder="sortOrder"
      :defaultSortOrder="-1"
      removableSort
      size="small"
      rowHover
      :row-class="rowClass"
      class="text-sm w-full whitespace-nowrap"
      @sort="handleSort"
      @row-click="handleRowClick"
    >
      <Column frozen headerClass="cursor-pointer" bodyClass="bg-inherit" headerStyle="padding-right: 0.25rem" bodyStyle="padding-right: 0.25rem">
        <template #header>
          <div class="flex items-center gap-2 cursor-pointer" @click="toggleAll">
            <i
              class="pi pi-angle-right transition-transform duration-200 text-surface-400"
              :class="{ 'rotate-90': allExpanded }"
            />
            <p class="font-semibold">Name</p>
          </div>
        </template>
        <template #body="{ data }">
          <div v-if="!data._isTeam" class="flex items-center gap-2">
            <i
              class="pi pi-angle-right transition-transform duration-200 text-surface-400"
              :class="{ 'rotate-90': expandedNames.has(data.name) }"
            />
            <span>{{ data.name }}</span>
          </div>
          <div v-else class="flex items-center gap-1 pl-8">
            <img v-if="data.logo_url" :src="data.logo_url" :alt="data.abbreviation" class="w-5 h-5 object-contain" />
            <span class="text-surface-300 hidden sm:inline">{{ data.teamName }}</span>
            <span class="text-surface-300 sm:hidden">{{ data.abbreviation }}</span>
          </div>
        </template>
      </Column>
      <Column field="_sortWins" header="Record" sortable>
        <template #body="{ data }">
          <p class="text-center" :class="{ 'text-surface-300': data._isTeam }">
            {{ data._isTeam ? data.teamRecord : data.record }}
          </p>
        </template>
      </Column>
      <Column field="_sortProjected" header="Projected" sortable>
        <template #body="{ data }">
          <p class="text-center" :class="{ 'text-surface-300': data._isTeam }">
            {{ data._isTeam ? fmtWins(data.teamProjectedWins) : fmtWins(data.projectedWins) }}
          </p>
        </template>
      </Column>
      <Column field="_sortWinProb" sortable>
        <template #header>
          <span class="sm:hidden">Win %</span>
          <span class="hidden sm:inline">Win Probability</span>
        </template>
        <template #body="{ data }">
          <div v-if="!data._isTeam && data.winProbability != null" class="flex justify-center">
            <span class="inline-flex tabular-nums">
              <span class="text-right w-[3ch]">{{ winProbParts(data.winProbability)[0] }}</span>
              <span>{{ winProbParts(data.winProbability)[1] }}</span>
            </span>
          </div>
        </template>
      </Column>
    </DataTable>
  </BaseScalableTable>
</template>

<style scoped>
:deep(.p-datatable-sort-icon) {
  width: 0.65rem;
  height: 0.65rem;
  margin-left: 0.35rem;
  vertical-align: middle;
}
</style>
