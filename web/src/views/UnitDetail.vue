<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError, apiFetch } from '@/api/client'
import type { FieldDefOut, ItemOut, LatestOut, LogEntryOut, LogEntryTypeOut, MovementOut, UnitOut } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import AttachmentList from '@/components/AttachmentList.vue'
import FieldForm from '@/components/FieldForm.vue'
import LatestValues from '@/components/LatestValues.vue'
import LocationPicker from '@/components/LocationPicker.vue'
import LogEntryForm from '@/components/LogEntryForm.vue'
import MovementTable from '@/components/MovementTable.vue'
import { attrsPatch } from '@/lib/attrs'
import { printLabels } from '@/lib/labels'

const props = defineProps<{ id: string }>()
const router = useRouter()
const toast = useToast()
const unit = ref<UnitOut | null>(null)
const item = ref<ItemOut | null>(null)
const latest = ref<Record<string, LatestOut>>({})
const log = ref<LogEntryOut[]>([])
const logTypes = ref<LogEntryTypeOut[]>([])
const movements = ref<MovementOut[]>([])
const unitSpecs = ref<FieldDefOut[]>([])
const error = ref('')
const logging = ref<{ type: LogEntryTypeOut; entry: LogEntryOut | null } | null>(null)
const picking = ref<'move' | 'check_in' | null>(null)
const editing = ref(false)
const attrs = ref<Record<string, unknown>>({})
const attrErrors = ref<Record<string, string>>({})

const unitTypes = computed(() => logTypes.value.filter((t) => t.applies_to === 'unit'))
const status = computed(() => unit.value?.status ?? '')
const active = computed(() => status.value === 'in_stock' || status.value === 'checked_out')

async function load() {
  error.value = ''
  unit.value = await apiFetch<UnitOut>(`/units/${props.id}`)
  item.value = await apiFetch<ItemOut>(`/items/${unit.value.item_id}`)
  const cat = item.value.category_id
  const [l, entries, types, moves, fields] = await Promise.all([
    apiFetch<Record<string, LatestOut>>(`/units/${props.id}/latest`),
    apiFetch<LogEntryOut[]>(`/units/${props.id}/log`),
    apiFetch<LogEntryTypeOut[]>(`/categories/${cat}/log-types`),
    apiFetch<MovementOut[]>(`/movements?unit_id=${props.id}`),
    apiFetch<FieldDefOut[]>(`/categories/${cat}/fields`),
  ])
  latest.value = l
  log.value = entries
  logTypes.value = types
  movements.value = moves
  unitSpecs.value = fields.filter((f) => f.scope === 'unit')
  attrs.value = { ...unit.value.attrs }
}

function fail(e: unknown) {
  error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
  toast.add({ severity: 'error', summary: 'Not done', detail: error.value, life: 6000 })
}

async function act(path: string, body?: unknown) {
  try {
    await apiFetch(`/units/${props.id}/${path}`, { method: 'POST', json: body ?? {} })
    await load()
  } catch (e) {
    fail(e)
  }
}

async function setCondition(ev: Event) {
  try {
    await apiFetch(`/units/${props.id}/condition`, { method: 'PATCH', json: { condition: (ev.target as HTMLSelectElement).value } })
    await load()
  } catch (e) {
    fail(e)
  }
}

async function pick(id: number) {
  const mode = picking.value
  picking.value = null
  if (mode === 'move') await act('move', { location_id: id })
  else await act('check-in', { location_id: id })
}

async function saveAttrs() {
  attrErrors.value = {}
  const patch = attrsPatch(unit.value?.attrs ?? {}, attrs.value, unitSpecs.value.map((s) => s.key))
  try {
    await apiFetch(`/units/${props.id}`, { method: 'PATCH', json: { attrs: patch } })
    editing.value = false
    await load()
  } catch (e) {
    if (e instanceof ApiError) attrErrors.value = e.fields
    fail(e)
  }
}

async function deleteEntry(e: LogEntryOut) {
  if (!window.confirm('Delete this log entry?')) return
  await apiFetch(`/log-entries/${e.id}`, { method: 'DELETE' }).catch(fail)
  await load()
}

async function print() {
  try {
    await printLabels('unit', [Number(props.id)])
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

async function remove() {
  if (!window.confirm(`Delete unit ${unit.value?.unit_code}? It goes to the trash.`)) return
  try {
    await apiFetch(`/units/${props.id}`, { method: 'DELETE' })
    router.push(`/items/${unit.value?.item_id}`)
  } catch (e) {
    fail(e)
  }
}

function saved() {
  logging.value = null
  load()
}

watch(() => props.id, load)
onMounted(load)
</script>

<template>
  <div v-if="unit && item">
    <p class="muted"><RouterLink :to="`/items/${item.id}`">{{ item.name }}</RouterLink> · {{ item.sku }}</p>
    <div class="row">
      <h1 class="spacer">{{ unit.unit_code }}</h1>
      <span :class="['badge', { ok: status === 'in_stock', warn: status === 'checked_out', danger: !active }]">{{ status.replace('_', ' ') }}</span>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="card row">
      <label class="row">Condition
        <select class="p2l-input" :value="unit.condition" data-test="condition" @change="setCondition">
          <option value="new">New</option><option value="tested_good">Tested good</option><option value="untested">Untested</option>
          <option value="faulty">Faulty</option><option value="for_parts">For parts</option>
        </select>
      </label>
      <button v-if="status === 'in_stock'" class="p2l-btn" data-test="unit-check-out" @click="act('check-out')">Check out</button>
      <button v-if="status === 'checked_out'" class="p2l-btn" data-test="unit-check-in" @click="act('check-in')">Check in</button>
      <button v-if="status === 'checked_out'" class="p2l-btn" @click="picking = 'check_in'">Check in elsewhere…</button>
      <button v-if="active" class="p2l-btn" @click="picking = 'move'">Move</button>
      <button v-if="active" class="p2l-btn" @click="act('consume')">Used up</button>
      <button v-if="active" class="p2l-btn" @click="act('dispose')">Dispose</button>
      <button class="p2l-btn" @click="print"><i class="pi pi-print" /> Print label</button>
      <span class="spacer" />
      <button class="p2l-btn danger" @click="remove">Delete</button>
    </div>

    <div class="grid-2">
      <section class="card">
        <h2>Details</h2>
        <table class="plain">
          <tbody>
            <tr><th>Location</th><td>{{ unit.location_path.map((p) => p.name).join(' › ') || '—' }}</td></tr>
            <tr v-if="unit.serial_number"><th>Serial</th><td>{{ unit.serial_number }}</td></tr>
            <tr v-for="(v, k) in item.attrs_display" :key="`i${k}`"><th>{{ k }}</th><td>{{ v }}</td></tr>
            <tr v-for="(v, k) in unit.attrs_display" :key="`u${k}`"><th>{{ k }}</th><td>{{ v }}</td></tr>
          </tbody>
        </table>
        <button v-if="unitSpecs.length" class="p2l-btn" @click="editing = true">Edit unit fields</button>
      </section>
      <section class="card">
        <h2>Latest values</h2>
        <p v-if="!Object.keys(latest).length" class="muted">No tests recorded yet.</p>
        <LatestValues :latest="latest" :log-types="logTypes" />
      </section>
    </div>

    <section class="card">
      <div class="row">
        <h2 class="spacer">History log</h2>
        <button v-for="t in unitTypes" :key="t.id" class="p2l-btn primary" :data-test="`add-${t.key}`" @click="logging = { type: t, entry: null }">Add {{ t.name }}</button>
      </div>
      <p v-if="!log.length" class="muted">No entries yet.</p>
      <table v-else class="plain" data-test="log-table">
        <thead><tr><th>When</th><th>Type</th><th>Values</th><th>Notes</th><th /></tr></thead>
        <tbody>
          <tr v-for="e in log" :key="e.id">
            <td>{{ new Date(e.performed_at).toLocaleString() }}</td>
            <td>{{ e.type_name }}</td>
            <td>{{ Object.values(e.values_display).join(' · ') }}</td>
            <td>{{ e.notes }}</td>
            <td class="row">
              <button class="p2l-btn" @click="logging = { type: logTypes.find((t) => t.id === e.log_entry_type_id)!, entry: e }">Edit</button>
              <button class="p2l-btn danger" @click="deleteEntry(e)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <div class="grid-2">
      <section class="card"><h2>Files</h2><AttachmentList owner-type="unit" :owner-id="unit.id" /></section>
      <section class="card"><h2>Movements</h2><MovementTable :movements="movements" @undo="undo" /></section>
    </div>

    <AppModal :open="!!logging" :title="logging?.type.name ?? ''" wide @close="logging = null">
      <LogEntryForm v-if="logging" :log-type="logging.type" :unit-id="unit.id" :entry="logging.entry" @saved="saved" />
    </AppModal>
    <AppModal :open="editing" title="Unit fields" wide @close="editing = false">
      <form class="stack" @submit.prevent="saveAttrs">
        <FieldForm v-model="attrs" :specs="unitSpecs" :errors="attrErrors" />
        <button class="p2l-btn primary">Save</button>
      </form>
    </AppModal>
    <LocationPicker :open="picking !== null" @select="pick" @close="picking = null" />
  </div>
</template>
