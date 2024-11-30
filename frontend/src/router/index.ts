import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'

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
  ],
})

export default router
