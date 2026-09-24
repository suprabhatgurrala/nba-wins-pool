<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ColumnGroup from 'primevue/columngroup'
import Row from 'primevue/row'
import SiteHeader from '@/components/common/SiteHeader.vue'
import SeasonRail from '@/components/pool/SeasonRail.vue'
import { usePool } from '@/composables/usePool'
import { useParticipantHistory } from '@/composables/useParticipantHistory'
import { isUuid } from '@/utils/ids'

const route = useRoute()
const router = useRouter()

const { pool, error: poolError, loading: poolLoading, fetchPoolById, fetchPoolBySlug } = usePool()
const { history, error: historyError, loading: historyLoading, fetchParticipantHistory } = useParticipantHistory()

const participantName = ref((route.params.name as string) || '')

function ordinal(rank: number): string {
  const mod100 = rank % 100
  if (mod100 >= 11 && mod100 <= 13) return `${rank}th`
  switch (rank % 10) {
    case 1:
      return `${rank}st`
    case 2:
      return `${rank}nd`
    case 3:
      return `${rank}rd`
    default:
      return `${rank}th`
  }
}

interface TeamContribution {
  abbreviation: string
  name: string
  logo_url: string
  seasons: number
  totalWins: number
  bestSeason: string
  bestWins: number
}

const hasPrices = computed(() =>
  (history.value?.seasons ?? []).some((s) => s.teams.some((t) => t.auction_price != null)),
)

const topTeams = computed<TeamContribution[]>(() => {
  const byAbbreviation = new Map<string, TeamContribution>()
  for (const season of history.value?.seasons ?? []) {
    for (const team of season.teams) {
      const existing = byAbbreviation.get(team.abbreviation)
      if (existing) {
        existing.seasons += 1
        existing.totalWins += team.wins
        if (team.wins > existing.bestWins) {
          existing.bestSeason = season.season
          existing.bestWins = team.wins
        }
      } else {
        byAbbreviation.set(team.abbreviation, {
          abbreviation: team.abbreviation,
          name: team.name,
          logo_url: team.logo_url,
          seasons: 1,
          totalWins: team.wins,
          bestSeason: season.season,
          bestWins: team.wins,
        })
      }
    }
  }
  return Array.from(byAbbreviation.values()).sort((a, b) => b.totalWins - a.totalWins)
})

const participantBlurb = computed(() => {
  const seasons = history.value?.seasons ?? []
  if (!seasons.length) return null

  const seasonsPlayed = seasons.length
  const seasonsText = `${seasonsPlayed} season${seasonsPlayed === 1 ? '' : 's'}`
  const championSeasons = seasons.filter((s) => s.rank === 1)

  if (championSeasons.length > 1) {
    return `${seasonsText} · ${championSeasons.length}-time champion`
  }
  if (championSeasons.length === 1) {
    return `${seasonsText} · Champion in ${championSeasons[0].season}`
  }

  const ranked = seasons.filter((s) => s.rank != null)
  if (!ranked.length) return seasonsText
  const bestRank = Math.min(...ranked.map((s) => s.rank as number))
  return `${seasonsText} · Best finish: ${ordinal(bestRank)}`
})

// Caps each list's height to its first N rows (measured from the rendered DOM, since row height
// varies with content) so the rest scrolls inside the card instead of pushing the page down — but
// only when that's actually needed to bring the Top Contributing Teams card into view; on a tall
// enough viewport both lists render in full.
function sumFirstHeights(container: HTMLElement | null, selector: string, count: number): number | null {
  if (!container) return null
  const rows = Array.from(container.querySelectorAll<HTMLElement>(selector))
  if (rows.length <= count) return null
  return rows.slice(0, count).reduce((sum, row) => sum + row.offsetHeight, 0)
}

const seasonsListEl = ref<HTMLElement | null>(null)
const seasonsMaxHeight = ref<number | null>(null)
const topTeamsEl = ref<HTMLElement | null>(null)
const topTeamsScrollHeight = ref<number | null>(null)

watch(history, async () => {
  // Reset to full height first so the visibility check below measures natural, uncapped layout.
  seasonsMaxHeight.value = null
  topTeamsScrollHeight.value = null
  await nextTick()

  const topTeamsVisible = !topTeamsEl.value || topTeamsEl.value.getBoundingClientRect().top < window.innerHeight
  if (topTeamsVisible) return

  seasonsMaxHeight.value = sumFirstHeights(seasonsListEl.value, ':scope > div', 3)
  topTeamsScrollHeight.value = sumFirstHeights(topTeamsEl.value, '.p-datatable-tbody > tr', 6)
})

async function resolvePoolAndSlug() {
  const idOrSlug = (route.params.slug as string) || ''
  if (!idOrSlug) return
  if (isUuid(idOrSlug)) {
    await fetchPoolById(idOrSlug)
  } else {
    await fetchPoolBySlug(idOrSlug)
  }
  const p = pool.value
  if (!p) return

  if (route.params.slug !== p.slug) {
    await router.replace({ name: 'pool-participant-history', params: { slug: p.slug, name: participantName.value } })
  }

  await fetchParticipantHistory(p.id, participantName.value)
}

onMounted(() => {
  resolvePoolAndSlug()
})
</script>

<template>
  <SiteHeader>
    <template #left>
      <Button
        icon="pi pi-arrow-left"
        variant="outlined"
        severity="secondary"
        @click="router.push({ name: 'pool', params: { slug: (route.params.slug as string) } })"
        aria-label="Back to pool"
      />
    </template>
  </SiteHeader>
  <main>
    <div class="flex flex-col items-center pb-2 pt-2">
      <p class="text-3xl font-extrabold text-center">{{ participantName }}</p>
      <p v-if="!poolLoading && pool" class="text-sm font-medium text-surface-400 text-center">{{ pool.name }}</p>
      <p v-if="participantBlurb" class="text-sm text-surface-300 text-center mt-1">{{ participantBlurb }}</p>
    </div>

    <div class="flex flex-col px-4 gap-3 mx-auto max-w-3xl w-full pb-8">
      <div v-if="historyLoading || poolLoading" class="py-8 text-center text-surface-400">
        <i class="pi pi-spinner pi-spin text-3xl mb-2"></i>
        <p class="text-sm">Loading history...</p>
      </div>
      <div v-else-if="historyError || poolError" class="text-sm text-red-500 p-4">
        ⚠️ {{ historyError || poolError }}
      </div>
      <div v-else-if="!history?.seasons.length" class="py-8 text-center text-sm text-surface-400">
        No seasons recorded for {{ participantName }}.
      </div>
      <Card
        v-if="history?.seasons.length"
        class="border-2 rounded-xl overflow-hidden border-content"
        :pt="{ body: 'p-0' }"
      >
        <template #content>
          <div
            class="grid items-center gap-x-2 py-1.5 pl-[6rem] pr-3 text-xs font-medium text-surface-400 sm:pr-4"
            :class="hasPrices ? 'grid-cols-[1.25rem_1fr_3.5rem_3.5rem]' : 'grid-cols-[1.25rem_1fr_3.5rem]'"
          >
            <span class="col-span-2"></span>
            <span v-if="hasPrices" class="text-right">Paid</span>
            <span class="text-right">Record</span>
          </div>
          <div
            ref="seasonsListEl"
            class="divide-y divide-[var(--p-content-border-color)] border-t border-content"
            :class="{ 'overflow-y-auto': seasonsMaxHeight }"
            :style="seasonsMaxHeight ? { maxHeight: `${seasonsMaxHeight}px` } : undefined"
          >
            <div v-for="s in history.seasons" :key="s.season" class="grid grid-cols-[6rem_1fr]">
              <SeasonRail
                :to="{ name: 'pool-season', params: { slug: (route.params.slug as string), season: s.season } }"
                :season="s.season"
              >
                <span v-if="s.rank === 1" class="text-xl leading-none text-amber-400">🏆</span>
                <span v-else-if="s.rank != null" class="text-xl font-extrabold leading-none">{{
                  ordinal(s.rank)
                }}</span>
                <span class="tabular-nums text-sm font-semibold text-surface-400">{{ s.wins }}-{{ s.losses }}</span>
              </SeasonRail>
              <div class="flex flex-col justify-center py-1.5">
                <div
                  v-for="t in s.teams"
                  :key="t.abbreviation"
                  class="grid items-center gap-x-2 px-3 py-1 sm:px-4"
                  :class="hasPrices ? 'grid-cols-[1.25rem_1fr_3.5rem_3.5rem]' : 'grid-cols-[1.25rem_1fr_3.5rem]'"
                >
                  <img :src="t.logo_url" :alt="t.abbreviation" class="size-5 flex-shrink-0" />
                  <span class="hidden truncate text-sm sm:inline">{{ t.name }}</span>
                  <span class="truncate text-sm sm:hidden">{{ t.abbreviation }}</span>
                  <span v-if="hasPrices" class="text-right tabular-nums text-sm text-surface-400">{{
                    t.auction_price != null ? `$${t.auction_price.toFixed(0)}` : '—'
                  }}</span>
                  <span class="text-right tabular-nums text-sm font-medium">{{ t.wins }}-{{ t.losses }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </Card>

      <Card
        v-if="topTeams.length"
        class="border-2 rounded-xl overflow-hidden border-content"
        :pt="{ body: 'p-0', header: 'px-3 py-2 sm:px-4 sm:py-2.5' }"
      >
        <template #header>
          <div class="flex items-center gap-2">
            <i class="pi pi-star text-amber-400"></i>
            <p class="text-sm font-semibold">Top Contributing Teams</p>
          </div>
        </template>
        <template #content>
          <div ref="topTeamsEl" class="overflow-x-auto">
            <DataTable
              :value="topTeams"
              size="small"
              class="w-full text-sm compact-history-table"
              removableSort
              :scrollable="!!topTeamsScrollHeight"
              :scrollHeight="topTeamsScrollHeight ? `${topTeamsScrollHeight}px` : undefined"
            >
              <ColumnGroup type="header">
                <Row>
                  <Column header="Team" :rowspan="2" />
                  <Column header="Total" :colspan="2" />
                  <Column header="Best" :colspan="2" />
                </Row>
                <Row>
                  <Column field="seasons" header="Seasons" sortable />
                  <Column field="totalWins" header="Wins" sortable />
                  <Column field="bestSeason" header="Season" sortable />
                  <Column field="bestWins" header="Wins" sortable />
                </Row>
              </ColumnGroup>
              <Column field="name">
                <template #body="{ data }">
                  <div class="flex items-center gap-2">
                    <img :src="data.logo_url" class="size-5 flex-shrink-0" :alt="data.abbreviation" />
                    <span class="hidden truncate font-medium sm:inline">{{ data.name }}</span>
                    <span class="truncate font-medium sm:hidden">{{ data.abbreviation }}</span>
                  </div>
                </template>
              </Column>
              <Column field="seasons" />
              <Column field="totalWins">
                <template #body="{ data }">
                  <span class="tabular-nums font-semibold">{{ data.totalWins }}</span>
                </template>
              </Column>
              <Column field="bestSeason">
                <template #body="{ data }">
                  <span class="tabular-nums text-surface-400">{{ data.bestSeason }}</span>
                </template>
              </Column>
              <Column field="bestWins">
                <template #body="{ data }">
                  <span class="tabular-nums font-semibold">{{ data.bestWins }}</span>
                </template>
              </Column>
            </DataTable>
          </div>
        </template>
      </Card>
    </div>
  </main>
</template>

<style scoped>
.compact-history-table :deep(.p-datatable-tbody > tr > td) {
  padding-block: 0.4rem;
  padding-inline: 0.375rem;
}

.compact-history-table :deep(.p-datatable-thead > tr > th) {
  padding-block: 0.4rem;
  padding-inline: 0.375rem;
}
</style>
