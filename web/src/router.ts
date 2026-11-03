import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useSession } from './stores/session'

const placeholder = () => import('./views/Placeholder.vue')

function page(path: string, title: string): RouteRecordRaw {
  return { path, component: placeholder, meta: { title } }
}

export const routes: RouteRecordRaw[] = [
  page('/', 'Dashboard'),
  page('/search', 'Search'),
  page('/items/new', 'New item'),
  page('/items/:id', 'Item'),
  page('/items/:id/edit', 'Edit item'),
  page('/units/:id', 'Unit'),
  page('/categories', 'Categories'),
  page('/categories/:id', 'Category'),
  page('/locations', 'Locations'),
  page('/locations/:id', 'Location'),
  page('/labels', 'Labels'),
  page('/import-export', 'Import / export'),
  page('/settings', 'Settings'),
  page('/backups', 'Backups'),
  page('/trash', 'Trash'),
  { path: '/login', component: () => import('./views/Login.vue'), meta: { bare: true, public: true } },
  { path: '/setup', component: () => import('./views/Setup.vue'), meta: { bare: true, public: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const session = useSession()
  if (!session.loaded || to.path === '/login' || to.path === '/setup') await session.load()

  if (!session.setupCompleted) return to.path === '/setup' ? true : '/setup'
  if (to.path === '/setup') return '/'
  if (session.mode === 'password' && !session.authenticated && to.path !== '/login') {
    return { path: '/login', query: { next: to.fullPath } }
  }
  if (to.path === '/login' && (session.authenticated || session.mode === 'none')) return '/'
  return true
})

export default router
