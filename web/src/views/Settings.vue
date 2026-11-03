<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { onMounted, reactive, ref } from 'vue'

import { ApiError, apiFetch } from '@/api/client'
import type { BackupList } from '@/api/types'
import { useSettings } from '@/stores/settings'

const toast = useToast()
const store = useSettings()
const values = reactive<Record<string, unknown>>({})
const original = ref<Record<string, unknown>>({})
const errors = ref<Record<string, string>>({})
const backupDir = ref('')
const pw = reactive({ current: '', next: '', confirm: '' })
const pwError = ref('')
const test = reactive({ times: [] as number[], text: '', result: '' })

async function load() {
  const all = await apiFetch<Record<string, unknown>>('/settings')
  Object.assign(values, all)
  original.value = { ...all }
  backupDir.value = (await apiFetch<BackupList>('/backups').catch(() => ({ backup_dir: '' }) as BackupList)).backup_dir
}

async function save() {
  errors.value = {}
  const changed = Object.fromEntries(Object.entries(values).filter(([k, v]) => v !== original.value[k] && k !== 'setup.completed'))
  if (!Object.keys(changed).length) return
  try {
    await store.save(changed)
    original.value = { ...values }
    toast.add({ severity: 'success', summary: 'Settings saved', life: 2500 })
  } catch (e) {
    if (e instanceof ApiError) {
      errors.value = Object.keys(e.fields).length ? e.fields : { _: e.message }
    }
  }
}

async function changePassword() {
  pwError.value = ''
  if (pw.next !== pw.confirm) {
    pwError.value = "Passwords don't match"
    return
  }
  try {
    await apiFetch('/auth/password', { method: 'POST', json: { current: pw.current || null, new: pw.next } })
    Object.assign(pw, { current: '', next: '', confirm: '' })
    toast.add({ severity: 'success', summary: 'Password changed', life: 2500 })
  } catch (e) {
    pwError.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
  }
}

function testKey(ev: KeyboardEvent) {
  if (ev.key === 'Enter') {
    ev.preventDefault()
    const gaps = test.times.slice(1).map((t, i) => t - test.times[i])
    const max = gaps.length ? Math.max(...gaps) : 0
    const fast = test.text.length >= Number(values['scanner.min_length'] ?? 4) && max <= Number(values['scanner.max_gap_ms'] ?? 30)
    test.result = `Got "${test.text}" — ${test.text.length} characters, max gap ${max} ms — ${fast ? 'looks like a scanner' : 'looks like typing (raise the max gap if this was the scanner)'}`
    test.times = []
    test.text = ''
    return
  }
  if (ev.key.length === 1) {
    test.times.push(Date.now())
    test.text += ev.key
  }
}

onMounted(load)
</script>

<template>
  <h1>Settings</h1>
  <p v-if="errors._" class="error" role="alert">{{ errors._ }}</p>
  <div class="grid-2">
    <section class="card stack">
      <h2>Login</h2>
      <div class="field">
        <label>Login</label>
        <select v-model="values['auth.mode']" class="p2l-input" data-test="auth.mode">
          <option value="password">Password required</option>
          <option value="none">No login (trusted home network)</option>
        </select>
        <span v-if="errors['auth.mode']" class="error">{{ errors['auth.mode'] }}</span>
      </div>
      <form class="stack" @submit.prevent="changePassword">
        <input v-model="pw.current" class="p2l-input" type="password" placeholder="Current password" autocomplete="current-password" />
        <input v-model="pw.next" class="p2l-input" type="password" placeholder="New password (8+ characters)" autocomplete="new-password" />
        <input v-model="pw.confirm" class="p2l-input" type="password" placeholder="Confirm new password" autocomplete="new-password" />
        <p v-if="pwError" class="error">{{ pwError }}</p>
        <button class="p2l-btn" :disabled="pw.next.length < 8">Change password</button>
      </form>
    </section>
    <section class="card stack">
      <h2>Barcode scanner</h2>
      <div class="grid-2">
        <div class="field"><label>Minimum length</label><input v-model.number="values['scanner.min_length']" class="p2l-input" type="number" min="1" /><span v-if="errors['scanner.min_length']" class="error">{{ errors['scanner.min_length'] }}</span></div>
        <div class="field"><label>Max gap between keys (ms)</label><input v-model.number="values['scanner.max_gap_ms']" class="p2l-input" type="number" min="1" /><span v-if="errors['scanner.max_gap_ms']" class="error">{{ errors['scanner.max_gap_ms'] }}</span></div>
        <div class="field"><label>Prefix</label><input v-model="values['scanner.prefix']" class="p2l-input" /></div>
        <div class="field"><label>Suffix</label><input v-model="values['scanner.suffix']" class="p2l-input" /></div>
      </div>
      <label class="row"><input v-model="values['scanner.intercept_inputs']" type="checkbox" /> Catch scans even while typing in other fields</label>
      <div class="field">
        <label>Test your scanner: click here and scan something</label>
        <input class="p2l-input" data-scan-ignore data-test="scanner-test" placeholder="Scan here" @keydown="testKey" />
        <span class="muted" data-test="scanner-result">{{ test.result }}</span>
      </div>
    </section>
    <section class="card stack">
      <h2>Backups &amp; trash</h2>
      <div class="field">
        <label>Nightly backup time (24-hour)</label>
        <input v-model="values['backup.schedule']" class="p2l-input" placeholder="03:00" data-test="backup.schedule" />
        <span v-if="errors['backup.schedule']" class="error">{{ errors['backup.schedule'] }}</span>
      </div>
      <div class="field"><label>Backups to keep</label><input v-model.number="values['backup.keep']" class="p2l-input" type="number" min="1" /><span v-if="errors['backup.keep']" class="error">{{ errors['backup.keep'] }}</span></div>
      <div class="field"><label>Backup folder</label><code>{{ backupDir || '—' }}</code><span class="muted">Set by P2L_BACKUP_DIR / the Docker volume.</span></div>
      <div class="field"><label>Keep deleted things in the trash for (days)</label><input v-model.number="values['trash.retention_days']" class="p2l-input" type="number" min="1" /></div>
    </section>
    <section class="card stack">
      <h2>Display</h2>
      <div class="field">
        <label>Theme</label>
        <select v-model="values['display.theme']" class="p2l-input">
          <option value="system">Follow the device</option><option value="light">Light</option><option value="dark">Dark</option>
        </select>
      </div>
    </section>
  </div>
  <div class="row"><span class="spacer" /><button class="p2l-btn primary" data-test="save-settings" @click="save">Save settings</button></div>
</template>
