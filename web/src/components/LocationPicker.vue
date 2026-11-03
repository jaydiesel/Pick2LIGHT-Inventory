<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { apiFetch } from '@/api/client'
import type { LocationNode, StockRow } from '@/api/types'
import AppModal from '@/components/AppModal.vue'

const props = defineProps<{ open: boolean; title?: string; locations?: StockRow[] }>()
const emit = defineEmits<{ select: [id: number]; close: [] }>()

interface Flat {
  id: number
  label: string
  depth: number
}
const tree = ref<Flat[]>([])
const filter = ref('')

function flatten(nodes: LocationNode[], depth = 0, out: Flat[] = []): Flat[] {
  for (const n of nodes) {
    out.push({ id: n.id, label: `${n.name} (${n.code})`, depth })
    flatten(n.children ?? [], depth + 1, out)
  }
  return out
}

watch(
  () => props.open,
  async (open) => {
    if (open && !props.locations?.length) tree.value = flatten(await apiFetch<LocationNode[]>('/locations/tree'))
  },
  { immediate: true },
)

const shown = computed(() => {
  const f = filter.value.trim().toLowerCase()
  return f ? tree.value.filter((t) => t.label.toLowerCase().includes(f)) : tree.value
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
      <p v-if="!shown.length" class="muted">No locations yet — add them under Locations.</p>
      <button
        v-for="loc in shown"
        :key="loc.id"
        class="p2l-btn choice"
        :style="{ paddingLeft: `${0.9 + loc.depth * 1.1}rem` }"
        :data-test="`choose-${loc.id}`"
        @click="emit('select', loc.id)"
      >
        {{ loc.label }}
      </button>
    </div>
  </AppModal>
</template>

<style scoped>
.choice { text-align: left; }
</style>
