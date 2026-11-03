<script setup lang="ts">
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import { computed, reactive, ref } from 'vue'
import type { components } from '../api/schema'
import { KEY_RE, slugify } from '../lib/patterns'
import FieldDefEditor from './FieldDefEditor.vue'

type LogEntryTypeOut = components['schemas']['LogEntryTypeOut']
type FieldBase = components['schemas']['FieldBase']

const props = defineProps<{ logType?: LogEntryTypeOut | null; takenKeys?: string[] }>()
const emit = defineEmits<{ save: [body: Record<string, unknown>]; cancel: [] }>()

const APPLIES = [
  { value: 'unit', label: 'Unit' },
  { value: 'item', label: 'Item' },
]

const lt = props.logType
const form = reactive({
  name: lt?.name ?? '',
  key: lt?.key ?? '',
  icon: lt?.icon ?? '',
  applies_to: (lt?.applies_to ?? 'unit') as 'unit' | 'item',
  fields: structuredClone(lt?.fields ?? []) as FieldBase[],
  summary_fields: [...(lt?.summary_fields ?? [])],
})
const keyTouched = ref(!!lt)
/** Index of the field being edited, -1 for a new one, null when the field editor is closed. */
const editingField = ref<number | null>(null)

function onName(value: string | undefined) {
  form.name = value ?? ''
  if (!keyTouched.value) form.key = slugify(form.name)
}
function onKey(value: string | undefined) {
  keyTouched.value = true
  form.key = value ?? ''
}

const fieldKeys = computed(() => form.fields.map((f) => f.key))
const editedField = computed(() => (editingField.value !== null && editingField.value >= 0 ? form.fields[editingField.value] : null))
const fieldTakenKeys = computed(() => [...(props.takenKeys ?? []), ...fieldKeys.value])

function onFieldSave(body: Record<string, unknown>) {
  const i = editingField.value
  if (i === null) return
  if (i < 0) {
    form.fields.push({ ...body, order: form.fields.length } as FieldBase)
  } else {
    const oldKey = form.fields[i].key
    form.fields[i] = { ...form.fields[i], ...body } as FieldBase
    const newKey = form.fields[i].key
    if (newKey !== oldKey) form.summary_fields = form.summary_fields.map((k) => (k === oldKey ? newKey : k))
  }
  editingField.value = null
}
function removeField(i: number) {
  const [gone] = form.fields.splice(i, 1)
  form.fields.forEach((f, idx) => (f.order = idx))
  form.summary_fields = form.summary_fields.filter((k) => k !== gone.key)
}

const valid = computed(() => form.name.trim() !== '' && KEY_RE.test(form.key) && editingField.value === null)

function snapshot(): Record<string, unknown> {
  return {
    key: form.key,
    name: form.name.trim(),
    icon: form.icon.trim() || null,
    applies_to: form.applies_to,
    fields: form.fields,
    summary_fields: form.summary_fields,
  }
}

function save() {
  if (!valid.value) return
  const snap = snapshot()
  if (!lt) return emit('save', snap)
  const original: Record<string, unknown> = {
    key: lt.key, name: lt.name, icon: lt.icon ?? null, applies_to: lt.applies_to,
    fields: lt.fields, summary_fields: lt.summary_fields,
  }
  const changed: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(snap)) {
    if (JSON.stringify(v) !== JSON.stringify(original[k])) changed[k] = v
  }
  emit('save', changed)
}
</script>

<template>
  <FieldDefEditor
    v-if="editingField !== null"
    :field="editedField"
    :scope-allowed="false"
    :taken-keys="fieldTakenKeys"
    @save="onFieldSave"
    @cancel="editingField = null"
  />
  <form v-else class="log-type-editor" @submit.prevent="save">
    <label>Name <InputText data-test="lt-name" :model-value="form.name" @update:model-value="onName" /></label>
    <label>Key <InputText data-test="lt-key" :model-value="form.key" :invalid="!!form.key && !KEY_RE.test(form.key)" @update:model-value="onKey" /></label>
    <label>Icon (PrimeIcons class, e.g. pi-bolt) <InputText v-model="form.icon" data-test="lt-icon" /></label>
    <label>Applies to
      <Select v-model="form.applies_to" :options="APPLIES" option-label="label" option-value="value" data-test="lt-applies" />
    </label>

    <fieldset>
      <legend>Fields</legend>
      <p v-if="!form.fields.length" class="muted">No fields yet.</p>
      <table v-else class="fields">
        <thead><tr><th>Label</th><th>Key</th><th>Type</th><th>Summary</th><th /></tr></thead>
        <tbody>
          <tr v-for="(f, i) in form.fields" :key="f.key">
            <td>{{ f.label }}</td>
            <td><code>{{ f.key }}</code></td>
            <td>{{ f.type }}</td>
            <td><Checkbox v-model="form.summary_fields" :value="f.key" :data-test="`summary-${f.key}`" :aria-label="`Show ${f.label} as a latest value`" /></td>
            <td class="actions">
              <Button type="button" icon="pi pi-pencil" text :aria-label="`Edit ${f.label}`" @click="editingField = i" />
              <Button type="button" icon="pi pi-trash" text severity="danger" :aria-label="`Remove ${f.label}`" @click="removeField(i)" />
            </td>
          </tr>
        </tbody>
      </table>
      <Button type="button" label="Add field" icon="pi pi-plus" text data-test="lt-add-field" @click="editingField = -1" />
    </fieldset>

    <div class="actions">
      <Button type="button" label="Cancel" text @click="emit('cancel')" />
      <Button type="submit" label="Save" data-test="lt-save" :disabled="!valid" />
    </div>
  </form>
</template>

<style scoped>
.log-type-editor { display: flex; flex-direction: column; gap: 0.75rem; }
.log-type-editor label { display: flex; flex-direction: column; gap: 0.25rem; }
.fields { width: 100%; border-collapse: collapse; }
.fields th, .fields td { text-align: left; padding: 0.25rem 0.5rem; }
.actions { display: flex; justify-content: flex-end; gap: 0.25rem; }
</style>
