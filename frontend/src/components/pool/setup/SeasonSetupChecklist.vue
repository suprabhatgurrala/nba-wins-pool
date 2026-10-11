<script setup lang="ts">
import { ref } from 'vue'
import Card from 'primevue/card'
import SetupParticipantsStep from '@/components/pool/setup/SetupParticipantsStep.vue'
import SetupAuctionStep from '@/components/pool/setup/SetupAuctionStep.vue'
import type { Auction, Pool, Roster } from '@/types/pool'

type Step = 'participants' | 'auction'

const props = defineProps<{
  pool: Pool
  season: string
  poolSeason: { id: string } | null
  previousSeasons: { id: string; season: string }[]
  rosters: Roster[]
  auction: Auction | null
  importingRosters: boolean
}>()

const emit = defineEmits<{
  changed: []
  'import-rosters': []
}>()

const steps: { key: Step; label: string }[] = [
  { key: 'participants', label: 'Participants' },
  { key: 'auction', label: 'Auction' },
]

function firstIncomplete(): Step {
  return props.rosters.length === 0 ? 'participants' : 'auction'
}

const current = ref<Step>(firstIncomplete())
const currentIndex = () => steps.findIndex((s) => s.key === current.value)

function canOpen(step: Step) {
  return step === 'participants' || props.rosters.length > 0
}
</script>

<template>
  <Card
    class="border-2 rounded-xl overflow-hidden border-[var(--p-content-border-color)] max-w-2xl w-full mx-auto"
    :pt="{ body: 'p-0' }"
    data-testid="season-setup"
  >
    <template #content>
      <div class="flex flex-col gap-6 p-4">
        <ol class="flex" aria-label="Setup progress">
          <li
            v-for="(s, i) in steps"
            :key="s.key"
            class="relative flex flex-1 flex-col items-center gap-1.5"
            :aria-current="i === currentIndex() ? 'step' : undefined"
          >
            <span
              v-if="i > 0"
              class="absolute top-[0.875rem] right-1/2 h-0.5 w-full -translate-y-1/2"
              :class="i <= currentIndex() ? 'bg-primary' : 'bg-[var(--p-content-border-color)]'"
              aria-hidden="true"
            ></span>
            <button
              type="button"
              class="relative flex flex-col items-center gap-1.5 rounded-md px-2 py-0.5 focus-visible:outline-2 focus-visible:outline-primary enabled:cursor-pointer disabled:cursor-not-allowed"
              :disabled="!canOpen(s.key)"
              :aria-label="`Go to ${s.label}`"
              @click="current = s.key"
            >
              <span
                class="relative z-10 flex size-6 items-center justify-center rounded-full text-xs font-bold"
                :class="
                  i <= currentIndex()
                    ? 'bg-primary text-primary-contrast'
                    : 'border-2 border-[var(--p-content-border-color)] bg-[var(--p-content-background)] text-surface-400'
                "
              >
                <i
                  v-if="i < currentIndex() || (auction && i === currentIndex())"
                  class="pi pi-check text-[0.65rem]"
                  aria-hidden="true"
                ></i>
                <template v-else>{{ i + 1 }}</template>
              </span>
              <span
                class="text-xs"
                :class="i === currentIndex() ? 'font-semibold' : 'text-surface-400'"
                >{{ s.label }}</span
              >
            </button>
          </li>
        </ol>

        <SetupParticipantsStep
          v-if="current === 'participants'"
          :pool="pool"
          :season="season"
          :pool-season="poolSeason"
          :previous-seasons="previousSeasons"
          :rosters="rosters"
          :auction="auction"
          @changed="emit('changed')"
          @next="current = 'auction'"
        />
        <SetupAuctionStep
          v-else
          :pool="pool"
          :season="season"
          :auction="auction"
          :participant-count="rosters.length"
          :importing-rosters="importingRosters"
          @changed="emit('changed')"
          @back="current = 'participants'"
          @import-rosters="emit('import-rosters')"
        />
      </div>
    </template>
  </Card>
</template>
