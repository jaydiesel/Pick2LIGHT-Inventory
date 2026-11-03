<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError, apiFetch } from '@/api/client'
import type { LocationNode, LocationOut, LocationTypeOut, SearchHit, SearchPage, SheetSpec } from '@/api/types'
import { printLabels } from '@/lib/labels'

const props = defineProps<{ id: string }>()
const router = useRouter()
const toast = useToast()
const loc = ref<LocationOut | null>(null)
const contents = ref<SearchHit[]>([])
const types = ref<LocationTypeOut[]>([])
const sheets = ref<SheetSpec[]>([])
const error = ref('')
const editing = ref(false)
const form = reactive({ name: '', code: '', location_type_id: '' as string, notes: '' })
const sheet = reactive({ id: '', start: 0 })

async function load() {
  error.value = ''
  loc.value = await apiFetch<LocationOut>(`/locations/${props.id}`)
  Object.assign(form, {
    name: loc.value.name, code: loc.value.code, notes: loc.value.notes ?? '',
    location_type_id: loc.value.location_type_id ? String(loc.value.location_type_id) : '',
  })
  const page = await apiFetch<SearchPage>('/search', { method: 'POST', json: { location_id: Number(props.id), limit: 200 } })
  contents.value = page.hits
  types.value = await apiFetch<LocationTypeOut[]>('/location-types')
  sheets.value = await apiFetch<SheetSpec[]>('/label-sheets').catch(() => [])
}

function fail(e: unknown) {
  error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
}

async function save() {
  try {
    await apiFetch(`/locations/${props.id}`, {
      method: 'PATCH',
      json: {
        name: form.name.trim(), code: form.code.trim(), notes: form.notes || null,
        location_type_id: form.location_type_id ? Number(form.location_type_id) : null,
      },
    })
    editing.value = false
    await load()
  } catch (e) {
    fail(e)
  }
}

async function remove() {
  if (!window.confirm(`Delete "${loc.value?.name}"? It goes to the trash.`)) return
  try {
    await apiFetch(`/locations/${props.id}`, { method: 'DELETE' })
    router.push('/locations')
  } catch (e) {
    fail(e)
  }
}

async function print() {
  try {
    await printLabels('location', [Number(props.id)])
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Print failed', detail: e instanceof Error ? e.message : String(e) })
  }
}

function descendants(nodes: LocationNode[], id: number): number[] {
  for (const n of nodes) {
    if (n.id === id) {
      const ids: number[] = []
      const walk = (kids: LocationNode[]) => kids.forEach((k) => (ids.push(k.id), walk(k.children ?? [])))
      walk(n.children ?? [])
      return ids
    }
    const found = descendants(n.children ?? [], id)
    if (found.length) return found
  }
  return []
}

async function printChildren() {
  const ids = descendants(await apiFetch<LocationNode[]>('/locations/tree'), Number(props.id))
  if (!ids.length) {
    toast.add({ severity: 'info', summary: 'No locations inside this one', life: 3000 })
    return
  }
  try {
    await printLabels('location', ids, { sheetId: sheet.id || null, startPosition: sheet.start })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Print failed', detail: e instanceof Error ? e.message : String(e) })
  }
}

watch(() => props.id, load)
onMounted(load)
</script>

<template>
  <div v-if="loc">
    <p class="muted" data-test="breadcrumb">{{ loc.path.map((p) => p.name).join(' › ') }}</p>
    <h1>{{ loc.name }} <span class="muted">{{ loc.code }}</span></h1>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <section class="card stack">
      <template v-if="!editing">
        <div class="row">
          <span v-if="loc.type_name" class="badge">{{ loc.type_name }}</span>
          <span v-if="loc.notes">{{ loc.notes }}</span>
          <span class="spacer" />
          <button class="p2l-btn" @click="editing = true">Edit</button>
          <button class="p2l-btn" @click="print"><i class="pi pi-print" /> Print label</button>
          <button class="p2l-btn danger" data-test="delete-location" @click="remove">Delete</button>
        </div>
      </template>
      <form v-else class="stack" @submit.prevent="save">
        <div class="grid-2">
          <div class="field"><label>Name</label><input v-model="form.name" class="p2l-input" /></div>
          <div class="field"><label>Code</label><input v-model="form.code" class="p2l-input" /></div>
          <div class="field">
            <label>Type</label>
            <select v-model="form.location_type_id" class="p2l-input">
              <option value="">—</option>
              <option v-for="t in types" :key="t.id" :value="String(t.id)">{{ t.name }}</option>
            </select>
          </div>
          <div class="field"><label>Notes</label><input v-model="form.notes" class="p2l-input" /></div>
        </div>
        <div class="row"><span class="spacer" /><button class="p2l-btn" type="button" @click="editing = false">Cancel</button><button class="p2l-btn primary">Save</button></div>
      </form>
    </section>
    <section class="card">
      <h2>Contents</h2>
      <p v-if="!contents.length" class="muted">Nothing stored here.</p>
      <table v-else class="plain">
        <thead><tr><th>Item</th><th>SKU</th><th>Category</th><th>On hand</th></tr></thead>
        <tbody>
          <tr v-for="h in contents" :key="h.id">
            <td><RouterLink :to="h.matched_unit_id ? `/units/${h.matched_unit_id}` : `/items/${h.id}`">{{ h.name }}</RouterLink></td>
            <td>{{ h.sku }}</td>
            <td>{{ h.category_name }}</td>
            <td>{{ h.on_hand }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    <section class="card row">
      <h2 class="spacer">Labels for the locations inside</h2>
      <select v-model="sheet.id" class="p2l-input">
        <option value="">One label per page (label printer)</option>
        <option v-for="s in sheets" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <label v-if="sheet.id" class="row">Skip <input v-model.number="sheet.start" class="p2l-input" type="number" min="0" style="width: 5rem" /> used labels</label>
      <button class="p2l-btn" @click="printChildren"><i class="pi pi-print" /> Print</button>
    </section>
  </div>
</template>
