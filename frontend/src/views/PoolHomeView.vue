<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import SiteHeader from '@/components/common/SiteHeader.vue'
import PoolHistory from '@/components/pool/PoolHistory.vue'
import { usePool } from '@/composables/usePool'
import { usePoolHistory } from '@/composables/usePoolHistory'
import { isUuid } from '@/utils/ids'

const route = useRoute()
const router = useRouter()

const { pool, error: poolError, loading: poolLoading, fetchPoolById, fetchPoolBySlug } = usePool()
const { history, error: historyError, loading: historyLoading, fetchPoolHistory } = usePoolHistory()

const seasonsPlayed = computed(() => history.value?.seasons.length ?? 0)
const earliestSeason = computed(() => {
  const seasons = history.value?.seasons
  return seasons && seasons.length ? seasons[seasons.length - 1].season : null
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

  // Canonicalize a UUID in the URL to the pool's slug
  if (route.params.slug !== p.slug) {
    await router.replace({ name: 'pool', params: { slug: p.slug } })
  }

  await fetchPoolHistory(p.id)
}

watch(poolError, (err) => {
  if (err && String(err).includes('HTTP 404')) {
    router.replace({ name: 'not-found' })
  }
})

onMounted(() => {
  resolvePoolAndSlug()
})
</script>

<template>
  <SiteHeader>
    <template #left>
      <Button
        icon="pi pi-home"
        variant="outlined"
        severity="secondary"
        @click="router.push({ name: 'pools' })"
        aria-label="Browse pools"
      />
    </template>
  </SiteHeader>
  <main>
    <div class="flex flex-col items-center pb-2 pt-2">
      <p v-if="!poolLoading" class="text-3xl font-extrabold text-center">{{ pool?.name }}</p>
      <p v-else-if="poolError">{{ poolError }}</p>
      <p v-else>Loading pool...</p>
      <p v-if="seasonsPlayed" class="text-sm font-medium text-surface-400 text-center">
        {{ seasonsPlayed }} season{{ seasonsPlayed === 1 ? '' : 's' }}<span v-if="earliestSeason">
          · est. {{ earliestSeason }}</span
        >
      </p>
    </div>

    <div class="flex flex-col px-4 gap-4 mx-auto max-w-3xl w-full pb-8">
      <PoolHistory
        :pool-slug="pool?.slug ?? (route.params.slug as string)"
        :history="history"
        :loading="historyLoading || poolLoading"
        :error="historyError || poolError"
      />
    </div>
  </main>
</template>
