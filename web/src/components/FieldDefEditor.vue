<script setup lang="ts">
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import { computed, reactive, ref } from 'vue'
import type { components } from '../api/schema'
import { KEY_RE, slugify } from '../lib/patterns'

type FieldDefOut = components['schemas']['FieldDefOut']
type FieldBase = components['schemas']['FieldBase']
type FieldType = FieldBase['type']

/** Editable shape of a field; used for field definitions and log-type fields (no scope). */
type FieldLike = FieldBase & { scope?: 'item' | 'unit' }

const props = defineProps<{
  /** Existing field to edit; omit to create one. */
  field?: FieldDefOut | FieldLike | null
  /** Offer the item/unit scope (only for per-unit categories, and never for log-type fields). */
  scopeAllowed: boolean
  /** Keys that are already taken (inherited, siblings, descendants); the field's own key is ignored. */
  takenKeys?: string[]
}>()
const emit = defineEmits<{ save: [body: Record<string, unknown>]; cancel: [] }>()

const TYPES: { value: FieldType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'long_text', label: 'Long text' },
  { value: 'number', label: 'Number' },
  { value: 'select', label: 'Select' },
  { value: 'multi_select', label: 'Multi-select' },
  { value: 'boolean', label: 'Yes / no' },
  { value: 'date', label: 'Date' },
  { value: 'url', label: 'URL' },
]
const SCOPES = [
  { value: 'item', label: 'Item' },
  { value: 'unit', label: 'Each unit' },
]

interface OptionRow {
  value: string
  label: string
  sku_code: string
}

const editing = computed(() => !!props.field)
const f = props.field
const form = reactive({
  label: f?.label ?? '',
  key: f?.key ?? '',
  help_text: f?.help_text ?? '',
  type: (f?.type ?? 'text') as FieldType,
  scope: (f?.scope ?? 'item') as 'item' | 'unit',
  required: f?.required ?? false,
  filterable: f?.filterable ?? false,
  show_on_label: f?.show_on_label ?? false,
  number_unit: f?.number_unit ?? '',
  number_si_prefixes: f?.number_si_prefixes ?? false,
  min: (f?.min ?? null) as number | null,
  max: (f?.max ?? null) as number | null,
  decimals: (f?.decimals ?? null) as number | null,
  options: (f?.options ?? []).map((o): OptionRow => ({ value: o.value, label: o.label, sku_code: o.sku_code ?? '' })),
})
// An existing key is never silently rewritten when the label changes.
const keyTouched = ref(editing.value)

function onLabel(value: string | undefined) {
  form.label = value ?? ''
  if (!keyTouched.value) form.key = slugify(form.label)
}
function onKey(value: string | undefined) {
  keyTouched.value = true
  form.key = value ?? ''
}

const isNumber = computed(() => form.type === 'number')
const isSelect = computed(() => form.type === 'select' || form.type === 'multi_select')

function addOption() {
  form.options.push({ value: '', label: '', sku_code: '' })
}
function removeOption(i: number) {
  form.options.splice(i, 1)
}

const blank = (o: OptionRow) => !o.value.trim() && !o.label.trim() && !o.sku_code.trim()
const filledOptions = computed(() => form.options.filter((o) => !blank(o)))
const optionsValid = computed(
  () => !isSelect.value || (filledOptions.value.length > 0 && filledOptions.value.every((o) => o.value.trim() && o.label.trim())),
)
const keyError = computed(() => {
  if (!form.key) return ''
  if (!KEY_RE.test(form.key)) return 'Use lowercase letters, digits and underscores, starting with a letter.'
  const taken = (props.takenKeys ?? []).filter((k) => k !== props.field?.key)
  return taken.includes(form.key) ? 'This key is already used by another field.' : ''
})
const valid = computed(() => form.label.trim() !== '' && KEY_RE.test(form.key) && !keyError.value && optionsValid.value)

const orNull = (s: string) => (s.trim() === '' ? null : s.trim())

/** Every editable key in its API shape; keys that do not apply to the type are cleared. */
function snapshot(): Record<string, unknown> {
  const snap: Record<string, unknown> = {
    key: form.key,
    label: form.label.trim(),
    help_text: orNull(form.help_text),
    type: form.type,
    required: form.required,
    filterable: form.filterable,
    show_on_label: form.show_on_label,
    number_unit: isNumber.value ? orNull(form.number_unit) : null,
    number_si_prefixes: isNumber.value ? form.number_si_prefixes : false,
    min: isNumber.value ? form.min : null,
    max: isNumber.value ? form.max : null,
    decimals: isNumber.value ? form.decimals : null,
    options: isSelect.value
      ? filledOptions.value.map((o) => ({ value: o.value.trim(), label: o.label.trim(), sku_code: orNull(o.sku_code) }))
      : null,
  }
  if (props.scopeAllowed) snap.scope = form.scope
  return snap
}

/** Normalised original, same shape as snapshot(), to diff against. */
const original = f ? snapshotOf(f) : null
function snapshotOf(src: FieldLike): Record<string, unknown> {
  const num = src.type === 'number'
  const sel = src.type === 'select' || src.type === 'multi_select'
  const snap: Record<string, unknown> = {
    key: src.key,
    label: src.label,
    help_text: src.help_text ?? null,
    type: src.type,
    required: src.required,
    filterable: src.filterable,
    show_on_label: src.show_on_label,
    number_unit: num ? (src.number_unit ?? null) : null,
    number_si_prefixes: num ? src.number_si_prefixes : false,
    min: num ? (src.min ?? null) : null,
    max: num ? (src.max ?? null) : null,
    decimals: num ? (src.decimals ?? null) : null,
    options: sel ? (src.options ?? []).map((o) => ({ value: o.value, label: o.label, sku_code: o.sku_code ?? null })) : null,
  }
  if (props.scopeAllowed) snap.scope = src.scope ?? 'item'
  return snap
}

function save() {
  if (!valid.value) return
  const snap = snapshot()
  if (!original) return emit('save', snap)
  // Only send keys that changed; clearing a value sends null. The server's stale values for
  // irrelevant keys are compared against the normalised original, so they are not resent.
  const changed: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(snap)) {
    if (JSON.stringify(v) !== JSON.stringify(original[k])) changed[k] = v
  }
  emit('save', changed)
}
</script>

<template>
  <form class="field-editor" @submit.prevent="save">
    <label>Label
      <InputText data-test="label" :model-value="form.label" @update:model-value="onLabel" />
    </label>
    <label>Key
      <InputText data-test="key" :model-value="form.key" :invalid="!!keyError" @update:model-value="onKey" />
      <small v-if="keyError" class="error" role="alert">{{ keyError }}</small>
    </label>
    <label>Type
      <Select v-model="form.type" data-test="type" :options="TYPES" option-label="label" option-value="value" />
    </label>
    <label v-if="scopeAllowed">Scope
      <Select v-model="form.scope" data-test="scope" :options="SCOPES" option-label="label" option-value="value" />
    </label>
    <label>Help text
      <InputText v-model="form.help_text" data-test="help" />
    </label>

    <template v-if="isNumber">
      <label>Unit (e.g. Ω, F, mAh)
        <InputText v-model="form.number_unit" data-test="number-unit" />
      </label>
      <label class="inline">
        <Checkbox v-model="form.number_si_prefixes" binary data-test="number-si" /> Allow SI prefixes (k, m, µ ...)
      </label>
      <div class="row">
        <label>Min <InputNumber v-model="form.min" data-test="number-min" :max-fraction-digits="12" /></label>
        <label>Max <InputNumber v-model="form.max" data-test="number-max" :max-fraction-digits="12" /></label>
        <label>Decimals <InputNumber v-model="form.decimals" data-test="number-decimals" :min="0" :max="12" /></label>
      </div>
    </template>

    <fieldset v-if="isSelect" class="options">
      <legend>Options</legend>
      <div v-for="(o, i) in form.options" :key="i" class="row">
        <InputText v-model="o.value" :data-test="`option-value-${i}`" placeholder="Value" aria-label="Option value" />
        <InputText v-model="o.label" :data-test="`option-label-${i}`" placeholder="Label" aria-label="Option label" />
        <InputText v-model="o.sku_code" :data-test="`option-sku-${i}`" placeholder="SKU code" aria-label="Option SKU code" />
        <Button type="button" icon="pi pi-trash" text severity="danger" aria-label="Remove option" @click="removeOption(i)" />
      </div>
      <Button type="button" data-test="add-option" label="Add option" icon="pi pi-plus" text @click="addOption" />
      <small v-if="!optionsValid" class="error" role="alert">Add at least one option with a value and a label.</small>
    </fieldset>

    <div class="row flags">
      <label class="inline"><Checkbox v-model="form.required" binary /> Required</label>
      <label class="inline"><Checkbox v-model="form.filterable" binary /> Filterable</label>
      <label class="inline"><Checkbox v-model="form.show_on_label" binary /> Show on label</label>
    </div>

    <div class="actions">
      <Button type="button" label="Cancel" text data-test="cancel" @click="emit('cancel')" />
      <Button type="submit" label="Save" data-test="save" :disabled="!valid" />
    </div>
  </form>
</template>

<style scoped>
.field-editor { display: flex; flex-direction: column; gap: 0.75rem; }
.field-editor label { display: flex; flex-direction: column; gap: 0.25rem; }
.field-editor label.inline { flex-direction: row; align-items: center; gap: 0.5rem; }
.row { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: flex-end; }
.flags { gap: 1rem; }
.options { border: 1px solid var(--p-content-border-color); border-radius: 6px; display: flex; flex-direction: column; gap: 0.5rem; }
.actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
