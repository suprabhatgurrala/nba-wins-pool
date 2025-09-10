import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import AuctionView from '@/views/AuctionView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      redirect: '/sg',
      children: [],
    },
    {
      path: '/:poolId',
      name: 'pool',
      component: HomeView,
    },
    {
      path: '/:poolId/auction',
      name: 'auction',
      component: AuctionView,
    },
  ],
})

export default router
