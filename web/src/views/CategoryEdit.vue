<script setup lang="ts">
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable, { type DataTableRowReorderEvent } from 'primevue/datatable'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import Tag from 'primevue/tag'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiFetch } from '../api/client'
import type { components } from '../api/schema'
import CategoryTree from '../components/CategoryTree.vue'
import FieldDefEditor from '../components/FieldDefEditor.vue'
import LogTypeEditor from '../components/LogTypeEditor.vue'
import { useApiToast } from '../composables/useApiToast'
import { DEFAULT_SKU_PATTERN, DEFAULT_UNIT_PATTERN, renderPreview } from '../lib/patterns'

type CategoryOut = components['schemas']['CategoryOut']
type FieldDefOut = components['schemas']['FieldDefOut']
type LogEntryTypeOut = components['schemas']['LogEntryTypeOut']

const route = useRoute()
const router = useRouter()
const notify = useApiToast()

const id = computed(() => Number(route.params.id))
const categories = ref<CategoryOut[]>([])
const category = ref<CategoryOut | null>(null)
const fields = ref<FieldDefOut[]>([])
const logTypes = ref<LogEntryTypeOut[]>([])
const loading = ref(true)

const form = reactive({ name: '', icon: '', description: '', sku_prefix: '', sku_pattern: '', unit_id_pattern: '' })
const trackingMode = ref<'inherit' | 'bulk' | 'unit'>('inherit')
const pickingParent = ref(false)
const examples = reactive<Record<string, string>>({})

const TRACKING = [
  { value: 'inherit', label: 'Inherit' },
  { value: 'bulk', label: 'Bulk (quantity)' },
  { value: 'unit', label: 'Per unit' },
]

function syncForm(c: CategoryOut) {
  Object.assign(form, {
    name: c.name,
    icon: c.icon ?? '',
    description: c.description ?? '',
    sku_prefix: c.sku_prefix ?? '',
    sku_pattern: c.sku_pattern ?? '',
    unit_id_pattern: c.unit_id_pattern ?? '',
  })
  trackingMode.value = c.tracking_mode ?? 'inherit'
}

async function load() {
  loading.value = true
  try {
    const [all, cat, fs, lts] = await Promise.all([
      apiFetch<CategoryOut[]>('/categories'),
      apiFetch<CategoryOut>(`/categories/${id.value}`),
      apiFetch<FieldDefOut[]>(`/categories/${id.value}/fields`),
      apiFetch<LogEntryTypeOut[]>(`/categories/${id.value}/log-types`),
    ])
    categories.value = all
    category.value = cat
    fields.value = [...fs].sort((a, b) => a.order - b.order)
    logTypes.value = lts
    syncForm(cat)
  } catch (e) {
    notify.error(e, 'Could not load the category')
  } finally {
    loading.value = false
  }
}
watch(id, load, { immediate: true })

const byId = computed(() => new Map(categories.value.map((c) => [c.id, c])))
const parentName = computed(() => {
  const pid = category.value?.parent_id
  return pid == null ? 'Top level' : (byId.value.get(pid)?.name ?? `#${pid}`)
})
const isUnit = computed(() => category.value?.effective_tracking_mode === 'unit')
const inheritedFields = computed(() => fields.value.filter((f) => f.inherited_from != null))
const ownFields = computed(() => fields.value.filter((f) => f.inherited_from == null))
const sourceName = (f: FieldDefOut) => byId.value.get(f.inherited_from!)?.name ?? `#${f.inherited_from}`

/** PATCH only the given keys, then reload. Returns false (after a toast) when the server refuses. */
async function patchCategory(body: Record<string, unknown>): Promise<boolean> {
  try {
    await apiFetch(`/categories/${id.value}`, { method: 'PATCH', json: body })
    await load()
    return true
  } catch (e) {
    notify.error(e)
    return false
  }
}

async function chooseParent(parentId: number | null) {
  pickingParent.value = false
  if (parentId === (category.value?.parent_id ?? null)) return
  await patchCategory({ parent_id: parentId })
}

async function onTracking(value: 'inherit' | 'bulk' | 'unit') {
  const ok = await patchCategory({ tracking_mode: value === 'inherit' ? null : value })
  // The server refuses (409) when items exist; show its message and put the select back.
  if (!ok && category.value) trackingMode.value = category.value.tracking_mode ?? 'inherit'
}

const orNull = (s: string) => (s.trim() === '' ? null : s.trim())
const textKeys = ['name', 'icon', 'description', 'sku_prefix', 'sku_pattern', 'unit_id_pattern'] as const
const changes = computed(() => {
  const c = category.value
  const out: Record<string, unknown> = {}
  if (!c) return out
  for (const k of textKeys) {
    const next = k === 'name' ? form.name.trim() : orNull(form[k])
    if (next !== (c[k] ?? null)) out[k] = next
  }
  return out
})
const canSave = computed(() => Object.keys(changes.value).length > 0 && form.name.trim() !== '')

async function saveDetails() {
  if (!canSave.value) return
  if (await patchCategory(changes.value)) notify.success('Category saved')
}

// ---- live preview (client-side approximation) ----
const chain = computed(() => {
  const out: CategoryOut[] = []
  let c = category.value ? byId.value.get(category.value.id) : undefined
  while (c && out.length < 32) {
    out.push(c)
    c = c.parent_id == null ? undefined : byId.value.get(c.parent_id)
  }
  return out
})
const ancestors = computed(() => chain.value.slice(1))
const inheritedPattern = (key: 'sku_pattern' | 'unit_id_pattern') => ancestors.value.find((c) => c[key])?.[key] ?? null
const previewPrefix = computed(() => {
  const own = form.sku_prefix.trim() || ancestors.value.find((c) => c.sku_prefix)?.sku_prefix
  return own || form.name.replace(/[^A-Za-z]/g, '').slice(0, 4).toUpperCase()
})
const skuPatternUsed = computed(() => form.sku_pattern.trim() || inheritedPattern('sku_pattern') || DEFAULT_SKU_PATTERN)
const unitPatternUsed = computed(() => form.unit_id_pattern.trim() || inheritedPattern('unit_id_pattern') || DEFAULT_UNIT_PATTERN)
const previewInput = computed(() => ({ prefix: previewPrefix.value, examples, fields: fields.value }))
const skuPreview = computed(() => renderPreview(skuPatternUsed.value, previewInput.value))
const unitPreview = computed(() => renderPreview(unitPatternUsed.value, { ...previewInput.value, sku: skuPreview.value }))

// ---- fields ----
const fieldDialog = ref(false)
const editingField = ref<FieldDefOut | null>(null)
const takenKeys = computed(() => fields.value.map((f) => f.key))

function openField(f: FieldDefOut | null) {
  editingField.value = f
  fieldDialog.value = true
}

async function saveField(body: Record<string, unknown>) {
  try {
    const f = editingField.value
    if (f) {
      if (Object.keys(body).length) await apiFetch(`/fields/${f.id}`, { method: 'PATCH', json: body })
    } else {
      const order = Math.max(-1, ...fields.value.map((x) => x.order)) + 1
      await apiFetch(`/categories/${id.value}/fields`, { method: 'POST', json: { scope: 'item', ...body, order } })
    }
    fieldDialog.value = false
    await load()
  } catch (e) {
    notify.error(e)
  }
}

async function deleteField(f: FieldDefOut) {
  if (!window.confirm(`Delete field "${f.label}"? Its values are removed from items.`)) return
  try {
    await apiFetch(`/fields/${f.id}`, { method: 'DELETE' })
    await load()
  } catch (e) {
    notify.error(e)
  }
}

/** Reuse the rows' existing order numbers in the new sequence, so own rows keep their place among inherited ones. */
function reorderPlan(rows: FieldDefOut[]): { id: number; order: number }[] {
  const slots = [...ownFields.value.map((f) => f.order)].sort((a, b) => a - b)
  const strict = slots.every((v, i) => i === 0 || v > slots[i - 1])
  const orders = strict ? slots : slots.map((_, i) => slots[0] + i)
  return rows.flatMap((row, i) => (row.order === orders[i] ? [] : [{ id: row.id, order: orders[i] }]))
}

async function onReorder(e: DataTableRowReorderEvent) {
  const moved = reorderPlan(e.value as FieldDefOut[])
  try {
    for (const m of moved) await apiFetch(`/fields/${m.id}`, { method: 'PATCH', json: { order: m.order } })
  } catch (err) {
    notify.error(err)
  }
  await load()
}

// ---- log types ----
const logDialog = ref(false)
const editingLog = ref<LogEntryTypeOut | null>(null)

function openLog(lt: LogEntryTypeOut | null) {
  editingLog.value = lt
  logDialog.value = true
}

async function saveLog(body: Record<string, unknown>) {
  try {
    const lt = editingLog.value
    if (lt) {
      if (Object.keys(body).length) await apiFetch(`/log-types/${lt.id}`, { method: 'PATCH', json: body })
    } else {
      await apiFetch(`/categories/${id.value}/log-types`, { method: 'POST', json: body })
    }
    logDialog.value = false
    await load()
  } catch (e) {
    notify.error(e)
  }
}

async function deleteLog(lt: LogEntryTypeOut) {
  if (!window.confirm(`Delete log entry type "${lt.name}"?`)) return
  try {
    await apiFetch(`/log-types/${lt.id}`, { method: 'DELETE' })
    await load()
  } catch (e) {
    notify.error(e)
  }
}

// ---- category-level actions ----
async function exportPack() {
  try {
    const pack = await apiFetch<unknown>(`/categories/${id.value}/export-pack`)
    const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${(category.value?.name ?? 'category').toLowerCase().replace(/[^a-z0-9]+/g, '-')}-pack.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    notify.error(e)
  }
}

async function deleteCategory() {
  if (!window.confirm(`Delete category "${category.value?.name}"?`)) return
  try {
    await apiFetch(`/categories/${id.value}`, { method: 'DELETE' })
    await router.push('/categories')
  } catch (e) {
    notify.error(e)
  }
}
</script>

<template>
  <div v-if="category" class="category-edit">
    <p><RouterLink to="/categories">&larr; All categories</RouterLink></p>
    <h1>{{ category.name }}</h1>

    <section class="card">
      <h2>Details</h2>
      <form class="grid" @submit.prevent="saveDetails">
        <label>Name <InputText v-model="form.name" data-test="name" /></label>
        <label>Icon (e.g. pi-bolt) <InputText v-model="form.icon" data-test="icon" /></label>
        <label class="wide">Description <InputText v-model="form.description" data-test="description" /></label>

        <div class="wide">
          <span class="label">Parent</span>
          <span data-test="parent-name">{{ parentName }}</span>
          <Button type="button" data-test="change-parent" label="Change" text size="small" @click="pickingParent = !pickingParent" />
          <div v-if="pickingParent" class="picker">
            <Button type="button" data-test="parent-root" label="Top level" text size="small" @click="chooseParent(null)" />
            <CategoryTree :categories="categories" :selected-id="category.parent_id" :disabled-ids="[category.id]" @select="chooseParent" />
          </div>
        </div>

        <label>Tracking mode
          <Select
            v-model="trackingMode"
            data-test="tracking"
            :options="TRACKING"
            option-label="label"
            option-value="value"
            title="Cannot be changed once items exist in this category."
            @update:model-value="onTracking"
          />
          <small class="muted">Effective: {{ category.effective_tracking_mode === 'unit' ? 'per unit' : 'bulk' }}. Locked by the server once items exist.</small>
        </label>
        <label>SKU prefix <InputText v-model="form.sku_prefix" data-test="sku-prefix" :placeholder="previewPrefix" /></label>
        <label class="wide">SKU pattern
          <InputText v-model="form.sku_pattern" data-test="sku-pattern" :placeholder="skuPatternUsed" />
          <small>Preview: <code data-test="sku-preview">{{ skuPreview || '(empty)' }}</code> <span class="muted">approximate, from the example column below</span></small>
        </label>
        <label v-if="isUnit" class="wide">Unit-code pattern
          <InputText v-model="form.unit_id_pattern" data-test="unit-pattern" :placeholder="unitPatternUsed" />
          <small>Preview: <code data-test="unit-preview">{{ unitPreview || '(empty)' }}</code></small>
        </label>
        <div class="wide actions">
          <Button type="submit" label="Save details" data-test="save-details" :disabled="!canSave" />
        </div>
      </form>
    </section>

    <section class="card">
      <h2>Fields</h2>
      <table v-if="inheritedFields.length" class="plain">
        <thead><tr><th>Label</th><th>Key</th><th>Type</th><th>Inherited</th><th>Example</th></tr></thead>
        <tbody>
          <tr v-for="f in inheritedFields" :key="f.id" :data-test="`inherited-field-${f.key}`">
            <td>{{ f.label }}</td>
            <td><code>{{ f.key }}</code></td>
            <td>{{ f.type }}</td>
            <td><Tag severity="secondary" :value="`from ${sourceName(f)}`" /></td>
            <td><InputText v-model="examples[f.key]" size="small" :aria-label="`Example for ${f.label}`" /></td>
          </tr>
        </tbody>
      </table>

      <DataTable :value="ownFields" data-key="id" reorderable-rows data-test="own-fields" @row-reorder="onReorder">
        <template #empty>No fields defined on this category.</template>
        <Column row-reorder style="width: 3rem" />
        <Column field="label" header="Label" />
        <Column field="key" header="Key"><template #body="{ data }"><code>{{ data.key }}</code></template></Column>
        <Column field="type" header="Type" />
        <Column v-if="isUnit" field="scope" header="Scope" />
        <Column header="Example">
          <template #body="{ data }"><InputText v-model="examples[data.key]" size="small" :aria-label="`Example for ${data.label}`" /></template>
        </Column>
        <Column header="">
          <template #body="{ data }">
            <Button :data-test="`edit-field-${data.key}`" icon="pi pi-pencil" text :aria-label="`Edit ${data.label}`" @click="openField(data)" />
            <Button icon="pi pi-trash" text severity="danger" :aria-label="`Delete ${data.label}`" @click="deleteField(data)" />
          </template>
        </Column>
      </DataTable>
      <Button data-test="add-field" label="Add field" icon="pi pi-plus" text @click="openField(null)" />
    </section>

    <section class="card">
      <h2>Log entry types</h2>
      <p v-if="!logTypes.length" class="muted">No log entry types.</p>
      <ul v-else class="plain-list">
        <li v-for="lt in logTypes" :key="lt.id" :data-test="`log-type-${lt.key}`">
          <i v-if="lt.icon" class="pi" :class="lt.icon" />
          <strong>{{ lt.name }}</strong> <code>{{ lt.key }}</code>
          <span class="muted">{{ lt.applies_to }} &middot; {{ lt.fields.length }} fields</span>
          <Button icon="pi pi-pencil" text :aria-label="`Edit ${lt.name}`" @click="openLog(lt)" />
          <Button icon="pi pi-trash" text severity="danger" :aria-label="`Delete ${lt.name}`" @click="deleteLog(lt)" />
        </li>
      </ul>
      <Button data-test="add-log-type" label="Add log entry type" icon="pi pi-plus" text @click="openLog(null)" />
    </section>

    <section class="card actions">
      <Button data-test="export-pack" label="Export pack" icon="pi pi-download" severity="secondary" @click="exportPack" />
      <Button label="Delete category" icon="pi pi-trash" severity="danger" text @click="deleteCategory" />
    </section>

    <Dialog v-model:visible="fieldDialog" modal :header="editingField ? 'Edit field' : 'New field'" :style="{ width: '34rem', maxWidth: '95vw' }">
      <FieldDefEditor :key="editingField?.id ?? 'new'" :field="editingField" :scope-allowed="isUnit" :taken-keys="takenKeys" @save="saveField" @cancel="fieldDialog = false" />
    </Dialog>
    <Dialog v-model:visible="logDialog" modal :header="editingLog ? 'Edit log entry type' : 'New log entry type'" :style="{ width: '38rem', maxWidth: '95vw' }">
      <LogTypeEditor :key="editingLog?.id ?? 'new'" :log-type="editingLog" @save="saveLog" @cancel="logDialog = false" />
    </Dialog>
  </div>
  <p v-else-if="loading" class="muted">Loading...</p>
</template>

<style scoped>
.category-edit { max-width: 60rem; display: flex; flex-direction: column; gap: 1rem; }
.card { border: 1px solid var(--p-content-border-color); border-radius: 8px; padding: 0.75rem 1rem; }
.card h2 { margin-top: 0; font-size: 1.1rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 0.75rem; }
.grid label { display: flex; flex-direction: column; gap: 0.25rem; }
.wide { grid-column: 1 / -1; }
.label { font-weight: 600; margin-right: 0.5rem; }
.picker { border: 1px solid var(--p-content-border-color); border-radius: 6px; padding: 0.5rem; margin-top: 0.5rem; max-height: 16rem; overflow-y: auto; }
.actions { display: flex; gap: 0.5rem; justify-content: flex-end; }
.plain { width: 100%; border-collapse: collapse; margin-bottom: 0.75rem; }
.plain th, .plain td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--p-content-border-color); }
.plain-list { list-style: none; padding: 0; margin: 0; }
.plain-list li { display: flex; gap: 0.5rem; align-items: center; }
</style>
