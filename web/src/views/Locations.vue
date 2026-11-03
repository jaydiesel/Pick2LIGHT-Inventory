<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError, apiFetch } from '@/api/client'
import type { LocationNode, LocationTypeOut } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import LocationPicker from '@/components/LocationPicker.vue'
import LocationTree from '@/components/LocationTree.vue'

const router = useRouter()
const nodes = ref<LocationNode[]>([])
const types = ref<LocationTypeOut[]>([])
const error = ref('')
const adding = ref<{ parent: LocationNode | null } | null>(null)
const newName = ref('')
const newType = ref('')
const moving = ref<LocationNode | null>(null)
const typesOpen = ref(false)
const newTypeName = ref('')

async function load() {
  ;[nodes.value, types.value] = await Promise.all([
    apiFetch<LocationNode[]>('/locations/tree'),
    apiFetch<LocationTypeOut[]>('/location-types'),
  ])
}

function fail(e: unknown) {
  error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
}

async function add() {
  error.value = ''
  try {
    await apiFetch('/locations', {
      method: 'POST',
      json: { name: newName.value.trim(), parent_id: adding.value?.parent?.id ?? null, location_type_id: newType.value ? Number(newType.value) : null },
    })
    adding.value = null
    newName.value = ''
    await load()
  } catch (e) {
    fail(e)
  }
}

async function rename(n: LocationNode) {
  const name = window.prompt('New name', n.name)
  if (!name || name === n.name) return
  await apiFetch(`/locations/${n.id}`, { method: 'PATCH', json: { name } }).catch(fail)
  await load()
}

async function moveTo(parentId: number | null) {
  const n = moving.value
  moving.value = null
  if (!n) return
  error.value = ''
  try {
    await apiFetch(`/locations/${n.id}/move`, { method: 'POST', json: { parent_id: parentId } })
    await load()
  } catch (e) {
    fail(e)
  }
}

async function remove(n: LocationNode) {
  if (!window.confirm(`Delete "${n.name}"? It goes to the trash.`)) return
  error.value = ''
  try {
    await apiFetch(`/locations/${n.id}`, { method: 'DELETE' })
    await load()
  } catch (e) {
    fail(e)
  }
}

async function addType() {
  try {
    await apiFetch('/location-types', { method: 'POST', json: { name: newTypeName.value.trim() } })
    newTypeName.value = ''
    await load()
  } catch (e) {
    fail(e)
  }
}

async function removeType(t: LocationTypeOut) {
  try {
    await apiFetch(`/location-types/${t.id}`, { method: 'DELETE' })
    await load()
  } catch (e) {
    fail(e)
  }
}

onMounted(load)
</script>

<template>
  <div class="row">
    <h1 class="spacer">Locations</h1>
    <button class="p2l-btn" @click="typesOpen = true">Location types</button>
    <button class="p2l-btn primary" data-test="add-root" @click="adding = { parent: null }">Add location</button>
  </div>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <section class="card">
    <p v-if="!nodes.length" class="muted">No locations yet. Start with a room or a cabinet.</p>
    <LocationTree :nodes="nodes" @select="(id) => router.push(`/locations/${id}`)">
      <template #actions="{ node }">
        <button class="p2l-btn" title="Add inside" @click="adding = { parent: node }"><i class="pi pi-plus" /></button>
        <button class="p2l-btn" title="Rename" @click="rename(node)"><i class="pi pi-pencil" /></button>
        <button class="p2l-btn" title="Move" @click="moving = node"><i class="pi pi-arrows-alt" /></button>
        <button class="p2l-btn danger" title="Delete" :data-test="`delete-${node.id}`" @click="remove(node)"><i class="pi pi-trash" /></button>
      </template>
    </LocationTree>
  </section>

  <AppModal :open="!!adding" :title="adding?.parent ? `Add inside ${adding.parent.name}` : 'Add location'" @close="adding = null">
    <form class="stack" @submit.prevent="add">
      <input v-model="newName" class="p2l-input" placeholder="Name, e.g. Drawer A1" data-test="new-location-name" />
      <select v-model="newType" class="p2l-input">
        <option value="">Type (optional)</option>
        <option v-for="t in types" :key="t.id" :value="String(t.id)">{{ t.name }}</option>
      </select>
      <button class="p2l-btn primary" :disabled="!newName.trim()">Add</button>
    </form>
  </AppModal>

  <LocationPicker
    :open="!!moving"
    :title="`Move ${moving?.name ?? ''} into…`"
    allow-root
    @select="moveTo"
    @root="moveTo(null)"
    @close="moving = null"
  />

  <AppModal :open="typesOpen" title="Location types" @close="typesOpen = false">
    <div class="stack">
      <div v-for="t in types" :key="t.id" class="row">
        <span class="spacer">{{ t.name }}</span>
        <button class="p2l-btn danger" @click="removeType(t)">Remove</button>
      </div>
      <form class="row" @submit.prevent="addType">
        <input v-model="newTypeName" class="p2l-input spacer" placeholder="New type" />
        <button class="p2l-btn" :disabled="!newTypeName.trim()">Add</button>
      </form>
    </div>
  </AppModal>
</template>
