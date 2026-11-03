<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { ApiError, apiBlob, apiFetch } from '@/api/client'
import type { LabelTemplateOut, SheetSpec } from '@/api/types'

const templates = ref<LabelTemplateOut[]>([])
const sheets = ref<SheetSpec[]>([])
const selectedId = ref<number | null>(null)
const layoutText = ref('')
const meta = ref({ name: '', width_mm: 50, height_mm: 30, dpi: 203 })
const previewId = ref<number | null>(null)
const previewUrl = ref('')
const error = ref('')
const saved = ref('')

const selected = computed(() => templates.value.find((t) => t.id === selectedId.value) ?? null)

async function load() {
  ;[templates.value, sheets.value] = await Promise.all([apiFetch<LabelTemplateOut[]>('/label-templates'), apiFetch<SheetSpec[]>('/label-sheets')])
  if (selectedId.value === null && templates.value.length) selectedId.value = templates.value[0].id
}

watch(selected, (t) => {
  if (!t) return
  layoutText.value = JSON.stringify(t.layout, null, 2)
  meta.value = { name: t.name, width_mm: t.width_mm, height_mm: t.height_mm, dpi: t.dpi }
  previewUrl.value = ''
  error.value = ''
})

function parse(): unknown[] | null {
  try {
    const v = JSON.parse(layoutText.value)
    if (!Array.isArray(v)) throw new Error('The layout must be a JSON list of elements')
    return v
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    return null
  }
}

function fail(e: unknown) {
  error.value = e instanceof ApiError ? Object.entries(e.fields).map(([k, v]) => `${k}: ${v}`).join('; ') || e.message : String(e)
}

async function save() {
  error.value = ''
  saved.value = ''
  const layout = parse()
  if (!layout || !selected.value) return
  try {
    await apiFetch(`/label-templates/${selected.value.id}`, { method: 'PATCH', json: { ...meta.value, layout } })
    saved.value = 'Saved'
    await load()
  } catch (e) {
    fail(e)
  }
}

async function duplicate() {
  const t = selected.value
  if (!t) return
  try {
    const copy = await apiFetch<LabelTemplateOut>('/label-templates', {
      method: 'POST',
      json: { name: `${t.name} (copy)`, width_mm: t.width_mm, height_mm: t.height_mm, dpi: t.dpi, target: t.target, layout: t.layout },
    })
    await load()
    selectedId.value = copy.id
  } catch (e) {
    fail(e)
  }
}

async function remove() {
  if (!selected.value || !window.confirm(`Delete the template "${selected.value.name}"?`)) return
  await apiFetch(`/label-templates/${selected.value.id}`, { method: 'DELETE' }).catch(fail)
  selectedId.value = null
  await load()
}

async function preview() {
  error.value = ''
  if (!selected.value || !previewId.value) return
  try {
    const blob = await apiBlob('/labels/preview', {
      method: 'POST',
      json: { template_id: selected.value.id, target_type: selected.value.target, id: previewId.value },
    })
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = URL.createObjectURL(blob)
  } catch (e) {
    fail(e)
  }
}

onMounted(load)
</script>

<template>
  <h1>Labels</h1>
  <div class="grid-2">
    <section class="card stack">
      <h2>Templates</h2>
      <button
        v-for="t in templates"
        :key="t.id"
        :class="['p2l-btn', { primary: t.id === selectedId }]"
        style="text-align: left"
        @click="selectedId = t.id"
      >
        {{ t.name }} <span class="muted">— {{ t.target }}, {{ t.width_mm }}×{{ t.height_mm }} mm</span>
      </button>
      <h2>Sticker sheets</h2>
      <p v-for="s in sheets" :key="s.id" class="muted">{{ s.name }}</p>
      <p class="muted">Print labels from any item, unit or location page. The PDF opens in a new tab; print it on a label printer or a sticker sheet.</p>
    </section>
    <section v-if="selected" class="card stack">
      <div class="grid-2">
        <div class="field"><label>Name</label><input v-model="meta.name" class="p2l-input" /></div>
        <div class="field"><label>Size (mm)</label><span class="row"><input v-model.number="meta.width_mm" class="p2l-input" type="number" style="width: 5rem" /> × <input v-model.number="meta.height_mm" class="p2l-input" type="number" style="width: 5rem" /></span></div>
      </div>
      <div class="field">
        <label>Layout (JSON)</label>
        <textarea v-model="layoutText" class="p2l-input mono" rows="16" spellcheck="false" data-test="layout" />
        <span class="muted">Elements: barcode (qr, datamatrix, code128, ean13), text, image, line, box. Text values use tokens like {name}, {sku}, {unit_code}, {label_line}, {summary_line}, {attrs.resistance}, {location.path}.</span>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="saved" class="muted">{{ saved }}</p>
      <div class="row">
        <button class="p2l-btn danger" @click="remove">Delete</button>
        <button class="p2l-btn" @click="duplicate">Duplicate</button>
        <span class="spacer" />
        <button class="p2l-btn primary" data-test="save-template" @click="save">Save</button>
      </div>
      <div class="row">
        <input v-model.number="previewId" class="p2l-input" type="number" min="1" :placeholder="`${selected.target} id to preview`" />
        <button class="p2l-btn" :disabled="!previewId" @click="preview">Preview</button>
      </div>
      <img v-if="previewUrl" :src="previewUrl" alt="Label preview" class="preview" />
    </section>
  </div>
</template>

<style scoped>
.mono { font-family: ui-monospace, monospace; font-size: .85rem; }
.preview { border: 1px solid var(--p2l-border); max-width: 100%; image-rendering: pixelated; background: #fff; }
</style>
