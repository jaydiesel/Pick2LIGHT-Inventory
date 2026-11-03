import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useSession } from '@/stores/session'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: () => import('@/views/Dashboard.vue') },
  { path: '/search', name: 'search', component: () => import('@/views/Search.vue') },
  { path: '/items/new', name: 'item-new', component: () => import('@/views/ItemEdit.vue') },
  { path: '/items/:id', name: 'item', component: () => import('@/views/ItemDetail.vue'), props: true },
  { path: '/items/:id/edit', name: 'item-edit', component: () => import('@/views/ItemEdit.vue'), props: true },
  { path: '/units/:id', name: 'unit', component: () => import('@/views/UnitDetail.vue'), props: true },
  { path: '/categories', name: 'categories', component: () => import('@/views/Categories.vue') },
  { path: '/categories/:id', name: 'category', component: () => import('@/views/CategoryEdit.vue'), props: true },
  { path: '/locations', name: 'locations', component: () => import('@/views/Locations.vue') },
  { path: '/locations/:id', name: 'location', component: () => import('@/views/LocationDetail.vue'), props: true },
  { path: '/labels', name: 'labels', component: () => import('@/views/Labels.vue') },
  { path: '/import-export', name: 'import-export', component: () => import('@/views/ImportExport.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/views/Settings.vue') },
  { path: '/backups', name: 'backups', component: () => import('@/views/Backups.vue') },
  { path: '/trash', name: 'trash', component: () => import('@/views/Trash.vue') },
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue'), meta: { bare: true } },
  { path: '/setup', name: 'setup', component: () => import('@/views/Setup.vue'), meta: { bare: true } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const session = useSession()
  if (!session.loaded) {
    try {
      await session.load()
    } catch {
      return true // server unreachable: let the page render its own error
    }
  }
  if (!session.setupCompleted) return to.name === 'setup' ? true : { name: 'setup' }
  if (to.name === 'setup') return { name: 'dashboard' }
  if (session.mode === 'password' && !session.authenticated && to.name !== 'login') {
    return { name: 'login', query: { next: to.fullPath } }
  }
  if (to.name === 'login' && (session.mode === 'none' || session.authenticated)) return { name: 'dashboard' }
  return true
})
