<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { ref, watch } from 'vue'

import { ApiError, apiFetch } from '@/api/client'
import type { LocationNode, SearchPage } from '@/api/types'
import AppModal from '@/components/AppModal.vue'

const props = defineProps<{ open: boolean; code: string }>()
const emit = defineEmits<{ close: []; attached: [] }>()
const toast = useToast()
const query = ref('')
const unitCode = ref('')
const hits = ref<SearchPage['hits']>([])
const locations = ref<{ id: number; name: string; code: string }[]>([])
const error = ref('')

function flatten(nodes: LocationNode[], out: { id: number; name: string; code: string }[] = []) {
  for (const n of nodes) {
    out.push({ id: n.id, name: n.name, code: n.code })
    flatten(n.children ?? [], out)
  }
  return out
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      query.value = ''
      unitCode.value = ''
      hits.value = []
      locations.value = []
      error.value = ''
    }
  },
)

async function search() {
  const q = query.value.trim()
  if (!q) return
  hits.value = (await apiFetch<SearchPage>(`/search?q=${encodeURIComponent(q)}&limit=10`)).hits
  const tree = flatten(await apiFetch<LocationNode[]>('/locations/tree'))
  locations.value = tree.filter((l) => l.name.toLowerCase().includes(q.toLowerCase())).slice(0, 10)
}

async function attach(target_type: 'item' | 'unit' | 'location', target_id: number) {
  error.value = ''
  try {
    const kind = target_type === 'location' ? 'custom' : 'manufacturer'
    await apiFetch('/barcodes', { method: 'POST', json: { code: props.code, target_type, target_id, kind } })
    await apiFetch(`/scan/unknown/${encodeURIComponent(props.code)}`, { method: 'DELETE' })
    toast.add({ severity: 'success', summary: 'Code attached', detail: props.code, life: 3000 })
    emit('attached')
    emit('close')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e)
  }
}

async function attachToUnit() {
  error.value = ''
  try {
    const bc = await apiFetch<{ target_type: string; target_id: number }>(`/barcodes/${encodeURIComponent(unitCode.value.trim())}`)
    if (bc.target_type !== 'unit') throw new Error('That code is not a unit code')
    await attach('unit', bc.target_id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}
</script>

<template>
  <AppModal :open="open" :title="`Attach ${code}`" wide @close="emit('close')">
    <div class="stack">
      <form class="row" @submit.prevent="search">
        <input v-model="query" class="p2l-input spacer" placeholder="Find an item or location" data-test="attach-query" />
        <button class="p2l-btn" type="submit">Search</button>
      </form>
      <table v-if="hits.length || locations.length" class="plain">
        <tbody>
          <tr v-for="h in hits" :key="`i${h.id}`">
            <td>Item</td>
            <td>{{ h.name }} <span class="muted">{{ h.sku }}</span></td>
            <td><button class="p2l-btn" :data-test="`attach-item-${h.id}`" @click="attach('item', h.id)">Attach</button></td>
          </tr>
          <tr v-for="l in locations" :key="`l${l.id}`">
            <td>Location</td>
            <td>{{ l.name }} <span class="muted">{{ l.code }}</span></td>
            <td><button class="p2l-btn" @click="attach('location', l.id)">Attach</button></td>
          </tr>
        </tbody>
      </table>
      <form class="row" @submit.prevent="attachToUnit">
        <input v-model="unitCode" class="p2l-input spacer" placeholder="…or type a unit code (e.g. C0042)" />
        <button class="p2l-btn" type="submit" :disabled="!unitCode.trim()">Attach to unit</button>
      </form>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </div>
  </AppModal>
</template>
