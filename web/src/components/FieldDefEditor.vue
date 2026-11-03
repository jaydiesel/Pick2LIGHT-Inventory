<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import { KEY_RE, slugKey } from '@/lib/keys'

export interface OptionDraft {
  value: string
  label?: string | null
  sku_code?: string | null
}
export interface FieldDraft {
  key: string
  label: string
  type: string
  scope?: string
  required?: boolean
  filterable?: boolean
  show_on_label?: boolean
  number_unit?: string | null
  number_si_prefixes?: boolean
  min?: number | null
  max?: number | null
  decimals?: number | null
  options: OptionDraft[]
  help_text?: string | null
}

const props = defineProps<{ trackingMode: string; initial?: Partial<FieldDraft> | null; hideScope?: boolean }>()
const emit = defineEmits<{ save: [draft: FieldDraft]; cancel: [] }>()

const TYPES = [
  ['text', 'Text'],
  ['long_text', 'Long text'],
  ['number', 'Number'],
  ['select', 'Choice'],
  ['multi_select', 'Multiple choice'],
  ['boolean', 'Yes / no'],
  ['date', 'Date'],
  ['url', 'Link'],
  ['file', 'File'],
]

function blank(): FieldDraft {
  return {
    key: '', label: '', type: 'text', scope: 'item', required: false, filterable: false, show_on_label: false,
    number_unit: null, number_si_prefixes: false, min: null, max: null, decimals: null, options: [], help_text: null,
  }
}

const draft = reactive<FieldDraft>({ ...blank(), ...(props.initial ?? {}), options: [...(props.initial?.options ?? [])] })
const existing = computed(() => !!props.initial?.key)
const keyTouched = ref(existing.value)

watch(
  () => draft.label,
  (label) => {
    if (!keyTouched.value) draft.key = slugKey(label)
  },
)

const isChoice = computed(() => draft.type === 'select' || draft.type === 'multi_select')
const showScope = computed(() => props.trackingMode === 'unit' && !props.hideScope)
const valid = computed(() => {
  if (!KEY_RE.test(draft.key) || !draft.label.trim()) return false
  if (isChoice.value) {
    const values = draft.options.map((o) => o.value.trim())
    if (!values.length || values.some((v) => !v) || new Set(values).size !== values.length) return false
  }
  return true
})

function addOption() {
  draft.options.push({ value: '', label: null, sku_code: null })
}

function save() {
  const out: FieldDraft = { ...draft, key: draft.key.trim(), label: draft.label.trim() }
  if (!isChoice.value) out.options = []
  else out.options = draft.options.map((o) => ({ value: o.value.trim(), label: o.label || null, sku_code: o.sku_code || null }))
  if (out.type !== 'number') Object.assign(out, { number_unit: null, number_si_prefixes: false, min: null, max: null, decimals: null })
  if (!showScope.value) delete out.scope
  emit('save', out)
}
</script>

<template>
  <div class="stack field-editor">
    <div class="grid-2">
      <div class="field">
        <label>Label</label>
        <input v-model="draft.label" class="p2l-input" data-test="label" />
      </div>
      <div class="field">
        <label>Key <span class="muted">(used in SKU patterns and labels)</span></label>
        <input v-model="draft.key" class="p2l-input" :disabled="existing" data-test="key" @input="keyTouched = true" />
      </div>
      <div class="field">
        <label>Type</label>
        <select v-model="draft.type" class="p2l-input" data-test="type">
          <option v-for="[v, l] in TYPES" :key="v" :value="v">{{ l }}</option>
        </select>
      </div>
      <div v-if="showScope" class="field">
        <label>Applies to</label>
        <select v-model="draft.scope" class="p2l-input" data-test="scope">
          <option value="item">The item (shared by all units)</option>
          <option value="unit">Each unit</option>
        </select>
      </div>
    </div>
    <div v-if="draft.type === 'number'" class="grid-2" data-test="unit-options">
      <div class="field">
        <label>Unit</label>
        <input v-model="draft.number_unit" class="p2l-input" placeholder="Ω, F, mAh, mm…" data-test="number-unit" />
      </div>
      <label class="row"><input v-model="draft.number_si_prefixes" type="checkbox" /> Allow SI prefixes (4.7k, 100n)</label>
      <div class="field"><label>Minimum</label><input v-model.number="draft.min" class="p2l-input" type="number" step="any" /></div>
      <div class="field"><label>Maximum</label><input v-model.number="draft.max" class="p2l-input" type="number" step="any" /></div>
      <div class="field"><label>Decimals shown</label><input v-model.number="draft.decimals" class="p2l-input" type="number" min="0" max="12" /></div>
    </div>
    <div v-if="isChoice" class="stack" data-test="options-table">
      <table class="plain">
        <thead><tr><th>Value</th><th>Label</th><th>SKU code</th><th /></tr></thead>
        <tbody>
          <tr v-for="(o, i) in draft.options" :key="i">
            <td><input v-model="o.value" class="p2l-input" :data-test="`option-value-${i}`" /></td>
            <td><input v-model="o.label" class="p2l-input" /></td>
            <td><input v-model="o.sku_code" class="p2l-input" /></td>
            <td><button class="p2l-btn" aria-label="Remove option" @click="draft.options.splice(i, 1)"><i class="pi pi-times" /></button></td>
          </tr>
        </tbody>
      </table>
      <div><button class="p2l-btn" data-test="add-option" @click="addOption">Add choice</button></div>
    </div>
    <div class="row">
      <label class="row"><input v-model="draft.required" type="checkbox" /> Required</label>
      <label class="row"><input v-model="draft.filterable" type="checkbox" /> Filterable</label>
      <label class="row"><input v-model="draft.show_on_label" type="checkbox" /> Show on labels</label>
    </div>
    <div class="field">
      <label>Help text</label>
      <input v-model="draft.help_text" class="p2l-input" />
    </div>
    <div class="row">
      <span class="spacer" />
      <button class="p2l-btn" @click="emit('cancel')">Cancel</button>
      <button class="p2l-btn primary" :disabled="!valid" data-test="save" @click="save">Save field</button>
    </div>
  </div>
</template>
