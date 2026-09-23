<script setup lang="ts">
import { ref } from 'vue'
import { onClickOutside } from '@vueuse/core'
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import { RouterLink } from 'vue-router'
import { getCurrentSeason } from '@/utils/season'
import type { PoolHistory } from '@/types/poolHistory'

const props = defineProps<{
  poolSlug: string
  history: PoolHistory | null
  loading: boolean
  error: string | null
}>()

// The popover is teleported to <body> (not rendered inline) because its trigger sits inside a
// Card with overflow-hidden (for rounded corners), which would otherwise clip it.
const showWinsTip = ref(false)
const winsTipBtn = ref<HTMLElement>()
const winsTipBubble = ref<HTMLElement>()
const winsTipStyle = ref({ top: '0px', left: '0px' })
onClickOutside(winsTipBubble, () => (showWinsTip.value = false), { ignore: [winsTipBtn] })

function toggleWinsTip() {
  if (!showWinsTip.value && winsTipBtn.value) {
    const rect = winsTipBtn.value.getBoundingClientRect()
    winsTipStyle.value = {
      top: `${rect.top - 8}px`,
      left: `${rect.left + rect.width / 2}px`,
    }
  }
  showWinsTip.value = !showWinsTip.value
}

// Only the season actually in progress right now gets the "reigning" highlight —
// a pool's most recent season may already be finished (e.g. no season created yet
// for the new year), and a finished season's champion should render gold like any other.
const reigningSeason = getCurrentSeason()
</script>

<template>
  <div v-if="loading" class="py-8 text-center text-surface-400">
    <i class="pi pi-spinner pi-spin text-3xl mb-2"></i>
    <p class="text-sm">Loading history...</p>
  </div>
  <div v-else-if="error" class="text-sm text-red-500 p-4">⚠️ {{ error }}</div>
  <div v-else class="flex flex-col gap-3">
    <Card
      class="border-2 rounded-xl overflow-hidden border-content"
      :pt="{ body: 'p-0', header: 'px-3 py-2 sm:px-4 sm:py-2.5' }"
    >
      <template #header>
        <div class="flex items-center gap-2">
          <i class="pi pi-calendar"></i>
          <p class="text-sm font-semibold">Seasons</p>
        </div>
      </template>
      <template #content>
        <div v-if="!history?.seasons.length" class="p-3 text-sm text-surface-400">
          No seasons recorded yet.
        </div>
        <div v-else class="divide-y divide-[var(--p-content-border-color)]">
          <RouterLink
            v-for="s in history.seasons"
            :key="s.season"
            :to="{ name: 'pool-season', params: { slug: poolSlug, season: s.season } }"
            class="flex items-baseline gap-2.5 px-3 py-2 transition-colors hover:bg-primary/5 sm:px-4"
          >
            <span
              class="flex-shrink-0 self-center whitespace-nowrap text-sm font-bold text-surface-400"
              :class="{ 'text-primary': s.season === reigningSeason }"
              >{{ s.season }}</span
            >
            <template v-if="s.champion">
              <div
                class="grid flex-1 min-w-0 grid-cols-[1rem_1fr_auto] items-baseline gap-x-1.5 gap-y-0.5"
              >
                <span class="text-xs text-surface-400">1.</span>
                <span
                  class="truncate text-sm font-semibold sm:text-base"
                  :class="{ 'text-primary': s.season === reigningSeason }"
                  >{{ s.champion.name }}</span
                >
                <span
                  class="flex-shrink-0 text-right tabular-nums text-sm font-bold"
                  :class="s.season === reigningSeason ? 'text-primary' : 'text-amber-400'"
                  >{{ s.champion.wins }}W</span
                >

                <template v-if="s.runner_up">
                  <span class="text-xs text-surface-400">2.</span>
                  <span class="truncate text-sm text-surface-400">{{ s.runner_up.name }}</span>
                  <span class="flex-shrink-0 text-right tabular-nums text-sm text-surface-400"
                    >{{ s.runner_up.wins }}W</span
                  >
                </template>
              </div>
              <i class="pi pi-angle-right self-center text-xs text-surface-400"></i>
            </template>
            <template v-else>
              <span class="flex-1 self-center text-sm text-surface-400">Draft not yet held</span>
              <span
                class="flex-shrink-0 self-center rounded-full border border-primary px-2 py-0.5 text-xs font-semibold text-primary"
                >Set up →</span
              >
            </template>
          </RouterLink>
        </div>
      </template>
    </Card>

    <Card
      class="border-2 rounded-xl overflow-hidden border-content"
      :pt="{ body: 'p-0', header: 'px-3 py-2 sm:px-4 sm:py-2.5' }"
    >
      <template #header>
        <div class="flex items-center gap-2">
          <i class="pi pi-trophy text-amber-400"></i>
          <p class="text-sm font-semibold">Participant Stats</p>
        </div>
      </template>
      <template #content>
        <div v-if="!history?.participants.length" class="p-3 text-sm text-surface-400">
          No participants recorded yet.
        </div>
        <div v-else class="overflow-x-auto">
          <DataTable :value="history.participants" size="small" class="w-full text-sm compact-history-table">
            <Column field="name">
              <template #body="{ data }">
                <span class="font-semibold">{{ data.name }}</span>
              </template>
            </Column>
            <Column field="seasons_played" header="Seasons" />
            <Column field="average_wins">
              <template #header>
                <span class="p-datatable-column-title">Avg Wins</span>
                <button
                  v-if="history?.wins_normalized"
                  ref="winsTipBtn"
                  type="button"
                  class="pi pi-info-circle ml-1.5 align-middle text-xs text-surface-400 hover:text-surface-200 transition-colors"
                  aria-label="Why Avg Wins is adjusted"
                  @click.stop="toggleWinsTip"
                />
              </template>
              <template #body="{ data }">
                <span class="tabular-nums">{{ data.average_wins.toFixed(1) }}</span>
              </template>
            </Column>
            <Column field="average_finish" header="Avg Finish">
              <template #body="{ data }">
                <span class="tabular-nums">{{ data.average_finish.toFixed(2) }}</span>
              </template>
            </Column>
            <Column field="championships" header="Titles">
              <template #body="{ data }">
                <span
                  v-if="data.championships > 0"
                  class="inline-flex items-center gap-1 font-semibold text-amber-400"
                >
                  <span>🏆</span>
                  <span v-if="data.championships > 1" class="tabular-nums">x{{ data.championships }}</span>
                </span>
                <span v-else class="tabular-nums text-surface-400">0</span>
              </template>
            </Column>
          </DataTable>
        </div>

        <Teleport to="body">
          <div
            v-if="showWinsTip"
            ref="winsTipBubble"
            :style="{ ...winsTipStyle, transform: 'translate(-50%, -100%)' }"
            class="fixed z-50 w-max max-w-48 rounded-md border border-content bg-surface-800 px-2 py-1.5 text-xs whitespace-normal text-surface-100 shadow-lg"
          >
            Adjusted to {{ history?.baseline_team_count }} teams per roster
          </div>
        </Teleport>
      </template>
    </Card>
  </div>
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
