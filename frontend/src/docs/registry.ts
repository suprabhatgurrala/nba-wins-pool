import type { Component } from 'vue'
import AboutPoolView from '@/views/AboutPoolView.vue'
import AuctionGuideView from '@/views/AuctionGuideView.vue'

export type DocsRouteName = 'pool-guide' | 'auction-guide'

export type DocsArticle = {
  name: DocsRouteName
  path: string
  navigationTitle: string
  title: string
  description: string
  component: Component
}

export const docsArticles: DocsArticle[] = [
  {
    name: 'pool-guide',
    path: '/docs/pools',
    navigationTitle: 'Wins Pools',
    title: 'How a wins pool works',
    description: 'A season-long competition where participants own teams and combine their wins.',
    component: AboutPoolView,
  },
  {
    name: 'auction-guide',
    path: '/docs/auction',
    navigationTitle: 'Auction Draft',
    title: 'How the auction works',
    description: 'Participants bid on team lots in real time to build their rosters.',
    component: AuctionGuideView,
  },
]

export function getDocsArticle(name: unknown): DocsArticle | undefined {
  return docsArticles.find((article) => article.name === name)
}
