<script setup lang="ts">
import { computed, ref } from 'vue'

import { ApiError, apiFetch } from '@/api/client'
import type { FieldDefOut, LogEntryOut, LogEntryTypeOut } from '@/api/types'
import FieldForm from '@/components/FieldForm.vue'
import { attrsPatch } from '@/lib/attrs'

const props = defineProps<{ logType: LogEntryTypeOut; unitId?: number; itemId?: number; entry?: LogEntryOut | null }>()
const emit = defineEmits<{ saved: [entry: LogEntryOut] }>()

function localNow(d = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const values = ref<Record<string, unknown>>({ ...(props.entry?.values ?? {}) })
const when = ref(props.entry ? localNow(new Date(props.entry.performed_at)) : localNow())
const notes = ref(props.entry?.notes ?? '')
const errors = ref<Record<string, string>>({})
const error = ref('')
const specs = computed(() =>
  (props.logType.fields as Record<string, unknown>[]).map(
    (f, i) => ({ id: i, category_id: props.logType.category_id, scope: 'item', inherited_from: null, required: false, filterable: false, show_on_label: false, number_unit: null, number_si_prefixes: false, min: null, max: null, decimals: null, options: [], help_text: null, order: i, ...f }) as unknown as FieldDefOut,
  ),
)

async function save() {
  errors.value = {}
  error.value = ''
  const performed_at = new Date(when.value).toISOString()
  const keys = specs.value.map((s) => s.key)
  const patch = attrsPatch(props.entry?.values ?? {}, values.value, keys)
  try {
    const entry = props.entry
      ? await apiFetch<LogEntryOut>(`/log-entries/${props.entry.id}`, { method: 'PATCH', json: { values: patch, performed_at, notes: notes.value || null } })
      : await apiFetch<LogEntryOut>('/log-entries', {
          method: 'POST',
          json: { log_entry_type_id: props.logType.id, unit_id: props.unitId ?? null, item_id: props.itemId ?? null, performed_at, values: patch, notes: notes.value || null },
        })
    emit('saved', entry)
  } catch (e) {
    if (e instanceof ApiError) {
      errors.value = e.fields
      error.value = Object.keys(e.fields).length ? 'Please fix the highlighted fields' : e.message
    } else error.value = String(e)
  }
}
</script>

<template>
  <form class="stack" @submit.prevent="save">
    <div class="field"><label for="when">Date and time</label><input id="when" v-model="when" class="p2l-input" type="datetime-local" data-test="when" /></div>
    <FieldForm v-model="values" :specs="specs" :errors="errors" />
    <div class="field"><label for="lnotes">Notes</label><textarea id="lnotes" v-model="notes" class="p2l-input" rows="2" /></div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="row"><span class="spacer" /><button class="p2l-btn primary" data-test="save-entry">Save entry</button></div>
  </form>
</template>
