<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError, apiFetch } from '@/api/client'
import type { FieldDefOut, ItemOut, LatestOut, LogEntryOut, LogEntryTypeOut, MovementOut, PurchaseSourceOut, StockRow, UnitOut } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import AttachmentList from '@/components/AttachmentList.vue'
import FieldForm from '@/components/FieldForm.vue'
import LocationPicker from '@/components/LocationPicker.vue'
import LogEntryForm from '@/components/LogEntryForm.vue'
import MovementTable from '@/components/MovementTable.vue'
import { printLabels } from '@/lib/labels'

const props = defineProps<{ id: string }>()
const router = useRouter()
const toast = useToast()
const item = ref<ItemOut | null>(null)
const stock = ref<StockRow[]>([])
const units = ref<UnitOut[]>([])
const latest = ref<Record<number, Record<string, LatestOut>>>({})
const movements = ref<MovementOut[]>([])
const sources = ref<PurchaseSourceOut[]>([])
const itemLogTypes = ref<LogEntryTypeOut[]>([])
const itemLog = ref<LogEntryOut[]>([])
const unitSpecs = ref<FieldDefOut[]>([])
const error = ref('')

type Action = 'check_in' | 'check_out' | 'consume' | 'move' | 'adjust'
const action = ref<Action | null>(null)
const act = reactive({ quantity: 1, location_id: null as number | null, to_location_id: null as number | null, label: '', toLabel: '' })
const picking = ref<'from' | 'to' | null>(null)
const addingUnit = ref(false)
const unitForm = reactive({ unit_code: '', serial_number: '', condition: 'untested', location_id: null as number | null, locLabel: '', attrs: {} as Record<string, unknown> })
const unitErrors = ref<Record<string, string>>({})
const logging = ref<LogEntryTypeOut | null>(null)
const source = reactive({ supplier: '', url: '', unit_price: null as number | null, currency: '', supplier_part_number: '' })

const perUnit = computed(() => item.value?.tracking_mode === 'unit')
const low = computed(() => !!item.value && item.value.min_stock !== null && item.value.on_hand < item.value.min_stock)

async function load() {
  error.value = ''
  const id = props.id
  item.value = await apiFetch<ItemOut>(`/items/${id}`)
  const catId = item.value.category_id
  const [m, s, lt] = await Promise.all([
    apiFetch<MovementOut[]>(`/movements?item_id=${id}&limit=50`),
    apiFetch<PurchaseSourceOut[]>(`/items/${id}/purchase-sources`),
    apiFetch<LogEntryTypeOut[]>(`/categories/${catId}/log-types`),
  ])
  movements.value = m
  sources.value = s
  itemLogTypes.value = lt.filter((t) => t.applies_to === 'item')
  itemLog.value = itemLogTypes.value.length ? await apiFetch<LogEntryOut[]>(`/items/${id}/log`) : []
  if (perUnit.value) {
    units.value = await apiFetch<UnitOut[]>(`/items/${id}/units`)
    const entries = await Promise.all(units.value.map(async (u) => [u.id, await apiFetch<Record<string, LatestOut>>(`/units/${u.id}/latest`)] as const))
    latest.value = Object.fromEntries(entries)
    unitSpecs.value = (await apiFetch<FieldDefOut[]>(`/categories/${catId}/fields`)).filter((f) => f.scope === 'unit')
  } else {
    stock.value = await apiFetch<StockRow[]>(`/items/${id}/stock`)
  }
}

function fail(e: unknown) {
  error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
  toast.add({ severity: 'error', summary: 'Not done', detail: error.value, life: 6000 })
}

function path(row: { location_path: { name: string }[] }) {
  return row.location_path.map((p) => p.name).join(' › ')
}

function start(a: Action, row?: StockRow) {
  action.value = a
  Object.assign(act, { quantity: a === 'adjust' ? row?.quantity ?? 0 : 1, location_id: row?.location_id ?? null, to_location_id: null, label: row ? path(row) : '', toLabel: '' })
  if (!row && a === 'check_in' && item.value?.default_location_id) act.location_id = item.value.default_location_id
}

async function pick(id: number) {
  const loc = await apiFetch<{ path: { name: string }[] }>(`/locations/${id}`)
  const label = loc.path.map((p) => p.name).join(' › ')
  if (picking.value === 'to') Object.assign(act, { to_location_id: id, toLabel: label })
  else if (picking.value === 'from' && addingUnit.value) Object.assign(unitForm, { location_id: id, locLabel: label })
  else Object.assign(act, { location_id: id, label })
  picking.value = null
}

async function runAction() {
  const a = action.value
  if (!a || !item.value) return
  const base = { item_id: item.value.id }
  try {
    if (a === 'check_in') await apiFetch('/stock/add', { method: 'POST', json: { ...base, location_id: act.location_id, quantity: act.quantity } })
    else if (a === 'check_out' || a === 'consume')
      await apiFetch('/stock/remove', { method: 'POST', json: { ...base, location_id: act.location_id, quantity: act.quantity, reason: a } })
    else if (a === 'move')
      await apiFetch('/stock/move', { method: 'POST', json: { ...base, from_location_id: act.location_id, to_location_id: act.to_location_id, quantity: act.quantity } })
    else await apiFetch('/stock/adjust', { method: 'POST', json: { ...base, location_id: act.location_id, counted: act.quantity } })
    action.value = null
    await load()
  } catch (e) {
    fail(e)
  }
}

async function undo(id: number) {
  try {
    await apiFetch(`/movements/${id}/undo`, { method: 'POST' })
    await load()
  } catch (e) {
    fail(e)
  }
}

async function print() {
  try {
    await printLabels('item', [Number(props.id)])
  } catch (e) {
    fail(e)
  }
}

async function remove() {
  if (!window.confirm(`Delete "${item.value?.name}"? It goes to the trash.`)) return
  try {
    await apiFetch(`/items/${props.id}`, { method: 'DELETE' })
    router.push('/search')
  } catch (e) {
    fail(e)
  }
}

async function addUnit() {
  unitErrors.value = {}
  try {
    const u = await apiFetch<UnitOut>('/units', {
      method: 'POST',
      json: {
        item_id: Number(props.id), unit_code: unitForm.unit_code.trim() || null, serial_number: unitForm.serial_number.trim() || null,
        condition: unitForm.condition, location_id: unitForm.location_id, attrs: unitForm.attrs,
      },
    })
    addingUnit.value = false
    Object.assign(unitForm, { unit_code: '', serial_number: '', attrs: {} })
    toast.add({ severity: 'success', summary: `Added ${u.unit_code}`, life: 3000 })
    await load()
  } catch (e) {
    if (e instanceof ApiError) unitErrors.value = e.fields
    fail(e)
  }
}

async function addSource() {
  try {
    await apiFetch(`/items/${props.id}/purchase-sources`, {
      method: 'POST',
      json: { supplier: source.supplier.trim(), url: source.url.trim() || null, unit_price: source.unit_price, currency: source.currency.trim() || null, supplier_part_number: source.supplier_part_number.trim() || null },
    })
    Object.assign(source, { supplier: '', url: '', unit_price: null, currency: '', supplier_part_number: '' })
    await load()
  } catch (e) {
    fail(e)
  }
}

async function removeSource(s: PurchaseSourceOut) {
  await apiFetch(`/purchase-sources/${s.id}`, { method: 'DELETE' }).catch(fail)
  await load()
}

watch(() => props.id, load)
onMounted(load)
</script>

<template>
  <div v-if="item">
    <p class="muted">{{ item.category_path.map((p) => p.name).join(' › ') }}</p>
    <div class="row">
      <h1 class="spacer">{{ item.name }} <span class="muted">{{ item.sku }}</span></h1>
      <span class="badge" data-test="on-hand">On hand: {{ item.on_hand }}</span>
      <span v-if="low" class="badge warn">Low stock</span>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="row card">
      <template v-if="!perUnit">
        <button class="p2l-btn" data-test="action-check-in" @click="start('check_in')">Check in</button>
        <button class="p2l-btn" @click="start('check_out')">Check out</button>
        <button class="p2l-btn" @click="start('move')">Move</button>
        <button class="p2l-btn" @click="start('adjust')">Correct count</button>
      </template>
      <button v-else class="p2l-btn primary" data-test="add-unit" @click="addingUnit = true">Add unit</button>
      <button class="p2l-btn" @click="print"><i class="pi pi-print" /> Print label</button>
      <span class="spacer" />
      <RouterLink class="p2l-btn" :to="`/items/${item.id}/edit`">Edit</RouterLink>
      <button class="p2l-btn danger" @click="remove">Delete</button>
    </div>

    <div class="grid-2">
      <section class="card">
        <h2>Details</h2>
        <table class="plain">
          <tbody>
            <tr v-for="(v, k) in item.attrs_display" :key="k"><th>{{ k }}</th><td>{{ v }}</td></tr>
            <tr v-if="item.description"><th>Description</th><td>{{ item.description }}</td></tr>
            <tr v-if="item.notes"><th>Notes</th><td>{{ item.notes }}</td></tr>
            <tr v-if="item.min_stock !== null"><th>Minimum</th><td>{{ item.min_stock }}</td></tr>
            <tr v-for="b in item.barcodes" :key="b.id"><th>Barcode</th><td><code>{{ b.code }}</code> <span class="muted">{{ b.kind }}</span></td></tr>
          </tbody>
        </table>
      </section>
      <section v-if="!perUnit" class="card">
        <h2>Stock</h2>
        <p v-if="!stock.length" class="muted">Not in stock anywhere.</p>
        <table v-else class="plain" data-test="stock-table">
          <tbody>
            <tr v-for="row in stock" :key="row.location_id">
              <td><RouterLink :to="`/locations/${row.location_id}`">{{ path(row) }}</RouterLink></td>
              <td>{{ row.quantity }}</td>
              <td class="row">
                <button class="p2l-btn" @click="start('check_out', row)">Take</button>
                <button class="p2l-btn" @click="start('move', row)">Move</button>
                <button class="p2l-btn" @click="start('adjust', row)">Count</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <section v-if="perUnit" class="card">
      <h2>Units</h2>
      <p v-if="!units.length" class="muted">No units yet — add one for each physical piece.</p>
      <table v-else class="plain" data-test="units-table">
        <thead><tr><th>Code</th><th>Condition</th><th>Status</th><th>Location</th><th>Latest</th></tr></thead>
        <tbody>
          <tr v-for="u in units" :key="u.id">
            <td><RouterLink :to="`/units/${u.id}`">{{ u.unit_code }}</RouterLink></td>
            <td>{{ u.condition.replace('_', ' ') }}</td>
            <td>{{ u.status.replace('_', ' ') }}</td>
            <td>{{ path(u) || '—' }}</td>
            <td class="muted">{{ Object.values(latest[u.id] ?? {}).flatMap((l) => Object.values(l.values_display)).join(' · ') }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="itemLogTypes.length" class="card">
      <div class="row"><h2 class="spacer">History log</h2>
        <button v-for="t in itemLogTypes" :key="t.id" class="p2l-btn" @click="logging = t">Add {{ t.name }}</button>
      </div>
      <table class="plain">
        <tbody>
          <tr v-for="e in itemLog" :key="e.id"><td>{{ new Date(e.performed_at).toLocaleString() }}</td><td>{{ e.type_name }}</td><td>{{ Object.values(e.values_display).join(' · ') }}</td></tr>
        </tbody>
      </table>
    </section>

    <div class="grid-2">
      <section class="card"><h2>Files</h2><AttachmentList owner-type="item" :owner-id="item.id" /></section>
      <section class="card stack">
        <h2>Where to buy</h2>
        <table v-if="sources.length" class="plain">
          <tbody>
            <tr v-for="s in sources" :key="s.id">
              <td><a v-if="s.url" :href="s.url" target="_blank" rel="noopener">{{ s.supplier }}</a><span v-else>{{ s.supplier }}</span></td>
              <td>{{ s.supplier_part_number }}</td>
              <td>{{ s.unit_price !== null ? `${s.unit_price} ${s.currency ?? ''}` : '' }}</td>
              <td><button class="p2l-btn" aria-label="Remove" @click="removeSource(s)"><i class="pi pi-trash" /></button></td>
            </tr>
          </tbody>
        </table>
        <form class="row" @submit.prevent="addSource">
          <input v-model="source.supplier" class="p2l-input" placeholder="Shop" />
          <input v-model="source.url" class="p2l-input" type="url" placeholder="Link" />
          <input v-model="source.supplier_part_number" class="p2l-input" placeholder="Part no." />
          <input v-model.number="source.unit_price" class="p2l-input" type="number" step="any" min="0" placeholder="Price" style="width: 6rem" />
          <input v-model="source.currency" class="p2l-input" maxlength="3" placeholder="USD" style="width: 4.5rem" />
          <button class="p2l-btn" :disabled="!source.supplier.trim()">Add</button>
        </form>
      </section>
    </div>

    <section class="card"><h2>History</h2><MovementTable :movements="movements" @undo="undo" /></section>

    <AppModal :open="action !== null" :title="{ check_in: 'Check in', check_out: 'Check out', consume: 'Use up', move: 'Move', adjust: 'Correct the count' }[action ?? 'check_in']" @close="action = null">
      <form class="stack" @submit.prevent="runAction">
        <div class="field">
          <label>{{ action === 'adjust' ? 'Counted quantity' : 'Quantity' }}</label>
          <input v-model.number="act.quantity" class="p2l-input" type="number" step="any" :min="action === 'adjust' ? 0 : 0.0001" data-test="action-quantity" />
        </div>
        <div class="field">
          <label>{{ action === 'move' ? 'From' : 'Location' }}</label>
          <select v-if="action !== 'check_in' && stock.length" v-model="act.location_id" class="p2l-input">
            <option v-for="row in stock" :key="row.location_id" :value="row.location_id">{{ path(row) }} ({{ row.quantity }})</option>
          </select>
          <button v-else type="button" class="p2l-btn" data-test="action-location" @click="picking = 'from'">{{ act.label || 'Choose…' }}</button>
        </div>
        <div v-if="action === 'move'" class="field">
          <label>To</label>
          <button type="button" class="p2l-btn" @click="picking = 'to'">{{ act.toLabel || 'Choose…' }}</button>
        </div>
        <button class="p2l-btn primary" :disabled="!act.location_id || (action === 'move' && !act.to_location_id)" data-test="action-save">Save</button>
      </form>
    </AppModal>

    <AppModal :open="addingUnit" title="Add unit" wide @close="addingUnit = false">
      <form class="stack" @submit.prevent="addUnit">
        <div class="grid-2">
          <div class="field"><label>Unit code</label><input v-model="unitForm.unit_code" class="p2l-input" placeholder="Leave blank to generate" /></div>
          <div class="field"><label>Serial number</label><input v-model="unitForm.serial_number" class="p2l-input" /></div>
          <div class="field">
            <label>Condition</label>
            <select v-model="unitForm.condition" class="p2l-input">
              <option value="new">New</option><option value="tested_good">Tested good</option><option value="untested">Untested</option>
              <option value="faulty">Faulty</option><option value="for_parts">For parts</option>
            </select>
          </div>
          <div class="field"><label>Location</label><button type="button" class="p2l-btn" @click="picking = 'from'">{{ unitForm.locLabel || 'Choose…' }}</button></div>
        </div>
        <FieldForm v-if="unitSpecs.length" v-model="unitForm.attrs" :specs="unitSpecs" :errors="unitErrors" />
        <button class="p2l-btn primary" data-test="save-unit">Add unit</button>
      </form>
    </AppModal>

    <AppModal :open="!!logging" :title="logging?.name ?? ''" wide @close="logging = null">
      <LogEntryForm v-if="logging" :log-type="logging" :item-id="item.id" @saved="logging = null; load()" />
    </AppModal>

    <LocationPicker :open="picking !== null" @select="pick" @close="picking = null" />
  </div>
</template>
