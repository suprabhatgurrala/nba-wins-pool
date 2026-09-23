import { createRouter, createWebHistory } from 'vue-router'
import PoolSeasonOverview from '../views/PoolSeasonOverview.vue'
import PoolHomeView from '../views/PoolHomeView.vue'
import AuctionOverview from '../views/AuctionOverview.vue'
import PoolsList from '../views/PoolsList.vue'
import NotFound from '../views/NotFound.vue'
import HomeView from '../views/HomeView.vue'
import DocsIndexView from '../views/DocsIndexView.vue'
import { docsArticles } from '@/docs/registry'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior(to) {
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    return { top: 0 }
  },
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/docs',
      name: 'docs-index',
      component: DocsIndexView,
      meta: {
        title: 'Docs',
      },
    },
    ...docsArticles.map((article) => ({
      path: article.path,
      name: article.name,
      component: article.component,
      meta: {
        title: article.title,
        description: article.description,
      },
    })),
    {
      path: '/pools/:slug/season/:season',
      name: 'pool-season',
      component: PoolSeasonOverview,
    },
    {
      path: '/pools',
      name: 'pools',
      component: PoolsList,
    },
    {
      path: '/auctions/:auctionId',
      name: 'auction-overview',
      component: AuctionOverview,
    },
    {
      path: '/pools/:slug',
      name: 'pool',
      component: PoolHomeView,
    },
    {
      path: '/404',
      name: 'not-found',
      component: NotFound,
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: { name: 'not-found' },
    },
  ],
})

router.afterEach((to) => {
  const title = to.meta.title
  document.title = typeof title === 'string' ? `${title} | NBA Wins Pool` : 'NBA Wins Pool'
})

// Global error handler: redirect to 404 on unexpected navigation errors (e.g., chunk load failures)
router.onError((err) => {
  if (router.currentRoute.value.name !== 'not-found') {
    console.error('Router error:', err)
    router.replace({ name: 'not-found' }).catch(() => {})
  }
})

export default router
