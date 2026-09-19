<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Button from 'primevue/button'
import Message from 'primevue/message'
import Textarea from 'primevue/textarea'
import PoolForm from '@/components/pool/PoolForm.vue'
import AuctionForm from '@/components/pool/AuctionForm.vue'
import SiteHeader from '@/components/common/SiteHeader.vue'
import { usePools } from '@/composables/usePools'
import { usePoolSeasons, type PoolSeason } from '@/composables/usePoolSeasons'
import { useRosters } from '@/composables/useRosters'
import { useAuctions } from '@/composables/useAuctions'
import type { Auction, AuctionCreate, AuctionUpdate, Pool, PoolCreate, PoolUpdate } from '@/types/pool'

const steps = ['Pool basics', 'Participants', 'Auction', 'Review']
const currentStep = ref(0)
const createdPool = ref<Pool | null>(null)
const createdSeason = ref<PoolSeason | null>(null)
const createdAuction = ref<Auction | null>(null)
const participantNames = ref('')
const participantCount = ref(0)
const importedParticipantCount = ref(0)
const importedLotCount = ref(0)
const submitting = ref(false)
const setupError = ref<string | null>(null)
const setupWarning = ref<string | null>(null)

const { createPool } = usePools()
const { createPoolSeason } = usePoolSeasons()
const { createRoster } = useRosters()
const { createAuction, importParticipantsFromPool, importNbaLots } = useAuctions()

const poolDestination = computed(() => {
  if (!createdPool.value || !createdSeason.value) return { name: 'pools' }
  return {
    name: 'pool-season',
    params: { slug: createdPool.value.slug, season: createdSeason.value.season },
  }
})

const auctionInitial = computed(() => ({
  pool_id: createdPool.value?.id || '',
  season: createdSeason.value?.season || '',
}))

const parsedParticipantNames = computed(() => {
  const uniqueNames = new Map<string, string>()
  participantNames.value
    .split('\n')
    .map((name) => name.trim())
    .filter(Boolean)
    .forEach((name) => uniqueNames.set(name.toLocaleLowerCase(), name))
  return [...uniqueNames.values()]
})

async function handlePoolCreate(payload: {
  pool: PoolCreate | PoolUpdate
  rules?: string | null
  season?: string
}) {
  if (!payload.season) return
  submitting.value = true
  setupError.value = null
  try {
    const pool = createdPool.value || (await createPool(payload.pool as PoolCreate))
    createdPool.value = pool
    createdSeason.value = await createPoolSeason(pool.id, {
      pool_id: pool.id,
      season: payload.season,
      rules: payload.rules || null,
    })
    currentStep.value = 1
  } catch (error) {
    setupError.value = error instanceof Error ? error.message : 'Failed to create pool'
  } finally {
    submitting.value = false
  }
}

async function saveParticipants() {
  if (!createdPool.value || !createdSeason.value) return
  if (parsedParticipantNames.value.length === 0) {
    setupError.value = 'Add at least one participant, or skip this step for now.'
    return
  }

  submitting.value = true
  setupError.value = null
  try {
    for (const name of parsedParticipantNames.value) {
      await createRoster({
        name,
        pool_id: createdPool.value.id,
        season: createdSeason.value.season,
      })
    }
    participantCount.value = parsedParticipantNames.value.length
    currentStep.value = 2
  } catch (error) {
    setupError.value = error instanceof Error ? error.message : 'Failed to add participants'
  } finally {
    submitting.value = false
  }
}

async function handleAuctionCreate(payload: AuctionCreate | AuctionUpdate) {
  submitting.value = true
  setupError.value = null
  setupWarning.value = null
  try {
    const auction = createdAuction.value || (await createAuction(payload as AuctionCreate))
    createdAuction.value = auction
    const importWarnings: string[] = []
    try {
      importedParticipantCount.value = await importParticipantsFromPool(auction.id)
    } catch (error) {
      importWarnings.push(error instanceof Error ? error.message : 'Participants were not imported')
    }
    try {
      importedLotCount.value = await importNbaLots(auction.id)
    } catch (error) {
      importWarnings.push(error instanceof Error ? error.message : 'NBA teams were not added')
    }
    setupWarning.value = importWarnings.length
      ? `${importWarnings.join(' ')} You can retry these actions from the draft room.`
      : null
    currentStep.value = 3
  } catch (error) {
    setupError.value = error instanceof Error ? error.message : 'Failed to prepare auction'
  } finally {
    submitting.value = false
  }
}

function skipParticipants() {
  setupError.value = null
  currentStep.value = 2
}

function skipAuction() {
  setupError.value = null
  currentStep.value = 3
}
</script>

<template>
  <div class="min-h-screen">
    <SiteHeader />

    <main class="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
      <div class="flex flex-col gap-5 border-b border-[var(--p-content-border-color)] pb-8 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p class="text-sm font-bold uppercase tracking-[0.16em] text-emerald-400">Commissioner setup</p>
          <h1 class="mt-2 text-4xl font-bold sm:text-5xl">Create your pool</h1>
          <p class="mt-3 max-w-2xl text-zinc-400">Set up the essentials now. Once the pool is created, you can leave and return to anything unfinished.</p>
        </div>
        <RouterLink
          v-if="createdPool"
          :to="poolDestination"
          custom
          v-slot="{ navigate }"
        >
          <Button label="Exit setup" icon="pi pi-arrow-right" iconPos="right" severity="secondary" outlined @click="navigate" />
        </RouterLink>
        <RouterLink v-else :to="{ name: 'home' }" custom v-slot="{ navigate }">
          <Button label="Cancel" severity="secondary" text @click="navigate" />
        </RouterLink>
      </div>

      <ol class="grid grid-cols-2 border-b border-[var(--p-content-border-color)] sm:grid-cols-4" aria-label="Setup progress">
        <li
          v-for="(step, index) in steps"
          :key="step"
          class="border-b-2 px-2 py-4 text-sm"
          :class="index === currentStep ? 'border-primary text-primary' : index < currentStep ? 'border-zinc-600 text-zinc-300' : 'border-transparent text-zinc-600'"
          :aria-current="index === currentStep ? 'step' : undefined"
        >
          <span class="mr-2 font-mono text-xs">0{{ index + 1 }}</span>{{ step }}
        </li>
      </ol>

      <div class="mx-auto mt-10 max-w-2xl">
        <section v-if="currentStep === 0" aria-labelledby="basics-heading">
          <h2 id="basics-heading" class="text-3xl font-bold">Name the season</h2>
          <p class="mb-8 mt-2 text-zinc-400">This creates a public pool page and its first season.</p>
          <PoolForm mode="create" :submitting="submitting" :error="setupError" @submit="handlePoolCreate" />
        </section>

        <section v-else-if="currentStep === 1" aria-labelledby="participants-heading">
          <h2 id="participants-heading" class="text-3xl font-bold">Who’s playing?</h2>
          <p class="mt-2 text-zinc-400">Add one participant per line. These names become the rosters used in standings and the auction.</p>
          <label for="participants" class="mt-8 block font-semibold text-zinc-200">Participant names</label>
          <Textarea
            id="participants"
            v-model="participantNames"
            rows="8"
            autoResize
            class="mt-2 w-full"
            placeholder="Avery&#10;Jordan&#10;Sam"
          />
          <p class="mt-2 text-sm text-zinc-500">{{ parsedParticipantNames.length }} unique participant{{ parsedParticipantNames.length === 1 ? '' : 's' }}</p>
          <Message v-if="setupError" class="mt-5" severity="error">{{ setupError }}</Message>
          <div class="mt-8 flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
            <Button label="Skip for now" severity="secondary" variant="text" @click="skipParticipants" />
            <Button label="Save and continue" icon="pi pi-arrow-right" iconPos="right" :loading="submitting" @click="saveParticipants" />
          </div>
        </section>

        <section v-else-if="currentStep === 2" aria-labelledby="auction-heading">
          <h2 id="auction-heading" class="text-3xl font-bold">Prepare an auction</h2>
          <p class="mt-2 text-zinc-400">Optional. Choose the limits and budget; we’ll add your participants and all NBA teams automatically.</p>
          <div class="mt-8">
            <AuctionForm
              mode="create"
              :initial="auctionInitial"
              :submitting="submitting"
              :error="setupError"
              @submit="handleAuctionCreate"
            />
          </div>
          <Button class="mt-4" label="Skip auction setup" severity="secondary" variant="text" @click="skipAuction" />
        </section>

        <section v-else aria-labelledby="review-heading">
          <p class="text-5xl" aria-hidden="true">🏆</p>
          <h2 id="review-heading" class="mt-5 text-4xl font-bold">Your pool is ready.</h2>
          <p class="mt-3 text-lg text-zinc-400">Head to the pool page now, or open the draft room if you prepared an auction.</p>

          <dl class="mt-8 divide-y divide-[var(--p-content-border-color)] border-y border-[var(--p-content-border-color)]">
            <div class="flex justify-between gap-5 py-4"><dt class="text-zinc-500">Pool</dt><dd class="font-bold text-white">{{ createdPool?.name }}</dd></div>
            <div class="flex justify-between gap-5 py-4"><dt class="text-zinc-500">Season</dt><dd class="font-bold text-white">{{ createdSeason?.season }}</dd></div>
            <div class="flex justify-between gap-5 py-4"><dt class="text-zinc-500">Participants</dt><dd class="font-bold text-white">{{ participantCount || 'Not added yet' }}</dd></div>
            <div class="flex justify-between gap-5 py-4"><dt class="text-zinc-500">Auction</dt><dd class="text-right font-bold text-white">{{ createdAuction ? `${importedParticipantCount} participants · ${importedLotCount} teams` : 'Skipped' }}</dd></div>
          </dl>

          <Message v-if="setupWarning" class="mt-6" severity="warn">{{ setupWarning }}</Message>
          <Message v-else-if="!createdAuction || participantCount === 0" class="mt-6" severity="secondary">
            You can finish missing setup from the pool page.
          </Message>

          <div class="mt-8 flex flex-col gap-3 sm:flex-row">
            <RouterLink
              :to="poolDestination"
              class="flex-1"
              custom
              v-slot="{ navigate }"
            >
              <Button class="w-full" size="large" label="Open pool" icon="pi pi-arrow-right" iconPos="right" @click="navigate" />
            </RouterLink>
            <RouterLink
              v-if="createdAuction"
              :to="{ name: 'auction-overview', params: { auctionId: createdAuction.id } }"
              class="flex-1"
              custom
              v-slot="{ navigate }"
            >
              <Button class="w-full" size="large" label="Open draft room" icon="pi pi-megaphone" severity="secondary" outlined @click="navigate" />
            </RouterLink>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>