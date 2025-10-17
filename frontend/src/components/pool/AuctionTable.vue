<script setup lang="ts">
import { ref, computed } from 'vue'
import DataTable from 'primevue/datatable'
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
  scrollHeight?: string
  density?: 'S' | 'M' | 'L'
  maxHeight?: string
}>()

const multiSortMeta = ref([{ field: 'auction_value', order: -1 as const }])

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

// Determine DataTable scroll behavior
const dtScrollable = computed(() => !!(props.scrollHeight || props.maxHeight))
</script>

<template>
  <BaseScalableTable
    :density="props.density"
    :maxHeight="props.maxHeight"
    :scrollHeight="props.scrollHeight"
    :isEmpty="isEmpty"
  >
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
        :rowClass="getRowClass"
        @row-click="(e) => handleRowClick(e.originalEvent, e.data)"
      >
        <Column
          frozen
          field="team"
          sortable
          class="min-w-48 font-medium"
          :pt="{ sortIcon: 'size-3', pcSortBadge: { root: 'hidden' } }"
        >
          <template #header>
            <span class="font-medium text-sm pr-2">Team</span>
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
                  :class="`${slotProps.data.team.toLowerCase()}-logo`"
                />
                <span
                  class="truncate"
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
                  {{ slotProps.data.team }}
                </span>
              </div>
            </div>
          </template>
        </Column>
        <Column
          field="conf"
          sortable
          class="w-20"
          :pt="{ sortIcon: 'size-3', pcSortBadge: { root: 'hidden' } }"
        >
          <template #header>
            <span class="text-sm font-medium pr-2">Conf</span>
          </template>
        </Column>
        <Column
          field="reg_season_wins"
          sortable
          class="w-24"
          :pt="{ sortIcon: 'size-3', pcSortBadge: { root: 'hidden' } }"
        >
          <template #header>
            <span class="text-sm font-medium pr-2">Reg Wins</span>
          </template>
        </Column>
        <Column
          field="over_reg_season_wins_prob"
          sortable
          class="w-28"
          :pt="{ sortIcon: 'size-3', pcSortBadge: { root: 'hidden' } }"
        >
          <template #header>
            <span class="text-sm font-medium pr-2">Over %</span>
          </template>
          <template #body="slotProps">
            {{ (slotProps.data.over_reg_season_wins_prob * 100).toFixed(2) }}%
          </template>
        </Column>
        <Column
          field="make_playoffs_prob"
          sortable
          class="w-28"
          :pt="{ sortIcon: 'size-3', pcSortBadge: { root: 'hidden' } }"
        >
          <template #header>
            <span class="text-sm font-medium pr-2">Playoffs %</span>
          </template>
          <template #body="slotProps">
            {{ (slotProps.data.make_playoffs_prob * 100).toFixed(2) }}%
          </template>
        </Column>
        <Column
          field="conf_prob"
          sortable
          class="w-24"
          :pt="{ sortIcon: 'size-3', pcSortBadge: { root: 'hidden' } }"
        >
          <template #header>
            <span class="text-sm font-medium pr-2">Conf %</span>
          </template>
          <template #body="slotProps">
            {{ (slotProps.data.conf_prob * 100).toFixed(2) }}%
          </template>
        </Column>
        <Column
          field="title_prob"
          sortable
          class="w-24"
          :pt="{ sortIcon: 'size-3', pcSortBadge: { root: 'hidden' } }"
        >
          <template #header>
            <span class="text-sm font-medium pr-2">Title %</span>
          </template>
          <template #body="slotProps">
            {{ (slotProps.data.title_prob * 100).toFixed(2) }}%
          </template>
        </Column>
        <Column
          field="total_expected_wins"
          sortable
          class="w-32"
          :pt="{ sortIcon: 'size-3', pcSortBadge: { root: 'hidden' } }"
        >
          <template #header>
            <span class="text-sm font-medium pr-2">Total Wins</span>
          </template>
          <template #body="slotProps">
            {{ slotProps.data.total_expected_wins.toFixed(1) }}
          </template>
        </Column>
        <Column
          field="auction_value"
          sortable
          class="w-32"
          :pt="{ sortIcon: 'size-3', pcSortBadge: { root: 'hidden' } }"
        >
          <template #header>
            <span class="text-sm font-medium pr-2">Value</span>
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
      </DataTable>
      <p v-else class="text-surface-400 p-4">No auction data available.</p>
    </template>
  </BaseScalableTable>
</template>

<style scoped>
:deep(td) {
  padding: 0.15rem;
}
:deep(.p-datatable-frozen-column) {
  padding-left: 0.75rem;
}
</style>
