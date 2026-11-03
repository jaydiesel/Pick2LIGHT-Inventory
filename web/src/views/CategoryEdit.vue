<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError, apiBlob, apiFetch } from '@/api/client'
import type { CategoryOut, FieldDefOut, LogEntryTypeOut } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import FieldDefEditor, { type FieldDraft } from '@/components/FieldDefEditor.vue'
import LogTypeEditor from '@/components/LogTypeEditor.vue'
import { downloadBlob } from '@/lib/keys'

const props = defineProps<{ id: string }>()
const router = useRouter()
const toast = useToast()

const category = ref<CategoryOut | null>(null)
const all = ref<CategoryOut[]>([])
const fields = ref<FieldDefOut[]>([])
const logTypes = ref<LogEntryTypeOut[]>([])
const error = ref('')
const fieldEditor = ref<FieldDefOut | 'new' | null>(null)
const logEditor = ref<LogEntryTypeOut | 'new' | null>(null)
const examples = reactive<Record<string, string>>({})
const form = reactive({
  name: '', parent_id: '' as string, icon: '', description: '', tracking_mode: '' as string,
  sku_prefix: '', sku_pattern: '', unit_id_pattern: '',
})

const names = computed(() => Object.fromEntries(all.value.map((c) => [c.id, c.name])))
const parentChoices = computed(() => all.value.filter((c) => !c.path.some((p) => p.id === Number(props.id))))
const mode = computed(() => category.value?.effective_tracking_mode ?? 'bulk')

function fill(c: CategoryOut) {
  Object.assign(form, {
    name: c.name, parent_id: c.parent_id ? String(c.parent_id) : '', icon: c.icon ?? '', description: c.description ?? '',
    tracking_mode: c.tracking_mode ?? '', sku_prefix: c.sku_prefix ?? '', sku_pattern: c.sku_pattern ?? '',
    unit_id_pattern: c.unit_id_pattern ?? '',
  })
}

async function load() {
  error.value = ''
  const id = props.id
  const [c, cats, f, lt] = await Promise.all([
    apiFetch<CategoryOut>(`/categories/${id}`),
    apiFetch<CategoryOut[]>('/categories'),
    apiFetch<FieldDefOut[]>(`/categories/${id}/fields`),
    apiFetch<LogEntryTypeOut[]>(`/categories/${id}/log-types`),
  ])
  category.value = c
  all.value = cats
  fields.value = f
  logTypes.value = lt
  fill(c)
}

function fail(e: unknown) {
  error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
  toast.add({ severity: 'error', summary: 'Not saved', detail: error.value, life: 6000 })
}

async function saveCategory() {
  error.value = ''
  const nul = (v: string) => (v.trim() === '' ? null : v.trim())
  try {
    category.value = await apiFetch<CategoryOut>(`/categories/${props.id}`, {
      method: 'PATCH',
      json: {
        name: form.name.trim(), parent_id: form.parent_id ? Number(form.parent_id) : null, icon: nul(form.icon),
        description: nul(form.description), tracking_mode: nul(form.tracking_mode), sku_prefix: nul(form.sku_prefix),
        sku_pattern: nul(form.sku_pattern), unit_id_pattern: nul(form.unit_id_pattern),
      },
    })
    toast.add({ severity: 'success', summary: 'Saved', life: 2500 })
    await load()
  } catch (e) {
    fail(e)
  }
}

async function saveField(draft: FieldDraft) {
  try {
    if (fieldEditor.value === 'new') {
      await apiFetch(`/categories/${props.id}/fields`, { method: 'POST', json: draft })
    } else if (fieldEditor.value) {
      const { key: _key, ...patch } = draft
      void _key
      await apiFetch(`/fields/${fieldEditor.value.id}`, { method: 'PATCH', json: patch })
    }
    fieldEditor.value = null
    await load()
  } catch (e) {
    fail(e)
  }
}

async function removeField(f: FieldDefOut) {
  if (!window.confirm(`Remove the field "${f.label}"? Stored values are kept but hidden.`)) return
  await apiFetch(`/fields/${f.id}`, { method: 'DELETE' }).catch(fail)
  await load()
}

async function moveField(f: FieldDefOut, delta: number) {
  const own = fields.value.filter((x) => x.inherited_from === null)
  const i = own.findIndex((x) => x.id === f.id)
  const j = i + delta
  if (j < 0 || j >= own.length) return
  ;[own[i], own[j]] = [own[j], own[i]]
  await Promise.all(own.map((x, order) => apiFetch(`/fields/${x.id}`, { method: 'PATCH', json: { order } })))
  await load()
}

async function saveLogType(payload: Record<string, unknown>) {
  try {
    if (logEditor.value === 'new') await apiFetch(`/categories/${props.id}/log-types`, { method: 'POST', json: payload })
    else if (logEditor.value) await apiFetch(`/log-types/${logEditor.value.id}`, { method: 'PATCH', json: payload })
    logEditor.value = null
    await load()
  } catch (e) {
    fail(e)
  }
}

async function removeLogType(t: LogEntryTypeOut) {
  if (!window.confirm(`Delete the log type "${t.name}"? It goes to the trash.`)) return
  await apiFetch(`/log-types/${t.id}`, { method: 'DELETE' }).catch(fail)
  await load()
}

async function deleteCategory() {
  if (!window.confirm(`Delete the category "${category.value?.name}"?`)) return
  try {
    await apiFetch(`/categories/${props.id}`, { method: 'DELETE' })
    router.push('/categories')
  } catch (e) {
    fail(e)
  }
}

async function exportPack() {
  downloadBlob(await apiBlob(`/categories/${props.id}/export-pack`), `${category.value?.name ?? 'pack'}.json`)
}

const tokenRe = /\{([a-z_][a-z0-9_]*)(?::(\d+))?(?:\|(upper|lower|si))?\}/g
function preview(pattern: string, fallback: string): string {
  const p = pattern.trim() || fallback
  const prefix = (form.sku_prefix || category.value?.name.slice(0, 4) || 'ITEM').toUpperCase()
  return p.replace(tokenRe, (_m, name: string, width?: string) => {
    if (name === 'prefix') return prefix
    if (name === 'seq') return '1'.padStart(Number(width || 1), '0')
    if (name === 'sku') return 'SKU'
    return examples[name] || `<${name}>`
  })
}

watch(() => props.id, load)
onMounted(load)
</script>

<template>
  <div v-if="category">
    <p class="muted"><RouterLink to="/categories">Categories</RouterLink> › {{ category.path.map((p) => p.name).join(' › ') }}</p>
    <h1>{{ category.name }}</h1>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <section class="card stack">
      <div class="grid-2">
        <div class="field"><label>Name</label><input v-model="form.name" class="p2l-input" data-test="name" /></div>
        <div class="field">
          <label>Parent</label>
          <select v-model="form.parent_id" class="p2l-input" data-test="parent">
            <option value="">— top level —</option>
            <option v-for="c in parentChoices" :key="c.id" :value="String(c.id)">{{ c.path.map((p) => p.name).join(' › ') }}</option>
          </select>
        </div>
        <div class="field">
          <label>Stock tracking</label>
          <select v-model="form.tracking_mode" class="p2l-input" data-test="tracking-mode">
            <option value="">Inherit ({{ mode === 'unit' ? 'per unit' : 'bulk' }})</option>
            <option value="bulk">Bulk — count a quantity</option>
            <option value="unit">Per unit — each one has its own label</option>
          </select>
        </div>
        <div class="field"><label>SKU prefix</label><input v-model="form.sku_prefix" class="p2l-input" /></div>
        <div class="field">
          <label>SKU pattern</label>
          <input v-model="form.sku_pattern" class="p2l-input" placeholder="{prefix}-{seq:4}" />
          <span class="muted">Preview: <code>{{ preview(form.sku_pattern, '{prefix}-{seq:4}') }}</code></span>
        </div>
        <div v-if="mode === 'unit'" class="field">
          <label>Unit code pattern</label>
          <input v-model="form.unit_id_pattern" class="p2l-input" placeholder="{prefix}{seq:4}" />
          <span class="muted">Preview: <code>{{ preview(form.unit_id_pattern, '{prefix}{seq:4}') }}</code></span>
        </div>
      </div>
      <div class="field"><label>Description</label><input v-model="form.description" class="p2l-input" /></div>
      <div class="row">
        <button class="p2l-btn danger" @click="deleteCategory">Delete</button>
        <button class="p2l-btn" @click="exportPack">Export pack</button>
        <span class="spacer" />
        <button class="p2l-btn primary" data-test="save-category" @click="saveCategory">Save</button>
      </div>
    </section>

    <section class="card">
      <div class="row"><h2>Fields</h2><span class="spacer" /><button class="p2l-btn" data-test="add-field" @click="fieldEditor = 'new'">Add field</button></div>
      <table class="plain">
        <thead><tr><th>Field</th><th>Type</th><th>Example (for preview)</th><th /></tr></thead>
        <tbody>
          <tr v-for="f in fields" :key="f.id" :data-test="`field-${f.key}`">
            <td>
              {{ f.label }} <span class="muted">{{ f.key }}</span>
              <span v-if="f.scope === 'unit'" class="badge">per unit</span>
              <span v-if="f.inherited_from" class="badge">from {{ names[f.inherited_from] ?? 'parent' }}</span>
            </td>
            <td>{{ f.type }}<template v-if="f.number_unit"> ({{ f.number_unit }})</template></td>
            <td><input v-model="examples[f.key]" class="p2l-input" /></td>
            <td class="row">
              <template v-if="!f.inherited_from">
                <button class="p2l-btn" aria-label="Move up" @click="moveField(f, -1)"><i class="pi pi-arrow-up" /></button>
                <button class="p2l-btn" aria-label="Move down" @click="moveField(f, 1)"><i class="pi pi-arrow-down" /></button>
                <button class="p2l-btn" data-test="edit-field" @click="fieldEditor = f">Edit</button>
                <button class="p2l-btn danger" @click="removeField(f)">Remove</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="card">
      <div class="row"><h2>History log types</h2><span class="spacer" /><button class="p2l-btn" @click="logEditor = 'new'">Add log type</button></div>
      <p v-if="!logTypes.length" class="muted">E.g. "Capacity Test" for battery cells or "Health Check" for drives.</p>
      <table v-else class="plain">
        <tbody>
          <tr v-for="t in logTypes" :key="t.id">
            <td>{{ t.name }} <span class="muted">{{ t.key }}</span> <span v-if="t.inherited_from" class="badge">from {{ names[t.inherited_from] }}</span></td>
            <td>{{ t.fields.length }} fields</td>
            <td class="row">
              <template v-if="!t.inherited_from">
                <button class="p2l-btn" @click="logEditor = t">Edit</button>
                <button class="p2l-btn danger" @click="removeLogType(t)">Delete</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <AppModal :open="fieldEditor !== null" :title="fieldEditor === 'new' ? 'New field' : 'Edit field'" wide @close="fieldEditor = null">
      <FieldDefEditor
        v-if="fieldEditor !== null"
        :tracking-mode="mode"
        :initial="fieldEditor === 'new' ? null : (fieldEditor as unknown as FieldDraft)"
        @save="saveField"
        @cancel="fieldEditor = null"
      />
    </AppModal>
    <AppModal :open="logEditor !== null" :title="logEditor === 'new' ? 'New log type' : 'Edit log type'" wide @close="logEditor = null">
      <LogTypeEditor
        v-if="logEditor !== null"
        :tracking-mode="mode"
        :initial="logEditor === 'new' ? null : logEditor"
        @save="saveLogType"
        @cancel="logEditor = null"
      />
    </AppModal>
  </div>
</template>
