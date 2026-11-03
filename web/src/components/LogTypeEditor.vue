<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import type { LogEntryTypeOut } from '@/api/types'
import FieldDefEditor, { type FieldDraft } from '@/components/FieldDefEditor.vue'
import { KEY_RE, slugKey } from '@/lib/keys'

const props = defineProps<{ initial?: LogEntryTypeOut | null; trackingMode: string }>()
const emit = defineEmits<{ save: [payload: Record<string, unknown>]; cancel: [] }>()

const existing = computed(() => !!props.initial)
const draft = reactive({
  key: props.initial?.key ?? '',
  name: props.initial?.name ?? '',
  applies_to: props.initial?.applies_to ?? (props.trackingMode === 'unit' ? 'unit' : 'item'),
  fields: [...((props.initial?.fields ?? []) as unknown as FieldDraft[])],
  summary_fields: [...(props.initial?.summary_fields ?? [])],
})
const keyTouched = ref(existing.value)
const editing = ref<number | 'new' | null>(null)

watch(
  () => draft.name,
  (name) => {
    if (!keyTouched.value) draft.key = slugKey(name)
  },
)

const valid = computed(() => KEY_RE.test(draft.key) && draft.name.trim() !== '')

function saveField(f: FieldDraft) {
  if (editing.value === 'new') draft.fields.push(f)
  else if (typeof editing.value === 'number') draft.fields.splice(editing.value, 1, f)
  editing.value = null
}

function removeField(i: number) {
  const [f] = draft.fields.splice(i, 1)
  draft.summary_fields = draft.summary_fields.filter((k) => k !== f.key)
}

function save() {
  const fields = draft.fields.map(({ ...f }) => {
    delete (f as Record<string, unknown>).scope
    delete (f as Record<string, unknown>).order
    return f
  })
  const payload: Record<string, unknown> = { name: draft.name.trim(), fields, summary_fields: draft.summary_fields }
  if (!existing.value) Object.assign(payload, { key: draft.key, applies_to: draft.applies_to })
  emit('save', payload)
}
</script>

<template>
  <div class="stack">
    <div class="grid-2">
      <div class="field"><label>Name</label><input v-model="draft.name" class="p2l-input" data-test="log-name" /></div>
      <div class="field">
        <label>Key</label>
        <input v-model="draft.key" class="p2l-input" :disabled="existing" @input="keyTouched = true" />
      </div>
      <div class="field">
        <label>Recorded per</label>
        <select v-model="draft.applies_to" class="p2l-input" :disabled="existing">
          <option value="unit" :disabled="trackingMode !== 'unit'">Unit</option>
          <option value="item">Item</option>
        </select>
      </div>
    </div>
    <table class="plain">
      <thead><tr><th>Field</th><th>Type</th><th>Show as latest value</th><th /></tr></thead>
      <tbody>
        <tr v-for="(f, i) in draft.fields" :key="f.key">
          <td>{{ f.label }} <span class="muted">{{ f.key }}</span></td>
          <td>{{ f.type }}</td>
          <td><input v-model="draft.summary_fields" type="checkbox" :value="f.key" /></td>
          <td class="row">
            <button class="p2l-btn" @click="editing = i">Edit</button>
            <button class="p2l-btn danger" @click="removeField(i)">Remove</button>
          </td>
        </tr>
      </tbody>
    </table>
    <FieldDefEditor
      v-if="editing !== null"
      :key="String(editing)"
      tracking-mode="bulk"
      hide-scope
      :initial="typeof editing === 'number' ? draft.fields[editing] : null"
      @save="saveField"
      @cancel="editing = null"
    />
    <div v-else><button class="p2l-btn" data-test="add-log-field" @click="editing = 'new'">Add field</button></div>
    <div class="row">
      <span class="spacer" />
      <button class="p2l-btn" @click="emit('cancel')">Cancel</button>
      <button class="p2l-btn primary" :disabled="!valid || editing !== null" data-test="save-log-type" @click="save">Save log type</button>
    </div>
  </div>
</template>
