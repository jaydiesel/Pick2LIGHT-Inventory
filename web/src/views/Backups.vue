<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { onMounted, ref } from 'vue'

import { ApiError, apiFetch } from '@/api/client'
import type { BackupInfo, BackupList } from '@/api/types'
import AppModal from '@/components/AppModal.vue'

const toast = useToast()
const list = ref<BackupList | null>(null)
const busy = ref(false)
const restoring = ref<BackupInfo | null>(null)
const confirmText = ref('')
const overlay = ref(false)
const error = ref('')

async function load() {
  list.value = await apiFetch<BackupList>('/backups')
}

function size(n: number) {
  return n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} kB`
}

function fail(e: unknown) {
  error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
}

async function backupNow() {
  busy.value = true
  error.value = ''
  try {
    const info = await apiFetch<BackupInfo>('/backups', { method: 'POST' })
    toast.add({ severity: 'success', summary: 'Backup written', detail: info.name, life: 3000 })
    await load()
  } catch (e) {
    fail(e)
  } finally {
    busy.value = false
  }
}

async function upload(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  const body = new FormData()
  body.append('file', file)
  try {
    await apiFetch('/backups/upload', { method: 'POST', body })
    await load()
  } catch (e) {
    fail(e)
  }
}

async function waitForServer() {
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 1000))
    try {
      const h = await apiFetch<{ maintenance?: boolean }>('/health')
      if (!h.maintenance) return
    } catch {
      /* server busy */
    }
  }
}

async function restore() {
  const b = restoring.value
  if (!b) return
  restoring.value = null
  overlay.value = true
  error.value = ''
  try {
    const request = apiFetch(`/backups/${b.name}/restore`, { method: 'POST' })
    await Promise.race([request, waitForServer()])
    await request
    toast.add({ severity: 'success', summary: 'Restored', detail: b.name, life: 4000 })
    window.location.reload()
  } catch (e) {
    fail(e)
  } finally {
    overlay.value = false
  }
}

onMounted(load)
</script>

<template>
  <h1>Backups</h1>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <section class="card row">
    <span class="spacer">
      Folder: <code>{{ list?.backup_dir }}</code>
      <template v-if="list?.last"><br /><span :class="list.last.ok ? 'muted' : 'error'">Last backup {{ new Date(String(list.last.at)).toLocaleString() }} — {{ list.last.ok ? 'OK' : `failed: ${list.last.error}` }}</span></template>
    </span>
    <button class="p2l-btn primary" :disabled="busy" @click="backupNow">Back up now</button>
    <label class="p2l-btn">Upload backup… <input type="file" accept=".gz" hidden @change="upload" /></label>
  </section>
  <section class="card">
    <p v-if="!list?.backups.length" class="muted">No backups yet. A backup runs every night (see Settings).</p>
    <table v-else class="plain">
      <thead><tr><th>File</th><th>Size</th><th>Created</th><th /></tr></thead>
      <tbody>
        <tr v-for="b in list.backups" :key="b.name">
          <td>{{ b.name }}</td>
          <td>{{ size(b.size) }}</td>
          <td>{{ new Date(b.created_at).toLocaleString() }}</td>
          <td class="row">
            <a class="p2l-btn" :href="`/api/v1/backups/${b.name}`" download>Download</a>
            <button class="p2l-btn danger" @click="restoring = b; confirmText = ''">Restore</button>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
  <AppModal :open="!!restoring" title="Restore backup" @close="restoring = null">
    <div class="stack">
      <p>This replaces <b>all</b> current data with <code>{{ restoring?.name }}</code>. Type <b>RESTORE</b> to confirm.</p>
      <input v-model="confirmText" class="p2l-input" data-test="restore-confirm" />
      <button class="p2l-btn danger" :disabled="confirmText !== 'RESTORE'" @click="restore">Restore now</button>
    </div>
  </AppModal>
  <div v-if="overlay" class="restoring" role="alert">Restoring… the app will reload when it's done.</div>
</template>

<style scoped>
.restoring { position: fixed; inset: 0; display: grid; place-items: center; background: rgba(0, 0, 0, .7); color: #fff; font-size: 1.3rem; z-index: 100; }
</style>
