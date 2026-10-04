<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DocsLayout from '@/components/common/DocsLayout.vue'
import DocsActions from '@/components/docs/DocsActions.vue'
import { getDocsArticle } from '@/docs/registry'
import { renderDocs } from '@/docs/render'

const route = useRoute()
const router = useRouter()
const html = computed(() => {
  const article = getDocsArticle(route.name)
  return article ? renderDocs(article.body) : ''
})

function onClick(event: MouseEvent) {
  if (
    event.defaultPrevented ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.button !== 0
  )
    return
  const link = (event.target as HTMLElement).closest('a')
  const href = link?.getAttribute('href')
  if (!href || !href.startsWith('/')) return
  event.preventDefault()
  router.push(href)
}
</script>

<template>
  <DocsLayout>
    <!-- eslint-disable-next-line vue/no-v-html -->
    <div class="docs-content" @click="onClick" v-html="html" />
    <DocsActions />
  </DocsLayout>
</template>
