<script setup lang="ts">
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import { onMounted, ref } from 'vue'
import { apiFetch } from '../api/client'
import type { components } from '../api/schema'
import { useApiToast } from '../composables/useApiToast'

type LocationTypeOut = components['schemas']['LocationTypeOut']

const emit = defineEmits<{ close: []; changed: [] }>()
const notify = useApiToast()

const types = ref<LocationTypeOut[]>([])
const names = ref<Record<number, string>>({})
const newName = ref('')

async function load() {
  try {
    types.value = await apiFetch<LocationTypeOut[]>('/location-types')
    names.value = Object.fromEntries(types.value.map((t) => [t.id, t.name]))
  } catch (e) {
    notify.error(e, 'Could not load location types')
  }
}
onMounted(load)

async function run(action: () => Promise<unknown>) {
  try {
    await action()
    await load()
    emit('changed')
  } catch (e) {
    notify.error(e)
  }
}

const add = () => {
  const name = newName.value.trim()
  if (!name) return
  void run(async () => {
    await apiFetch('/location-types', { method: 'POST', json: { name } })
    newName.value = ''
  })
}
const rename = (t: LocationTypeOut) => {
  const name = (names.value[t.id] ?? '').trim()
  if (name && name !== t.name) void run(() => apiFetch(`/location-types/${t.id}`, { method: 'PATCH', json: { name } }))
}
const remove = (t: LocationTypeOut) => void run(() => apiFetch(`/location-types/${t.id}`, { method: 'DELETE' }))
</script>

<template>
  <Dialog :visible="true" modal header="Location types" :style="{ width: '28rem' }" @update:visible="emit('close')">
    <ul class="types">
      <li v-for="t in types" :key="t.id">
        <InputText v-model="names[t.id]" :data-test="`type-name-${t.id}`" :aria-label="`Name of ${t.name}`" @blur="rename(t)" @keydown.enter="rename(t)" />
        <Button icon="pi pi-trash" text severity="danger" :aria-label="`Delete ${t.name}`" :data-test="`type-delete-${t.id}`" @click="remove(t)" />
      </li>
    </ul>
    <form class="add" @submit.prevent="add">
      <InputText v-model="newName" placeholder="New type" aria-label="New type name" data-test="type-new" />
      <Button type="submit" label="Add" :disabled="!newName.trim()" data-test="type-add" />
    </form>
    <template #footer><Button label="Close" text @click="emit('close')" /></template>
  </Dialog>
</template>

<style scoped>
.types { list-style: none; margin: 0 0 1rem; padding: 0; display: grid; gap: 0.5rem; }
.types li, .add { display: flex; gap: 0.5rem; }
.types li :deep(input) { flex: 1; }
.add :deep(input) { flex: 1; }
</style>
