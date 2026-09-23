<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { usePools } from '@/composables/usePools'
import { getCurrentSeason } from '@/utils/season'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Tag from 'primevue/tag'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import InputText from 'primevue/inputtext'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import SiteHeader from '@/components/common/SiteHeader.vue'
import CreatePoolDialog from '@/components/pool/CreatePoolDialog.vue'
import type { Pool } from '@/types/pool'

const { pools, error, loading, fetchPools } = usePools()
const route = useRoute()
const router = useRouter()
const searchQuery = ref('')
const poolSeasons = ref<Record<string, Array<{ id: string; season: string }>>>({})

const showCreate = ref(false)

function handleCreateVisibility(visible: boolean) {
  showCreate.value = visible
  if (!visible && route.query.create) {
    const { create: _, ...query } = route.query
    router.replace({ query })
  }
}

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

// Each pool card exposes its history hub (all seasons) plus quick links to the most recent seasons
function historyLink(pool: Pool) {
  return { name: 'pool', params: { slug: pool.slug } }
}

function recentSeasons(pool: Pool): string[] {
  const seasons = poolSeasons.value[pool.id]?.map((s) => s.season)
  return seasons && seasons.length ? seasons.slice(0, 2) : [getCurrentSeason()]
}

function seasonLink(pool: Pool, season: string) {
  return { name: 'pool-season', params: { slug: pool.slug, season } }
}

function buildPoolSeasons() {
  poolSeasons.value = pools.value.reduce(
    (acc, pool) => {
      // @ts-ignore - seasons is dynamically added by backend when include_seasons=true
      acc[pool.id] = pool.seasons || []
      return acc
    },
    {} as Record<string, Array<{ id: string; season: string }>>,
  )
}

onMounted(async () => {
  showCreate.value = route.query.create === '1'

  // Fetch pools with seasons in a single optimized batch query
  await fetchPools(true)
  buildPoolSeasons()
})

watch(
  () => route.query.create,
  (create) => {
    if (create === '1') showCreate.value = true
  },
)

async function handleCreated() {
  await fetchPools(true)
  buildPoolSeasons()
}
</script>

<template>
  <SiteHeader />
  <main class="container mx-auto max-w-3xl min-w-min px-4 pb-4">
    <div class="flex w-full mb-4 gap-2 pt-6">
      <IconField class="flex-1">
        <InputIcon class="pi pi-search" />
        <InputText class="w-full" v-model="searchQuery" placeholder="Search Pools" />
      </IconField>
      <Button label="New Pool" icon="pi pi-plus" outlined @click="showCreate = true" />
    </div>
    <div v-if="loading">Loading pools…</div>
    <div v-else-if="error" class="text-red-400">⚠️ {{ error }}</div>
    <div v-else class="grid gap-4">
      <div v-for="p in filteredPools" :key="p.id" class="group cursor-pointer" @click="router.push(historyLink(p))">
        <Card class="border-2 border-[var(--p-content-border-color)] group-hover:border-primary">
          <template #title>
            <div class="flex items-baseline justify-between gap-3">
              <span>{{ p.name }}</span>
              <span
                class="inline-block flex-shrink-0 text-surface-400 transition-transform group-hover:translate-x-1 group-hover:text-primary"
                >→</span
              >
            </div>
          </template>
          <template #subtitle>
            <span v-if="p.description">{{ p.description }}</span>
            <span v-else-if="p.rules">{{ p.rules }}</span>
          </template>
          <template #footer>
            <div class="flex items-center gap-2 flex-wrap">
              <Tag v-if="p.slug" :value="p.slug" rounded />
              <div class="flex gap-2 ml-auto">
                <RouterLink :to="historyLink(p)" @click.stop>
                  <Button label="All Seasons" outlined rounded size="small" severity="secondary" />
                </RouterLink>
                <RouterLink
                  v-for="s in recentSeasons(p)"
                  :key="s"
                  :to="seasonLink(p, s)"
                  @click.stop
                >
                  <Button :label="s" outlined rounded size="small" severity="secondary" />
                </RouterLink>
              </div>
            </div>
          </template>
        </Card>
      </div>
    </div>
    <div v-if="!loading && !error && filteredPools.length === 0" class="text-center">
      {{ searchQuery ? 'No matching pools.' : 'No pools found.' }}
    </div>

    <CreatePoolDialog
      :visible="showCreate"
      @update:visible="handleCreateVisibility"
      @created="handleCreated"
    />
  </main>
</template>
