<script setup lang="ts">
import ConfirmDialog from 'primevue/confirmdialog'
import Toast from 'primevue/toast'
import { onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from '@/components/AppShell.vue'
import { useSession } from '@/stores/session'
import { useSettings } from '@/stores/settings'

const route = useRoute()
const session = useSession()
const settings = useSettings()
const media = window.matchMedia?.('(prefers-color-scheme: dark)')

function applyTheme() {
  const theme = settings.get<string>('display.theme', 'system')
  const dark = theme === 'dark' || (theme === 'system' && !!media?.matches)
  document.documentElement.classList.toggle('p2l-dark', dark)
}

onMounted(async () => {
  media?.addEventListener?.('change', applyTheme)
  try {
    await settings.load()
  } catch {
    /* public settings unavailable: keep defaults */
  }
  applyTheme()
})
watch(() => settings.values['display.theme'], applyTheme)
watch(
  () => session.authenticated,
  async (ok) => {
    if (ok) await settings.load(true).catch(() => settings.load())
  },
)
</script>

<template>
  <Toast position="bottom-right" />
  <ConfirmDialog />
  <RouterView v-if="route.meta.bare" />
  <AppShell v-else>
    <RouterView />
  </AppShell>
</template>
