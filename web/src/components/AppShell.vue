<script setup lang="ts">
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Toast from 'primevue/toast'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useToast } from 'primevue/usetoast'
import { useRouter } from 'vue-router'
import { apiFetch } from '../api/client'
import { useScanner } from '../composables/useScanner'
import { useScanStore } from '../stores/scan'
import LocationPicker from './LocationPicker.vue'
import ScanModeBar from './ScanModeBar.vue'
import { useSession } from '../stores/session'
import { useSettings } from '../stores/settings'

interface Health {
  status: string
  database: 'ok' | 'error'
  maintenance?: boolean
}

const HEALTH_INTERVAL_MS = 30_000

const router = useRouter()
const session = useSession()
const settings = useSettings()
const scan = useScanStore()
const toast = useToast()

scan.bind({
  navigate: (path) => void router.push(path),
  notify: (severity, message) => toast.add({ severity, summary: message, life: severity === 'error' ? 6000 : 3000 }),
})

// One app-wide scanner listener so a scan works on every page; settings are read lazily as they load.
useScanner(
  () => ({
    minLength: Number(settings.get('scanner.min_length', 4)),
    maxGapMs: Number(settings.get('scanner.max_gap_ms', 30)),
    prefix: settings.get<string>('scanner.prefix', '') ?? '',
    suffix: settings.get<string>('scanner.suffix', '') ?? '',
    interceptInputs: settings.get<boolean>('scanner.intercept_inputs', true) !== false,
  }),
  (code) => void scan.submit(code),
)

const query = ref('')
const drawerOpen = ref(false)
const health = ref<Health | null>(null)
let timer: ReturnType<typeof setInterval> | undefined
let media: MediaQueryList | undefined

const nav = [
  { to: '/', label: 'Dashboard', icon: 'pi-home' },
  { to: '/search', label: 'Search', icon: 'pi-search' },
  { to: '/categories', label: 'Categories', icon: 'pi-tags' },
  { to: '/locations', label: 'Locations', icon: 'pi-map-marker' },
  { to: '/labels', label: 'Labels', icon: 'pi-print' },
  { to: '/import-export', label: 'Import / export', icon: 'pi-file-import' },
  { to: '/backups', label: 'Backups', icon: 'pi-database' },
  { to: '/trash', label: 'Trash', icon: 'pi-trash' },
  { to: '/settings', label: 'Settings', icon: 'pi-cog' },
]

const dbDown = computed(() => health.value?.database === 'error')
const maintenance = computed(() => health.value?.maintenance === true)

async function poll() {
  try {
    health.value = await apiFetch<Health>('/health')
  } catch {
    // Maintenance answers 503 for everything but /health; an unreachable server keeps the last state.
  }
}

function search() {
  const q = query.value.trim()
  void router.push({ path: '/search', query: q ? { q } : {} })
}

/** `display.theme`: light, dark, or system (follows prefers-color-scheme). */
function applyTheme() {
  const theme = settings.get<string>('display.theme', 'system')
  const dark = theme === 'dark' || (theme === 'system' && media?.matches === true)
  document.documentElement.classList.toggle('app-dark', dark)
}

watch(() => settings.get('display.theme'), applyTheme)
watch(() => router.currentRoute.value.fullPath, () => (drawerOpen.value = false))

onMounted(() => {
  media = window.matchMedia?.('(prefers-color-scheme: dark)')
  media?.addEventListener?.('change', applyTheme)
  applyTheme()
  void poll()
  timer = setInterval(poll, HEALTH_INTERVAL_MS)
})

onUnmounted(() => {
  clearInterval(timer)
  media?.removeEventListener?.('change', applyTheme)
})
</script>

<template>
  <div class="shell">
    <Toast />
    <header class="topbar">
      <Button class="menu-toggle" icon="pi pi-bars" text aria-label="Menu" @click="drawerOpen = !drawerOpen" />
      <strong class="brand">Pick2LIGHT</strong>
      <form class="search" role="search" @submit.prevent="search">
        <InputText v-model="query" type="search" data-scan-target placeholder="Search items…" aria-label="Search" fluid />
      </form>
      <div class="scan-bar"><slot name="scan-bar"><ScanModeBar /></slot></div>
      <Button v-if="session.mode === 'password'" icon="pi pi-sign-out" text aria-label="Log out" @click="session.logout()" />
    </header>

    <LocationPicker
      v-if="scan.pendingLocationChoice"
      :locations="scan.pendingLocationChoice.locations"
      @select="scan.chooseLocation($event)"
      @cancel="scan.cancelLocationChoice()"
    />

    <div v-if="dbDown" class="banner banner-error" role="alert">
      Database unreachable. The server is retrying; changes cannot be saved right now.
    </div>
    <div v-if="maintenance" class="banner banner-warn" role="status">Maintenance in progress</div>

    <div class="body">
      <nav class="sidenav" :class="{ open: drawerOpen }" aria-label="Main">
        <RouterLink v-for="n in nav" :key="n.to" :to="n.to">
          <i class="pi" :class="n.icon" aria-hidden="true" /> <span>{{ n.label }}</span>
        </RouterLink>
      </nav>
      <main class="content"><slot /></main>
    </div>
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; min-height: 100vh; }
.topbar { display: flex; align-items: center; gap: 0.75rem; padding: 0.5rem 1rem; border-bottom: 1px solid var(--p-content-border-color); }
.search { flex: 1; max-width: 32rem; }
.scan-bar { display: flex; align-items: center; }
.menu-toggle { display: none; }
.banner { padding: 0.5rem 1rem; font-weight: 600; }
.banner-error { background: var(--p-red-600, #dc2626); color: #fff; }
.banner-warn { background: var(--p-amber-400, #fbbf24); color: #000; }
.body { display: flex; flex: 1; min-height: 0; }
.sidenav { display: flex; flex-direction: column; width: 14rem; padding: 0.5rem; border-right: 1px solid var(--p-content-border-color); }
.sidenav a { display: flex; gap: 0.5rem; align-items: center; padding: 0.6rem 0.75rem; border-radius: 6px; color: inherit; text-decoration: none; }
.sidenav a.router-link-exact-active { background: var(--p-highlight-background); color: var(--p-highlight-color); }
.content { flex: 1; padding: 1rem; min-width: 0; }

@media (max-width: 767px) {
  .menu-toggle { display: inline-flex; }
  .brand { display: none; }
  .body { flex-direction: column; }
  /* Side nav becomes a drawer sliding up from the bottom edge. */
  .sidenav {
    position: fixed; left: 0; right: 0; bottom: 0; width: auto; z-index: 100;
    max-height: 70vh; overflow-y: auto;
    border-right: 0; border-top: 1px solid var(--p-content-border-color);
    background: var(--p-content-background);
    transform: translateY(100%); transition: transform 0.2s ease;
  }
  .sidenav.open { transform: translateY(0); }
}
</style>
