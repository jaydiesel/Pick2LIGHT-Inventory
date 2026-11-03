<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { apiFetch } from '@/api/client'
import { useSession } from '@/stores/session'

const router = useRouter()
const session = useSession()
const query = ref('')
const navOpen = ref(false)
const dbDown = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

const nav = [
  { to: '/', label: 'Dashboard', icon: 'pi-home' },
  { to: '/search', label: 'Search', icon: 'pi-search' },
  { to: '/items/new', label: 'Add item', icon: 'pi-plus' },
  { to: '/locations', label: 'Locations', icon: 'pi-map-marker' },
  { to: '/categories', label: 'Categories', icon: 'pi-sitemap' },
  { to: '/labels', label: 'Labels', icon: 'pi-tag' },
  { to: '/import-export', label: 'Import / export', icon: 'pi-file-import' },
  { to: '/backups', label: 'Backups', icon: 'pi-database' },
  { to: '/trash', label: 'Trash', icon: 'pi-trash' },
  { to: '/settings', label: 'Settings', icon: 'pi-cog' },
]

function search() {
  const q = query.value.trim()
  router.push({ name: 'search', query: q ? { q } : {} })
}

async function checkHealth() {
  try {
    const h = await apiFetch<{ database: string }>('/health')
    dbDown.value = h.database !== 'ok'
  } catch {
    dbDown.value = true
  }
}

async function logout() {
  await session.logout()
  router.push({ name: 'login' })
}

onMounted(() => {
  checkHealth()
  timer = setInterval(checkHealth, 30_000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="shell">
    <header class="top">
      <button class="p2l-btn menu" aria-label="Menu" @click="navOpen = !navOpen"><i class="pi pi-bars" /></button>
      <RouterLink to="/" class="brand">Pick2<b>LIGHT</b></RouterLink>
      <form class="searchbox" role="search" @submit.prevent="search">
        <input
          v-model="query"
          class="p2l-input"
          type="search"
          data-scan-target
          placeholder="Search name, SKU, value… or scan"
          aria-label="Search"
        />
      </form>
      <slot name="toolbar" />
      <button v-if="session.mode === 'password' && session.authenticated" class="p2l-btn" @click="logout">
        Log out
      </button>
    </header>
    <div v-if="dbDown" class="banner" role="alert">The database is not reachable. Changes can't be saved right now.</div>
    <nav :class="['nav', { open: navOpen }]" @click="navOpen = false">
      <RouterLink v-for="n in nav" :key="n.to" :to="n.to" class="nav-link">
        <i :class="['pi', n.icon]" /> <span>{{ n.label }}</span>
      </RouterLink>
    </nav>
    <main class="main"><slot /></main>
  </div>
</template>

<style scoped>
.shell { display: grid; grid-template-columns: 220px 1fr; grid-template-rows: auto auto 1fr; min-height: 100vh; }
.top { grid-column: 1 / -1; display: flex; gap: .75rem; align-items: center; padding: .6rem 1rem; background: var(--p2l-surface); border-bottom: 1px solid var(--p2l-border); position: sticky; top: 0; z-index: 10; flex-wrap: wrap; }
.brand { font-size: 1.15rem; text-decoration: none; color: var(--p2l-text); white-space: nowrap; }
.brand b { color: var(--p2l-accent); }
.searchbox { flex: 1; min-width: 180px; display: flex; }
.searchbox input { width: 100%; }
.menu { display: none; }
.banner { grid-column: 1 / -1; background: var(--p2l-danger); color: #fff; padding: .5rem 1rem; }
.nav { display: flex; flex-direction: column; padding: .75rem; gap: .15rem; border-right: 1px solid var(--p2l-border); background: var(--p2l-surface); }
.nav-link { display: flex; gap: .6rem; align-items: center; padding: .5rem .65rem; border-radius: 6px; text-decoration: none; color: var(--p2l-text); }
.nav-link.router-link-exact-active { background: var(--p2l-bg); color: var(--p2l-accent); font-weight: 600; }
.main { padding: 1rem; min-width: 0; }
@media (max-width: 768px) {
  .shell { grid-template-columns: 1fr; }
  .menu { display: inline-block; }
  .nav { display: none; position: fixed; inset: auto 0 0 0; max-height: 70vh; overflow: auto; z-index: 20; border-top: 1px solid var(--p2l-border); border-right: 0; box-shadow: 0 -4px 16px rgba(0,0,0,.2); }
  .nav.open { display: flex; }
}
</style>
