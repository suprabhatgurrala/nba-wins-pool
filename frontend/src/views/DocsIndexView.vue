<script setup lang="ts">
import { RouterLink } from 'vue-router'
import SiteHeader from '@/components/common/SiteHeader.vue'
import { docsArticles } from '@/docs/registry'
</script>

<template>
  <div class="min-h-screen">
    <SiteHeader />

    <main class="mx-auto max-w-3xl px-5 py-8 sm:px-8 sm:py-12">
      <header class="pb-8">
        <h1 class="text-4xl font-bold leading-tight sm:text-5xl">Docs</h1>
      </header>

        <RouterLink
          v-for="article in docsArticles"
          :key="article.name"
          :to="{ name: article.name }"
          class="group flex items-start justify-between gap-4 border-b border-[var(--p-content-border-color)] py-5"
        >
          <span>
            <span class="block text-lg font-semibold group-hover:text-primary">{{ article.navigationTitle }}</span>
            <span class="mt-1 block text-sm leading-6 text-zinc-400">{{ article.description }}</span>
          </span>
          <i class="pi pi-angle-right mt-1 shrink-0 text-sm text-zinc-500 group-hover:text-primary" aria-hidden="true"></i>
        </RouterLink>
    </main>
  </div>
</template>