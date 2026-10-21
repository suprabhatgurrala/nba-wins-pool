<script setup lang="ts">
import ColumnHeader from '@/components/common/ColumnHeader.vue'
import NestedTeamLabel from '@/components/common/NestedTeamLabel.vue'
import { provideTeamNameGroup } from '@/composables/useFitGroup'
import { computed, ref } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import BaseScalableTable from '@/components/common/BaseScalableTable.vue'
import type { RosterRow, TeamRow } from '@/types/leaderboard'

provideTeamNameGroup()

const props = defineProps<{
  roster: RosterRow[]
  team: TeamRow[]
  density?: 'S' | 'M' | 'L'
}>()

const hasSimData = computed(() => props.roster.some((r) => r.expected_wins != null))
const hasWinProb = computed(() => props.roster.some((r) => r.win_probability != null))
const hasPreseason = computed(() => props.roster.some((r) => r.preseason_projected_wins != null))
const defaultSortField = computed(() =>
  hasWinProb.value ? '_sortWinProb' : hasSimData.value ? '_sortProjected' : '_sortWins',
)

interface OwnerFlatRow {
  _key: string
  _isTeam: false
  name: string
  record: string
  preseasonWins: number | null
  projectedWins: number | null
  winProbability: number | null
  rosterEliminated: boolean
  // Dedicated sort fields — Undrafted gets ±Infinity so it always sorts last
  _sortWins: number
  _sortPreseason: number
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
  teamPreseasonWins: number | null
  teamProjectedWins: number | null
  // Inherit parent's sort values so stable sort keeps team rows adjacent to their owner
  _sortWins: number
  _sortPreseason: number
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
    preseasonWins: r.preseason_projected_wins ?? null,
    projectedWins: r.expected_wins ?? null,
    winProbability: r.win_probability ?? null,
    eliminated: r.eliminated ?? false,
    teams: (teamsByOwner.get(r.name) ?? []).map((t) => ({
      teamName: t.team,
      abbreviation: t.abbreviation,
      logo_url: t.logo_url,
      eliminated: t.eliminated ?? false,
      teamRecord: `${t.wins}-${t.losses}`,
      teamPreseasonWins: t.preseason_projected_wins ?? null,
      teamProjectedWins: t.expected_wins ?? null,
      teamCurrentWins: t.wins,
    })),
  }))
})

const userSortField = ref<string | null>(null)
const sortField = computed(() => userSortField.value ?? defaultSortField.value)
const sortOrder = ref(-1)

function handleSort(event: {
  sortField?: string | null | ((item: unknown) => string)
  sortOrder?: number | null
}) {
  const field = typeof event.sortField === 'string' ? event.sortField : null
  if (!field) {
    userSortField.value = null
    sortOrder.value = -1
  } else {
    userSortField.value = field
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
    const sortWins = isUndrafted ? bottom : owner.currentWins
    const sortPreseason = isUndrafted ? bottom : (owner.preseasonWins ?? bottom)
    const sortProj = isUndrafted ? bottom : (owner.projectedWins ?? bottom)
    const sortWinProb = isUndrafted ? bottom : (owner.winProbability ?? bottom)

    rows.push({
      _key: owner.name,
      _isTeam: false,
      name: owner.name,
      record: owner.record,
      preseasonWins: owner.preseasonWins,
      projectedWins: owner.projectedWins,
      winProbability: owner.winProbability,
      rosterEliminated: owner.eliminated,
      _sortWins: sortWins,
      _sortPreseason: sortPreseason,
      _sortProjected: sortProj,
      _sortWinProb: sortWinProb,
    })

    if (expandedNames.value.has(owner.name)) {
      const teamSortKey = {
        _sortPreseason: 'teamPreseasonWins',
        _sortProjected: 'teamProjectedWins',
      }[sortField.value] as 'teamPreseasonWins' | 'teamProjectedWins' | undefined
      const teams = teamSortKey
        ? [...owner.teams].sort((a, b) => {
            const av = a[teamSortKey] ?? bottom
            const bv = b[teamSortKey] ?? bottom
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
          teamPreseasonWins: t.teamPreseasonWins,
          teamProjectedWins: t.teamProjectedWins,
          _sortWins: sortWins,
          _sortPreseason: sortPreseason,
          _sortProjected: sortProj,
          _sortWinProb: sortWinProb,
        })
      }
    }
  }
  return rows
})

const rowClass = (row: FlatRow) => {
  if (!row._isTeam)
    return ['hover:cursor-pointer', row.rosterEliminated ? 'opacity-50' : '']
      .filter(Boolean)
      .join(' ')
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

// Same compact cell styling as AuctionTable: tighter cells in a narrow table, small sort icons
const columnPt = {
  pcSortBadge: { root: 'hidden' },
  headerCell: '!px-1.5 @xl:!px-2 !whitespace-nowrap leading-tight',
  bodyCell: '!px-1.5 @xl:!px-2',
}
</script>

<template>
  <div v-if="!hasSimData && !hasPreseason" class="p-6 text-center text-surface-400 text-sm">
    <i class="pi pi-info-circle mr-1.5"></i>No simulation data available yet.
  </div>
  <BaseScalableTable v-else :density="density">
    <DataTable
      data-scroll-x
      scrollable
      :value="tableData"
      dataKey="_key"
      :sortField="sortField"
      :sortOrder="sortOrder"
      :defaultSortOrder="-1"
      removableSort
      size="small"
      rowHover
      :row-class="rowClass"
      class="text-sm w-full"
      @sort="handleSort"
      @row-click="handleRowClick"
    >
      <Column
        frozen
        headerClass="cursor-pointer"
        bodyClass="bg-inherit"
        class="min-w-28"
        :pt="columnPt"
      >
        <template #header>
          <div class="flex flex-1 items-center gap-2 cursor-pointer" @click="toggleAll">
            <i
              class="pi pi-angle-right transition-transform duration-200 text-surface-400"
              :class="{ 'rotate-90': allExpanded }"
            />
            <ColumnHeader full="Name" />
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
          <NestedTeamLabel
            v-else
            class="pl-8 text-surface-300"
            :name="data.teamName"
            :abbreviation="data.abbreviation"
            :logo-url="data.logo_url"
          />
        </template>
      </Column>
      <Column field="_sortWins" sortable :pt="columnPt">
        <template #header
          ><ColumnHeader full="Record" short="W-L" class="text-sm font-medium"
        /></template>
        <template #body="{ data }">
          <p class="text-center" :class="{ 'text-surface-300': data._isTeam }">
            {{ data._isTeam ? data.teamRecord : data.record }}
          </p>
        </template>
      </Column>
      <Column v-if="hasPreseason" field="_sortPreseason" sortable :pt="columnPt">
        <template #header>
          <ColumnHeader full="Preseason" class="text-sm font-medium" />
        </template>
        <template #body="{ data }">
          <p class="text-center" :class="{ 'text-surface-300': data._isTeam }">
            {{ data._isTeam ? fmtWins(data.teamPreseasonWins) : fmtWins(data.preseasonWins) }}
          </p>
        </template>
      </Column>
      <Column v-if="hasSimData" field="_sortProjected" sortable :pt="columnPt">
        <template #header>
          <ColumnHeader full="Simulated Avg" short="Sim" class="text-sm font-medium" />
        </template>
        <template #body="{ data }">
          <p class="text-center" :class="{ 'text-surface-300': data._isTeam }">
            {{ data._isTeam ? fmtWins(data.teamProjectedWins) : fmtWins(data.projectedWins) }}
          </p>
        </template>
      </Column>
      <Column v-if="hasWinProb" field="_sortWinProb" sortable :pt="columnPt">
        <template #header>
          <ColumnHeader full="Win Probability" short="Win %" class="text-sm font-medium" />
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
