<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { RouterLink } from 'vue-router'
import SiteHeader from '@/components/common/SiteHeader.vue'
import { getDocsArticle } from '@/docs/registry'

const route = useRoute()
const article = computed(() => getDocsArticle(route.name))
</script>

<template>
  <div class="min-h-screen">
    <SiteHeader />

    <main class="mx-auto max-w-3xl px-5 py-8 sm:px-8 sm:py-12">
      <nav class="mb-7 flex items-center gap-2 text-sm text-zinc-500" aria-label="Breadcrumb">
        <RouterLink
          :to="{ name: 'docs-index' }"
          class="hover:text-primary hover:underline"
        >
          Docs
        </RouterLink>
        <i class="pi pi-angle-right text-xs" aria-hidden="true"></i>
        <span aria-current="page">{{ article?.navigationTitle }}</span>
      </nav>

      <article class="docs-article">
        <header>
          <h1 class="text-4xl font-bold leading-tight sm:text-5xl">{{ article?.title }}</h1>
          <p class="docs-lede">{{ article?.description }}</p>
        </header>
        <slot />
      </article>
    </main>
  </div>
</template>