<script setup lang="ts">
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiFetch } from '../api/client'
import type { components } from '../api/schema'
import LocationTree from '../components/LocationTree.vue'
import LocationTypesDialog from '../components/LocationTypesDialog.vue'
import { useApiToast } from '../composables/useApiToast'

type LocationNode = components['schemas']['LocationNode']

const router = useRouter()
const notify = useApiToast()

const tree = ref<LocationNode[]>([])
const newRootName = ref('')
const showTypes = ref(false)

/** The node an action dialog is currently open for. */
const adding = ref<LocationNode | null>(null)
const renaming = ref<LocationNode | null>(null)
const moving = ref<LocationNode | null>(null)
const deleting = ref<LocationNode | null>(null)
const dialogName = ref('')

async function load() {
  try {
    tree.value = await apiFetch<LocationNode[]>('/locations/tree')
  } catch (e) {
    notify.error(e, 'Could not load locations')
  }
}
onMounted(load)

/** Run a mutation, reload the tree on success, toast the server's message on failure. */
async function mutate(action: () => Promise<unknown>): Promise<boolean> {
  try {
    await action()
    await load()
    return true
  } catch (e) {
    notify.error(e)
    return false
  }
}

async function addRoot() {
  const name = newRootName.value.trim()
  if (!name) return
  if (await mutate(() => apiFetch('/locations', { method: 'POST', json: { name } }))) newRootName.value = ''
}

function openAdd(node: LocationNode) {
  dialogName.value = ''
  adding.value = node
}
async function confirmAdd() {
  const parent = adding.value
  const name = dialogName.value.trim()
  if (!parent || !name) return
  adding.value = null
  await mutate(() => apiFetch('/locations', { method: 'POST', json: { name, parent_id: parent.id } }))
}

function openRename(node: LocationNode) {
  dialogName.value = node.name
  renaming.value = node
}
async function confirmRename() {
  const node = renaming.value
  const name = dialogName.value.trim()
  if (!node || !name) return
  renaming.value = null
  await mutate(() => apiFetch(`/locations/${node.id}`, { method: 'PATCH', json: { name } }))
}

function without(nodes: LocationNode[], id: number): LocationNode[] {
  return nodes.filter((n) => n.id !== id).map((n) => ({ ...n, children: without(n.children, id) }))
}
/** Move targets exclude the node itself and therefore its whole subtree. */
const moveTargets = computed(() => (moving.value ? without(tree.value, moving.value.id) : []))

async function moveTo(parentId: number | null) {
  const node = moving.value
  if (!node) return
  moving.value = null
  await mutate(() => apiFetch(`/locations/${node.id}/move`, { method: 'POST', json: { parent_id: parentId } }))
}

async function confirmDelete() {
  const node = deleting.value
  if (!node) return
  deleting.value = null
  await mutate(() => apiFetch(`/locations/${node.id}`, { method: 'DELETE' }))
}
</script>

<template>
  <section class="locations">
    <header class="bar">
      <h1>Locations</h1>
      <Button label="Location types" icon="pi pi-tags" text data-test="manage-types" @click="showTypes = true" />
    </header>

    <form class="add-root" @submit.prevent="addRoot">
      <InputText v-model="newRootName" placeholder="New top-level location" aria-label="New top-level location" data-test="new-root" />
      <Button type="submit" label="Add" :disabled="!newRootName.trim()" data-test="add-root" />
    </form>

    <LocationTree :nodes="tree" selectable @select="router.push(`/locations/${$event}`)">
      <template #actions="{ node }">
        <Button icon="pi pi-plus" text size="small" :aria-label="`Add child to ${node.name}`" :data-test="`add-${node.id}`" @click="openAdd(node)" />
        <Button icon="pi pi-pencil" text size="small" :aria-label="`Rename ${node.name}`" :data-test="`rename-${node.id}`" @click="openRename(node)" />
        <Button icon="pi pi-arrows-alt" text size="small" :aria-label="`Move ${node.name}`" :data-test="`move-${node.id}`" @click="moving = node" />
        <Button icon="pi pi-trash" text size="small" severity="danger" :aria-label="`Delete ${node.name}`" :data-test="`delete-${node.id}`" @click="deleting = node" />
      </template>
    </LocationTree>
    <p v-if="!tree.length" class="muted">No locations yet.</p>

    <Dialog :visible="!!adding" modal :header="`Add child to ${adding?.name ?? ''}`" :style="{ width: '24rem' }" @update:visible="adding = null">
      <form @submit.prevent="confirmAdd"><InputText v-model="dialogName" aria-label="Name" data-test="add-name" class="full" autofocus /></form>
      <template #footer>
        <Button label="Cancel" text @click="adding = null" />
        <Button label="Add" :disabled="!dialogName.trim()" data-test="add-confirm" @click="confirmAdd" />
      </template>
    </Dialog>

    <Dialog :visible="!!renaming" modal header="Rename location" :style="{ width: '24rem' }" @update:visible="renaming = null">
      <form @submit.prevent="confirmRename"><InputText v-model="dialogName" aria-label="Name" data-test="rename-name" class="full" autofocus /></form>
      <template #footer>
        <Button label="Cancel" text @click="renaming = null" />
        <Button label="Rename" :disabled="!dialogName.trim()" data-test="rename-confirm" @click="confirmRename" />
      </template>
    </Dialog>

    <Dialog :visible="!!moving" modal :header="`Move ${moving?.name ?? ''} to…`" :style="{ width: '28rem' }" @update:visible="moving = null">
      <Button label="Top level" text data-test="move-root" @click="moveTo(null)" />
      <LocationTree :nodes="moveTargets" selectable @select="moveTo" />
      <template #footer><Button label="Cancel" text @click="moving = null" /></template>
    </Dialog>

    <Dialog :visible="!!deleting" modal header="Delete location" :style="{ width: '24rem' }" @update:visible="deleting = null">
      <p>Delete “{{ deleting?.name }}”? It can be restored from the trash.</p>
      <template #footer>
        <Button label="Cancel" text @click="deleting = null" />
        <Button label="Delete" severity="danger" data-test="confirm-delete" @click="confirmDelete" />
      </template>
    </Dialog>

    <LocationTypesDialog v-if="showTypes" @close="showTypes = false" @changed="load" />
  </section>
</template>

<style scoped>
.bar { display: flex; justify-content: space-between; align-items: center; }
.add-root { display: flex; gap: 0.5rem; margin: 0.5rem 0 1rem; }
.add-root :deep(input) { flex: 1; max-width: 24rem; }
.full { width: 100%; }
</style>
