<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError, apiFetch } from '@/api/client'
import type { CategoryOut, PackResult, PackSummary } from '@/api/types'
import CategoryTree from '@/components/CategoryTree.vue'

const router = useRouter()
const toast = useToast()
const categories = ref<CategoryOut[]>([])
const packs = ref<PackSummary[]>([])
const name = ref('')
const parent = ref('')
const error = ref('')

async function load() {
  ;[categories.value, packs.value] = await Promise.all([apiFetch<CategoryOut[]>('/categories'), apiFetch<PackSummary[]>('/packs')])
}

async function create() {
  error.value = ''
  try {
    const c = await apiFetch<CategoryOut>('/categories', {
      method: 'POST',
      json: { name: name.value.trim(), parent_id: parent.value ? Number(parent.value) : null },
    })
    router.push(`/categories/${c.id}`)
  } catch (e) {
    error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
  }
}

function report(r: PackResult) {
  toast.add({ severity: 'success', summary: 'Pack applied', detail: `${r.created} created, ${r.skipped} already there`, life: 4000 })
}

async function applyPack(id: string) {
  report(await apiFetch<PackResult>('/packs/apply', { method: 'POST', json: { pack_id: id } }))
  await load()
}

async function importPack(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  const body = new FormData()
  body.append('file', file)
  try {
    report(await apiFetch<PackResult>('/packs/import', { method: 'POST', body }))
    await load()
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Import failed', detail: e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e) })
  }
}

onMounted(load)
</script>

<template>
  <h1>Categories</h1>
  <div class="grid-2">
    <section class="card">
      <p v-if="!categories.length" class="muted">No categories yet — create one or apply a starter pack.</p>
      <CategoryTree :categories="categories" @select="(id) => router.push(`/categories/${id}`)" />
    </section>
    <div>
      <form class="card stack" @submit.prevent="create">
        <h2>New category</h2>
        <input v-model="name" class="p2l-input" placeholder="Name" data-test="new-name" />
        <select v-model="parent" class="p2l-input">
          <option value="">— top level —</option>
          <option v-for="c in categories" :key="c.id" :value="String(c.id)">{{ c.path.map((p) => p.name).join(' › ') }}</option>
        </select>
        <p v-if="error" class="error">{{ error }}</p>
        <button class="p2l-btn primary" type="submit" :disabled="!name.trim()">Create</button>
      </form>
      <section class="card stack">
        <h2>Starter packs</h2>
        <div v-for="p in packs" :key="p.id" class="row">
          <span class="spacer"><b>{{ p.name }}</b> <span class="muted">{{ p.description }}</span></span>
          <button class="p2l-btn" @click="applyPack(p.id)">Apply</button>
        </div>
        <label class="field">
          <span>Import a pack file (.json)</span>
          <input type="file" accept="application/json,.json" @change="importPack" />
        </label>
      </section>
    </div>
  </div>
</template>
