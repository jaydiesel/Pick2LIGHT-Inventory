<script setup lang="ts">
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiFetch } from '../api/client'
import type { components } from '../api/schema'
import CategoryTree from '../components/CategoryTree.vue'
import { useApiToast } from '../composables/useApiToast'

type CategoryOut = components['schemas']['CategoryOut']
type PackSummary = components['schemas']['PackSummary']
type PackResult = components['schemas']['PackResult']

const router = useRouter()
const notify = useApiToast()

const categories = ref<CategoryOut[]>([])
const packs = ref<PackSummary[]>([])
const newName = ref('')
const newParent = ref<number | null>(null)
const packId = ref<string | null>(null)
const packParent = ref<number | null>(null)
const importInput = ref<HTMLInputElement | null>(null)

const parentOptions = computed(() => [
  { id: null, label: 'Top level' },
  ...categories.value.map((c) => ({ id: c.id, label: [...c.path.map((p) => p.name), c.name].join(' / ') })),
])

async function load() {
  try {
    ;[categories.value, packs.value] = await Promise.all([
      apiFetch<CategoryOut[]>('/categories'),
      apiFetch<PackSummary[]>('/packs'),
    ])
  } catch (e) {
    notify.error(e, 'Could not load categories')
  }
}
onMounted(load)

async function create() {
  const name = newName.value.trim()
  if (!name) return
  try {
    const created = await apiFetch<CategoryOut>('/categories', {
      method: 'POST',
      json: { name, ...(newParent.value != null ? { parent_id: newParent.value } : {}) },
    })
    newName.value = ''
    await router.push(`/categories/${created.id}`)
  } catch (e) {
    notify.error(e)
  }
}

function reportPack(r: PackResult) {
  notify.success(`Pack applied: ${r.created} created, ${r.skipped} skipped`)
}

async function applyPack() {
  if (!packId.value) return
  try {
    reportPack(
      await apiFetch<PackResult>('/packs/apply', {
        method: 'POST',
        json: { pack_id: packId.value, ...(packParent.value != null ? { parent_id: packParent.value } : {}) },
      }),
    )
    await load()
  } catch (e) {
    notify.error(e)
  }
}

async function importPack(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const body = new FormData()
  body.append('file', file)
  try {
    reportPack(await apiFetch<PackResult>('/packs/import', { method: 'POST', body }))
    await load()
  } catch (e) {
    notify.error(e)
  } finally {
    input.value = ''
  }
}
</script>

<template>
  <div class="categories">
    <h1>Categories</h1>
    <div class="layout">
      <section class="card">
        <CategoryTree :categories="categories" @select="router.push(`/categories/${$event}`)" />
        <p v-if="!categories.length" class="muted">No categories yet.</p>
      </section>

      <div class="side">
        <form class="card" @submit.prevent="create">
          <h2>New category</h2>
          <InputText v-model="newName" data-test="new-name" placeholder="Name" aria-label="Category name" />
          <Select v-model="newParent" :options="parentOptions" option-label="label" option-value="id" aria-label="Parent category" />
          <Button type="submit" label="Create" data-test="create" :disabled="!newName.trim()" />
        </form>

        <section class="card">
          <h2>Starter packs</h2>
          <Select v-model="packId" :options="packs" option-label="name" option-value="id" placeholder="Choose a starter pack" data-test="pack-select" />
          <Select v-model="packParent" :options="parentOptions" option-label="label" option-value="id" aria-label="Apply under" />
          <Button label="Apply starter pack" data-test="apply-pack" :disabled="!packId" @click="applyPack" />
          <Button label="Import pack" icon="pi pi-upload" severity="secondary" data-test="import-pack" @click="importInput?.click()" />
          <input ref="importInput" type="file" accept="application/json,.json" hidden data-test="import-file" @change="importPack" />
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.layout { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 1rem; align-items: start; }
@media (max-width: 800px) { .layout { grid-template-columns: 1fr; } }
.card { border: 1px solid var(--p-content-border-color); border-radius: 8px; padding: 0.75rem 1rem; display: flex; flex-direction: column; gap: 0.5rem; }
.card h2 { margin: 0; font-size: 1.1rem; }
.side { display: flex; flex-direction: column; gap: 1rem; }
</style>
