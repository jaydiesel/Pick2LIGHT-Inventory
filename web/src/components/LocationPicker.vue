<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { apiFetch } from '@/api/client'
import type { LocationNode, StockRow } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import LocationTree from '@/components/LocationTree.vue'

const props = defineProps<{ open: boolean; title?: string; locations?: StockRow[]; allowRoot?: boolean }>()
const emit = defineEmits<{ select: [id: number]; root: []; close: [] }>()

const tree = ref<LocationNode[]>([])
const filter = ref('')

watch(
  () => props.open,
  async (open) => {
    if (open && !props.locations?.length) tree.value = await apiFetch<LocationNode[]>('/locations/tree')
  },
  { immediate: true },
)

function prune(nodes: LocationNode[], f: string): LocationNode[] {
  const out: LocationNode[] = []
  for (const n of nodes) {
    const kids = prune(n.children ?? [], f)
    if (kids.length || `${n.name} ${n.code}`.toLowerCase().includes(f)) out.push({ ...n, children: kids })
  }
  return out
}

const shown = computed(() => {
  const f = filter.value.trim().toLowerCase()
  return f ? prune(tree.value, f) : tree.value
})
</script>

<template>
  <AppModal :open="open" :title="title || 'Choose a location'" @close="emit('close')">
    <div v-if="locations?.length" class="stack">
      <button
        v-for="row in locations"
        :key="row.location_id"
        class="p2l-btn choice"
        :data-test="`choose-${row.location_id}`"
        @click="emit('select', row.location_id)"
      >
        {{ row.location_path.map((p) => p.name).join(' › ') }} <span class="muted">— {{ row.quantity }}</span>
      </button>
    </div>
    <div v-else class="stack">
      <input v-model="filter" class="p2l-input" placeholder="Filter locations" data-test="location-filter" />
      <button v-if="allowRoot" class="p2l-btn choice" data-test="choose-root" @click="emit('root')">Top level (no parent)</button>
      <p v-if="!shown.length" class="muted">No locations yet — add them under Locations.</p>
      <LocationTree :nodes="shown" @select="(id) => emit('select', id)" />
    </div>
  </AppModal>
</template>

<style scoped>
.choice { text-align: left; }
</style>
