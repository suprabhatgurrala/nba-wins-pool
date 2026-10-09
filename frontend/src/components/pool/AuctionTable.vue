<script setup lang="ts">
import { ref, computed } from 'vue'
import DataTable, { type DataTableSortEvent } from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import BaseScalableTable from '@/components/common/BaseScalableTable.vue'
import type { AuctionDataItem } from '@/types/pool'

const props = defineProps<{
  auctionTableData: AuctionDataItem[] | null
  showNominateButton?: boolean
  nominatableTeamIds?: Set<string>
  closedLotTeamIds?: Set<string>
  currentLotTeamId?: string
  currentLotStatus?: string
  density?: 'S' | 'M' | 'L'
  maxHeight?: string
}>()

type SortMeta = { field: string; order: 1 | -1 }

const multiSortMeta = ref<SortMeta[]>([{ field: 'auction_value', order: -1 }])
let prevSortMeta: SortMeta[] = [...multiSortMeta.value]

// Text columns sort A-Z first; every other (numeric) column sorts descending first.
const TEXT_SORT_FIELDS = new Set(['team_name', 'conference'])

// The DataTable's sort cycle is desc -> asc -> off (defaultSortOrder = -1). For text columns,
// rewrite the result of the tapped header to asc -> desc -> off.
function handleSort(event: DataTableSortEvent) {
  const next = (event.multiSortMeta ?? []) as SortMeta[]
  const fields = new Set([...prevSortMeta, ...next].map((m) => m.field))
  const tapped = [...fields].find(
    (f) =>
      prevSortMeta.find((m) => m.field === f)?.order !== next.find((m) => m.field === f)?.order,
  )
  if (tapped && TEXT_SORT_FIELDS.has(tapped)) {
    const prevOrder = prevSortMeta.find((m) => m.field === tapped)?.order
    const others = prevSortMeta.filter((m) => m.field !== tapped)
    if (prevOrder === undefined) {
      multiSortMeta.value = [...others, { field: tapped, order: 1 }]
    } else if (prevOrder === 1) {
      multiSortMeta.value = prevSortMeta.map((m) =>
        m.field === tapped ? { field: tapped, order: -1 } : m,
      )
    } else {
      multiSortMeta.value = others
    }
  }
  prevSortMeta = [...multiSortMeta.value]
}

const emit = defineEmits<{
  nominate: [team: AuctionDataItem]
}>()

function canNominate(team: AuctionDataItem): boolean {
  if (!props.showNominateButton || !props.nominatableTeamIds) return false
  return team.team_id ? props.nominatableTeamIds.has(team.team_id) : false
}

function getRowClass(data: AuctionDataItem) {
  // Check if this is the current lot
  const isCurrentLot = props.currentLotTeamId && data.team_id === props.currentLotTeamId

  // If current lot is closed, treat it like other closed lots
  if (isCurrentLot && props.currentLotStatus === 'closed') {
    return 'opacity-40'
  }

  // Highlight current lot only if it's open
  if (isCurrentLot && props.currentLotStatus === 'open') {
    return 'bg-primary-900 [&>td]:!bg-primary-900'
  }

  // Other closed lots
  if (props.closedLotTeamIds && data.team_id && props.closedLotTeamIds.has(data.team_id)) {
    return 'opacity-40'
  }

  // Nominatable rows should be clickable
  if (canNominate(data)) {
    return 'cursor-pointer'
  }

  return ''
}

function handleRowClick(event: Event, data: AuctionDataItem) {
  if (canNominate(data)) {
    emit('nominate', data)
  }
}

// Determine if table is empty
const isEmpty = computed(() => !props.auctionTableData || props.auctionTableData.length === 0)

// DataTable is scrollable when maxHeight is set
const dtScrollable = computed(() => !!props.maxHeight)

// Column visibility checks
const hasOverWinsData = computed(
  () => props.auctionTableData?.some((item) => item.over_wins_prob !== null) ?? false,
)
const hasMakePlayoffsData = computed(
  () => props.auctionTableData?.some((item) => item.make_playoffs_prob !== null) ?? false,
)
const hasWinConferenceData = computed(
  () => props.auctionTableData?.some((item) => item.win_conference_prob !== null) ?? false,
)
const hasWinFinalsData = computed(
  () => props.auctionTableData?.some((item) => item.win_finals_prob !== null) ?? false,
)

// Tighter cells on mobile; sort icons for unsorted columns are hidden there (see style block)
const columnPt = {
  sortIcon: 'size-3',
  pcSortBadge: { root: 'hidden' },
  headerCell: '!px-1.5 sm:!px-2',
  bodyCell: '!px-1.5 sm:!px-2',
}
</script>

<template>
  <BaseScalableTable :density="props.density" :maxHeight="props.maxHeight" :isEmpty="isEmpty">
    <template #default="{ scrollHeight }">
      <DataTable
        v-if="props.auctionTableData && props.auctionTableData.length > 0"
        class="text-sm w-full"
        :value="props.auctionTableData"
        :scrollable="dtScrollable"
        :scrollHeight="scrollHeight"
        size="small"
        sortMode="multiple"
        removableSort
        v-model:multiSortMeta="multiSortMeta"
        :defaultSortOrder="-1"
        @sort="handleSort"
        :rowClass="getRowClass"
        @row-click="(e) => handleRowClick(e.originalEvent, e.data)"
      >
        <Column
          frozen
          field="team_name"
          sortable
          class="min-w-24 sm:min-w-48 font-medium"
          :pt="columnPt"
        >
          <template #header>
            <span class="font-medium text-sm sm:pr-2">Team</span>
          </template>
          <template #body="slotProps">
            <div class="block">
              <div class="flex items-center gap-2">
                <Button
                  v-if="props.showNominateButton && canNominate(slotProps.data)"
                  icon="pi pi-plus"
                  size="small"
                  rounded
                  variant="outlined"
                  severity="primary"
                  @click.stop="emit('nominate', slotProps.data)"
                  aria-label="Nominate team"
                />
                <img
                  :src="slotProps.data.logo_url"
                  class="size-7 flex-shrink-0"
                  :class="`${slotProps.data.team_name.toLowerCase()}-logo`"
                />
                <span
                  class="sm:truncate"
                  :class="
                    (props.closedLotTeamIds &&
                      slotProps.data.team_id &&
                      props.closedLotTeamIds.has(slotProps.data.team_id)) ||
                    (props.currentLotTeamId === slotProps.data.team_id &&
                      props.currentLotStatus === 'closed')
                      ? 'line-through'
                      : ''
                  "
                >
                  <span class="hidden sm:inline">{{ slotProps.data.team_name }}</span>
                  <span class="sm:hidden">{{
                    slotProps.data.abbreviation ?? slotProps.data.team_name
                  }}</span>
                </span>
              </div>
            </div>
          </template>
        </Column>
        <Column field="auction_value" sortable class="sm:w-32" :pt="columnPt">
          <template #header>
            <span class="text-sm font-medium sm:pr-2">Value</span>
          </template>
          <template #body="slotProps">
            {{
              Math.floor(slotProps.data.auction_value).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD',
                minimumFractionDigits: 0,
                maximumFractionDigits: 0,
              })
            }}
          </template>
        </Column>
        <Column field="expected_wins" sortable class="sm:w-32" :pt="columnPt">
          <template #header>
            <span class="text-sm font-medium sm:pr-2"
              ><span class="sm:hidden">Tot Wins</span
              ><span class="hidden sm:inline">Total Wins</span></span
            >
          </template>
          <template #body="slotProps">
            {{ slotProps.data.expected_wins.toFixed(1) }}
          </template>
        </Column>
        <Column field="conference" sortable class="sm:w-20" :pt="columnPt">
          <template #header>
            <span class="text-sm font-medium sm:pr-2">Conf</span>
          </template>
        </Column>
        <Column field="reg_season_wins" sortable class="sm:w-24" :pt="columnPt">
          <template #header>
            <span class="text-sm font-medium sm:pr-2"
              ><span class="sm:hidden">RS Wins</span
              ><span class="hidden sm:inline">Reg Wins</span></span
            >
          </template>
        </Column>
        <Column
          v-if="hasOverWinsData"
          field="over_wins_prob"
          sortable
          class="sm:w-28"
          :pt="columnPt"
        >
          <template #header>
            <span class="text-sm font-medium sm:pr-2">Over %</span>
          </template>
          <template #body="slotProps">
            {{
              slotProps.data.over_wins_prob !== null
                ? (slotProps.data.over_wins_prob * 100).toFixed(2) + '%'
                : '-'
            }}
          </template>
        </Column>
        <Column
          v-if="hasMakePlayoffsData"
          field="make_playoffs_prob"
          sortable
          class="sm:w-28"
          :pt="columnPt"
        >
          <template #header>
            <span class="text-sm font-medium sm:pr-2"
              ><span class="sm:hidden">PO %</span
              ><span class="hidden sm:inline">Playoffs %</span></span
            >
          </template>
          <template #body="slotProps">
            {{
              slotProps.data.make_playoffs_prob !== null
                ? (slotProps.data.make_playoffs_prob * 100).toFixed(2) + '%'
                : '-'
            }}
          </template>
        </Column>
        <Column
          v-if="hasWinConferenceData"
          field="win_conference_prob"
          sortable
          class="sm:w-24"
          :pt="columnPt"
        >
          <template #header>
            <span class="text-sm font-medium sm:pr-2"
              ><span class="sm:hidden">CF %</span><span class="hidden sm:inline">Conf %</span></span
            >
          </template>
          <template #body="slotProps">
            {{
              slotProps.data.win_conference_prob !== null
                ? (slotProps.data.win_conference_prob * 100).toFixed(2) + '%'
                : '-'
            }}
          </template>
        </Column>
        <Column
          v-if="hasWinFinalsData"
          field="win_finals_prob"
          sortable
          class="sm:w-24"
          :pt="columnPt"
        >
          <template #header>
            <span class="text-sm font-medium sm:pr-2">Title %</span>
          </template>
          <template #body="slotProps">
            {{
              slotProps.data.win_finals_prob !== null
                ? (slotProps.data.win_finals_prob * 100).toFixed(2) + '%'
                : '-'
            }}
          </template>
        </Column>
      </DataTable>
      <p v-else class="text-surface-400 p-4">No auction data available.</p>
    </template>
  </BaseScalableTable>
</template>

<style scoped>
/* AuctionTable uses .scalable-table class from BaseScalableTable for common scaling */
/* Override: slightly larger images than default */
:deep(img) {
  width: calc(1.75rem * var(--table-scale, 1));
  height: calc(1.75rem * var(--table-scale, 1));
}

/* On mobile, only show the sort icon on columns that are actively sorted */
@media (max-width: 639px) {
  :deep(th[data-p-sorted='false'] .p-datatable-sort-icon) {
    display: none;
  }
}
</style>
