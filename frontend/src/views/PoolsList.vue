<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { usePools } from '@/composables/usePools'
import { usePoolSeasons } from '@/composables/usePoolSeasons'
import { getCurrentSeason } from '@/utils/season'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Tag from 'primevue/tag'
import IconField from 'primevue/iconfield';
import InputIcon from 'primevue/inputicon';
import InputText from 'primevue/inputtext';
import { RouterLink } from 'vue-router'
import Dialog from 'primevue/dialog'
import PoolForm from '@/components/pool/PoolForm.vue'
import type { PoolCreate, PoolUpdate, Pool } from '@/types/pool'

const { pools, error, loading, fetchPools, createPool } = usePools()
const { createPoolSeason, fetchPoolSeasons } = usePoolSeasons()
const searchQuery = ref('')
const poolSeasons = ref<Record<string, Array<{ id: string; season: string }>>>({})

// Modal state
const showCreate = ref(false)
const submitting = ref(false)
const submitError = ref<string | null>(null)

// Search
const filteredPools = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return pools.value
  return pools.value.filter((p) => {
    const name = p.name?.toLowerCase() ?? ''
    const desc = p.description?.toLowerCase() ?? ''
    const slug = p.slug?.toLowerCase() ?? ''
    return name.includes(q) || desc.includes(q) || slug.includes(q)
  })
})

// Helper to get the link for a pool - navigates directly to most recent season
function getPoolLink(pool: Pool) {
  const seasons = poolSeasons.value[pool.id]
  const mostRecentSeason = seasons?.[0]?.season || getCurrentSeason()
  return { name: 'pool-season', params: { slug: pool.slug, season: mostRecentSeason } }
}

onMounted(async () => {
  // Fetch pools with seasons in a single optimized batch query
  await fetchPools(true)
  
  // Build the poolSeasons map from the included seasons
  poolSeasons.value = pools.value.reduce((acc, pool) => {
    // @ts-ignore - seasons is dynamically added by backend when include_seasons=true
    acc[pool.id] = pool.seasons || []
    return acc
  }, {} as Record<string, Array<{ id: string; season: string }>>)
})

async function handleCreate(payload: { pool: PoolCreate | PoolUpdate; rules?: string | null; season?: string }) {
  submitting.value = true
  submitError.value = null
  try {
    const createdPool = await createPool(payload.pool as PoolCreate)
    
    // Create the pool season with rules if provided
    if (payload.season && createdPool) {
      try {
        await createPoolSeason(createdPool.id, {
          pool_id: createdPool.id,
          season: payload.season,
          rules: payload.rules || null
        })
      } catch (e) {
        console.error('Failed to create pool season:', e)
        // Don't fail the whole operation if pool season creation fails
      }
    }
    
    showCreate.value = false
  } catch (e: any) {
    submitError.value = e?.message || 'Failed to create pool'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <header>
    <div class="flex items-center justify-center p-4">
      <p class="text-2xl font-bold">🏀 NBA Wins Pool 🏆</p>
    </div>
  </header>
  <!-- <BaseToolbar/> -->
  <main class="container mx-auto max-w-3xl min-w-min px-4 pb-4">
    <div class="flex w-full mb-4 gap-2">
      <IconField class="flex-1">
        <InputIcon class="pi pi-search" />
        <InputText class="w-full" v-model="searchQuery" placeholder="Search Pools" />
      </IconField>
      <Button label="New Pool" icon="pi pi-plus" @click="showCreate = true"/>
    </div>
    <div v-if="loading">Loading pools…</div>
    <div v-else-if="error" class="text-red-400">⚠️ {{ error }}</div>
    <div v-else class="grid gap-4">
      <div v-for="p in filteredPools" :key="p.id" class="group">
        <RouterLink :to="getPoolLink(p)">
          <Card class="border-1 border-[var(--p-content-border-color)] group-hover:border-primary" >
            <template #title>
              <div class="flex justify-between">
                <span>{{ p.name }}</span>
                <span class="inline-block transition-transform group-hover:translate-x-1">→</span>
              </div>
            </template>
            <template #subtitle>
              <span v-if="p.description">{{ p.description }}</span>
              <span v-else-if="p.rules">{{ p.rules }}</span>
            </template>
            <template #footer>
              <div class="flex items-center gap-2 flex-wrap">
                <Tag v-if="p.slug" :value="p.slug" rounded />
                <RouterLink
                  v-for="s in poolSeasons[p.id] || []"
                  :key="s.id"
                  :to="{ name: 'pool-season', params: { slug: p.slug, season: s.season } }"
                  @click.stop
                >
                  <Button
                    :label="s.season"
                    outlined
                    rounded
                    size="small"
                    severity="secondary"
                  />
                </RouterLink>
              </div>
            </template>
          </Card>
        </RouterLink>
      </div>
    </div>
    <div v-if="!loading && !error && filteredPools.length === 0" class="text-center">{{ searchQuery ? 'No matching pools.' : 'No pools found.' }}</div>
    
    <Dialog 
      v-model:visible="showCreate" 
      modal 
      :draggable="false" 
      dismissableMask 
      class="container max-w-lg m-2" 
      @hide="showCreate = false"
    >
    <template #header>
      <p class="text-2xl font-semibold">Create New Pool</p>
    </template>
      <PoolForm
          mode="create"
          :submitting="submitting"
          :error="submitError"
          @submit="handleCreate"
        />
    </Dialog>
  </main>
</template>

