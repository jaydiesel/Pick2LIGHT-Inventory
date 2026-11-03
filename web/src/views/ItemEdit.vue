<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, apiFetch } from '@/api/client'
import type { CategoryOut, FieldDefOut, ItemOut, LocationOut } from '@/api/types'
import FieldForm from '@/components/FieldForm.vue'
import LocationPicker from '@/components/LocationPicker.vue'
import { attrsPatch } from '@/lib/attrs'

const props = defineProps<{ id?: string }>()
const route = useRoute()
const router = useRouter()
const editing = computed(() => !!props.id)
const categories = ref<CategoryOut[]>([])
const specs = ref<FieldDefOut[]>([])
const errors = ref<Record<string, string>>({})
const error = ref('')
const busy = ref(false)
const picking = ref<'default' | 'initial' | null>(null)
const names = reactive<{ default: string; initial: string }>({ default: '', initial: '' })
const form = reactive({
  category_id: null as number | null,
  name: '', sku: '', description: '', notes: '',
  min_stock: null as number | null,
  default_location_id: null as number | null,
  attrs: {} as Record<string, unknown>,
  quantity: null as number | null,
  initial_location_id: null as number | null,
})
const barcode = computed(() => (typeof route.query.barcode === 'string' ? route.query.barcode : ''))
const category = computed(() => categories.value.find((c) => c.id === form.category_id) ?? null)
const itemSpecs = computed(() => specs.value.filter((s) => s.scope === 'item'))

watch(
  () => form.category_id,
  async (id) => {
    specs.value = id ? await apiFetch<FieldDefOut[]>(`/categories/${id}/fields`) : []
  },
)

async function locName(id: number | null): Promise<string> {
  return id ? (await apiFetch<LocationOut>(`/locations/${id}`)).path.map((p) => p.name).join(' › ') : ''
}

onMounted(async () => {
  categories.value = await apiFetch<CategoryOut[]>('/categories')
  if (props.id) {
    const item = await apiFetch<ItemOut>(`/items/${props.id}`)
    Object.assign(form, {
      category_id: item.category_id, name: item.name, sku: item.sku, description: item.description ?? '',
      notes: item.notes ?? '', min_stock: item.min_stock, default_location_id: item.default_location_id, attrs: { ...item.attrs },
    })
    names.default = await locName(item.default_location_id)
  }
})

async function choose(id: number) {
  if (picking.value === 'default') {
    form.default_location_id = id
    names.default = await locName(id)
  } else {
    form.initial_location_id = id
    names.initial = await locName(id)
  }
  picking.value = null
}

async function save() {
  errors.value = {}
  error.value = ''
  busy.value = true
  const body = {
    category_id: form.category_id,
    name: form.name.trim(),
    sku: form.sku.trim() || null,
    description: form.description || null,
    notes: form.notes || null,
    min_stock: form.min_stock,
    default_location_id: form.default_location_id,
    attrs: form.attrs,
  }
  try {
    let item: ItemOut
    const keys = itemSpecs.value.map((s) => s.key)
    if (props.id) {
      const original = await apiFetch<ItemOut>(`/items/${props.id}`)
      const attrs = attrsPatch(original.attrs, form.attrs, keys)
      item = await apiFetch<ItemOut>(`/items/${props.id}`, { method: 'PATCH', json: { ...body, attrs } })
    } else {
      item = await apiFetch<ItemOut>('/items', { method: 'POST', json: { ...body, attrs: attrsPatch({}, form.attrs, keys) } })
      if (barcode.value) {
        await apiFetch('/barcodes', { method: 'POST', json: { code: barcode.value, target_type: 'item', target_id: item.id, kind: 'manufacturer' } })
        await apiFetch(`/scan/unknown/${encodeURIComponent(barcode.value)}`, { method: 'DELETE' }).catch(() => undefined)
      }
      const where = form.initial_location_id ?? form.default_location_id
      if (item.tracking_mode === 'bulk' && form.quantity && where) {
        await apiFetch('/stock/add', { method: 'POST', json: { item_id: item.id, location_id: where, quantity: form.quantity } })
      }
    }
    router.push(`/items/${item.id}`)
  } catch (e) {
    if (e instanceof ApiError) {
      errors.value = e.fields
      error.value = Object.keys(e.fields).length ? 'Please fix the highlighted fields' : e.message
    } else error.value = String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <h1>{{ editing ? 'Edit item' : 'Add item' }}</h1>
  <form class="stack" @submit.prevent="save">
    <section class="card stack">
      <div class="field">
        <label for="cat">Category</label>
        <select id="cat" v-model="form.category_id" class="p2l-input" data-test="category">
          <option :value="null" disabled>Choose a category…</option>
          <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.path.map((p) => p.name).join(' › ') }}</option>
        </select>
        <span v-if="errors.category_id" class="error">{{ errors.category_id }}</span>
        <span v-if="category?.effective_tracking_mode === 'unit'" class="muted">Tracked per unit — add units with their own labels after saving.</span>
      </div>
      <p v-if="barcode" class="muted">Barcode <code>{{ barcode }}</code> will be attached to this item.</p>
    </section>
    <template v-if="form.category_id">
      <section class="card grid-2">
        <div class="field">
          <label for="name">Name *</label>
          <input id="name" v-model="form.name" class="p2l-input" data-test="name" />
          <span v-if="errors.name" class="error">{{ errors.name }}</span>
        </div>
        <div class="field">
          <label for="sku">SKU</label>
          <input id="sku" v-model="form.sku" class="p2l-input" placeholder="Leave blank to generate" data-test="sku" />
          <span v-if="!form.sku && !editing" class="muted">Will be generated from the category's pattern</span>
          <span v-if="errors.sku" class="error">{{ errors.sku }}</span>
        </div>
        <div class="field">
          <label for="min">Minimum stock</label>
          <input id="min" v-model.number="form.min_stock" class="p2l-input" type="number" min="0" />
        </div>
        <div class="field">
          <label>Default location</label>
          <div class="row">
            <button class="p2l-btn" type="button" @click="picking = 'default'">{{ names.default || 'Choose…' }}</button>
            <button v-if="form.default_location_id" class="p2l-btn" type="button" @click="form.default_location_id = null; names.default = ''">×</button>
          </div>
        </div>
        <div class="field"><label for="desc">Description</label><input id="desc" v-model="form.description" class="p2l-input" /></div>
        <div class="field"><label for="notes">Notes</label><input id="notes" v-model="form.notes" class="p2l-input" /></div>
      </section>
      <section v-if="itemSpecs.length" class="card">
        <FieldForm v-model="form.attrs" :specs="itemSpecs" :errors="errors" />
      </section>
      <section v-if="!editing && category?.effective_tracking_mode !== 'unit'" class="card grid-2">
        <div class="field">
          <label for="qty">Initial quantity</label>
          <input id="qty" v-model.number="form.quantity" class="p2l-input" type="number" min="0" step="any" data-test="quantity" />
        </div>
        <div class="field">
          <label>Put it in</label>
          <button class="p2l-btn" type="button" data-test="initial-location" @click="picking = 'initial'">
            {{ names.initial || names.default || 'Choose a location…' }}
          </button>
        </div>
      </section>
    </template>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="row">
      <span class="spacer" />
      <button class="p2l-btn" type="button" @click="router.back()">Cancel</button>
      <button class="p2l-btn primary" type="submit" :disabled="busy || !form.category_id || !form.name.trim()" data-test="save-item">Save</button>
    </div>
  </form>
  <LocationPicker :open="picking !== null" @select="choose" @close="picking = null" />
</template>
