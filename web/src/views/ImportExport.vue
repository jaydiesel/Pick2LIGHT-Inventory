<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { ApiError, apiFetch } from '@/api/client'
import type { CategoryOut, FieldDefOut, ImportPreview } from '@/api/types'
import CsvMapping from '@/components/CsvMapping.vue'
import LocationPicker from '@/components/LocationPicker.vue'
import { csvHeaders } from '@/lib/csvMapping'

const EXPORTS = [
  ['items', 'Items'],
  ['units', 'Units'],
  ['locations', 'Locations'],
  ['stock', 'Stock'],
  ['log_entries', 'History log'],
]
const categories = ref<CategoryOut[]>([])
const specs = ref<FieldDefOut[]>([])
const file = ref<File | null>(null)
const headers = ref<string[]>([])
const mapping = ref<Record<string, string>>({})
const opts = reactive({ category_id: null as number | null, update_existing: false, skip_invalid: false, default_location_id: null as number | null })
const preview = ref<ImportPreview | null>(null)
const result = ref<ImportPreview | null>(null)
const error = ref('')
const busy = ref(false)
const picking = ref(false)
const locationLabel = ref('')

const errorRows = computed(() => preview.value?.counts.errors ?? 0)

watch(
  () => opts.category_id,
  async (id) => {
    specs.value = id ? await apiFetch<FieldDefOut[]>(`/categories/${id}/fields`) : []
    preview.value = null
  },
)

async function chooseFile(ev: Event) {
  const f = (ev.target as HTMLInputElement).files?.[0] ?? null
  file.value = f
  preview.value = null
  result.value = null
  headers.value = f ? csvHeaders(await f.text()) : []
  mapping.value = {}
}

function body(): FormData {
  const fd = new FormData()
  fd.append('file', file.value as File)
  fd.append('options', JSON.stringify({ ...opts, mapping: mapping.value }))
  return fd
}

function fail(e: unknown) {
  error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
}

async function runPreview() {
  error.value = ''
  busy.value = true
  try {
    preview.value = await apiFetch<ImportPreview>('/import/csv/preview', { method: 'POST', body: body() })
  } catch (e) {
    fail(e)
  } finally {
    busy.value = false
  }
}

async function apply() {
  error.value = ''
  busy.value = true
  try {
    result.value = await apiFetch<ImportPreview>('/import/csv/apply', { method: 'POST', body: body() })
    preview.value = null
  } catch (e) {
    fail(e)
  } finally {
    busy.value = false
  }
}

async function chooseLocation(id: number) {
  picking.value = false
  opts.default_location_id = id
  locationLabel.value = (await apiFetch<{ path: { name: string }[] }>(`/locations/${id}`)).path.map((p) => p.name).join(' › ')
}

onMounted(async () => {
  categories.value = await apiFetch<CategoryOut[]>('/categories')
})
</script>

<template>
  <h1>Import &amp; export</h1>
  <section class="card stack">
    <h2>Export</h2>
    <div class="row">
      <a v-for="[e, label] in EXPORTS" :key="e" class="p2l-btn" :href="`/api/v1/export/${e}.csv`" download>{{ label }} (CSV)</a>
      <a class="p2l-btn" href="/api/v1/export/full.json" download>Everything (JSON)</a>
    </div>
  </section>
  <section class="card stack">
    <h2>Import a spreadsheet (CSV)</h2>
    <p class="muted">Export your spreadsheet as CSV (comma or semicolon). Each row becomes an item — or a unit for per-unit categories.</p>
    <div class="grid-2">
      <div class="field">
        <label>Category for the rows</label>
        <select v-model="opts.category_id" class="p2l-input" data-test="import-category">
          <option :value="null" disabled>Choose…</option>
          <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.path.map((p) => p.name).join(' › ') }}</option>
        </select>
      </div>
      <div class="field"><label>File</label><input type="file" accept=".csv,text/csv" data-test="import-file" @change="chooseFile" /></div>
    </div>
    <template v-if="headers.length && opts.category_id">
      <CsvMapping v-model="mapping" :headers="headers" :specs="specs" />
      <div class="row">
        <label class="row"><input v-model="opts.update_existing" type="checkbox" /> Update existing items</label>
        <label class="row"><input v-model="opts.skip_invalid" type="checkbox" data-test="skip-invalid" /> Skip rows with errors</label>
        <button class="p2l-btn" type="button" @click="picking = true">Default location: {{ locationLabel || 'none' }}</button>
      </div>
      <div class="row"><span class="spacer" /><button class="p2l-btn" :disabled="busy" data-test="preview-import" @click="runPreview">Preview</button></div>
    </template>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </section>
  <section v-if="preview" class="card stack">
    <h2>Preview</h2>
    <p>
      <span v-for="(n, k) in preview.counts" :key="k" :class="['badge', { danger: k === 'errors' && n > 0 }]" style="margin-right: .4rem">{{ k }}: {{ n }}</span>
    </p>
    <table class="plain" data-test="preview-table">
      <thead><tr><th>Row</th><th>Action</th><th>Values</th><th>Problems</th></tr></thead>
      <tbody>
        <tr v-for="r in preview.rows" :key="r.row" :class="{ bad: Object.keys(r.errors).length }">
          <td>{{ r.row }}</td>
          <td>{{ Object.keys(r.errors).length ? '—' : r.action.replace('_', ' ') }}</td>
          <td class="muted">{{ Object.values(r.values).join(' · ') }}</td>
          <td class="error">{{ Object.entries(r.errors).map(([k, v]) => `${k}: ${v}`).join('; ') }}</td>
        </tr>
      </tbody>
    </table>
    <div class="row">
      <span v-if="errorRows && !opts.skip_invalid" class="error">Tick "Skip rows with errors" or fix the file to import.</span>
      <span class="spacer" />
      <button class="p2l-btn primary" :disabled="busy || (errorRows > 0 && !opts.skip_invalid)" data-test="apply-import" @click="apply">Import</button>
    </div>
  </section>
  <section v-if="result" class="card">
    <h2>Imported</h2>
    <p><span v-for="(n, k) in result.counts" :key="k" class="badge" style="margin-right: .4rem">{{ k }}: {{ n }}</span></p>
  </section>
  <LocationPicker :open="picking" @select="chooseLocation" @close="picking = false" />
</template>

<style scoped>
tr.bad td { background: color-mix(in srgb, var(--p2l-danger) 8%, transparent); }
</style>
