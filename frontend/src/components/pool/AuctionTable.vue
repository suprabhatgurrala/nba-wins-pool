<script setup lang="ts">
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'

import { AuctionDataItem } from '@/types/pool'

const props = defineProps<{
    auctionTableData: AuctionDataItem[] | null
}>()
</script>

<template>
    <DataTable :value="props.auctionTableData" scrollable>
        <Column frozen field="team" header="Team">
            <template #body="slotProps">
                <div class="name-cell" :class="{ 'team-row': 'team' in slotProps.data }">
                    <img :src="slotProps.data.logo_url" class="team-logo"
                        :class="`${slotProps.data.team.toLowerCase()}-logo`" />
                    <span>{{ slotProps.data.team }}</span>
                </div>
            </template>
        </Column>
        <Column field="conf" header="Conference" />
        <Column field="reg_season_wins" header="Regular Season Wins" />
        <Column field="over_reg_season_wins_prob" header="Over Wins Probability">
            <template #body="slotProps">
                {{ (slotProps.data.over_reg_season_wins_prob * 100).toFixed(2) }}%
            </template>
        </Column>
        <Column field="make_playoffs_prob" header="Make Playoffs Probability">
            <template #body="slotProps">
                {{ (slotProps.data.make_playoffs_prob * 100).toFixed(2) }}%
            </template>
        </Column>
        <Column field="conf_prob" header="Conference Probability">
            <template #body="slotProps">
                {{ (slotProps.data.conf_prob * 100).toFixed(2) }}%
            </template>
        </Column>
        <Column field="title_prob" header="Title Probability">
            <template #body="slotProps">
                {{ (slotProps.data.title_prob * 100).toFixed(2) }}%
            </template>
        </Column>
        <Column field="total_expected_wins" header="Total Expected Wins">
            <template #body="slotProps">
                {{ slotProps.data.total_expected_wins.toFixed(1) }}
            </template>
        </Column>
        <Column field="auction_value" header="Auction Value">
            <template #body="slotProps">
                {{ Math.floor(slotProps.data.auction_value).toLocaleString('en-US', {
                    style: 'currency', currency:
                        'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }) }}
            </template>
        </Column>
    </DataTable>
</template>

<style scoped>
.name-cell {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.5rem 0.35rem 1.25rem;
  height: 2.25rem;
  cursor: pointer;
  position: relative;
}

.name-cell.team-row {
  padding-left: 0.75rem;
  background: var(--surface-ground);
  cursor: default;
}

.team-logo {
  width: 30px;
  height: 30px;
  object-fit: contain;
}

</style>
