import { createRouter, createWebHistory } from 'vue-router'
import PoolSeasonOverview from '../views/PoolSeasonOverview.vue'
import AuctionOverview from '../views/AuctionOverview.vue'
import PoolsList from '../views/PoolsList.vue'
import NotFound from '../views/NotFound.vue'
import AuctionView from '@/views/AuctionView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'root',
      redirect: '/pools',
    },
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
      component: PoolSeasonOverview,
    },
    {
      path: '/:poolId/auction',
      name: 'auction',
      component: AuctionView,
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

// Global error handler: redirect to 404 on unexpected navigation errors (e.g., chunk load failures)
router.onError((err) => {
  if (router.currentRoute.value.name !== 'not-found') {
    console.error('Router error:', err)
    router.replace({ name: 'not-found' }).catch(() => {})
  }
})

export default router


