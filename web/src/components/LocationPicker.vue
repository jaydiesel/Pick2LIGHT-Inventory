<script setup lang="ts">
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import { computed, onMounted, ref } from 'vue'
import { apiFetch } from '../api/client'
import type { components } from '../api/schema'

type StockRow = components['schemas']['StockRow']
type LocationRef = components['schemas']['LocationRef']
type LocationNode = components['schemas']['LocationNode']

const props = defineProps<{
  /** Candidate locations from the scan result; when empty the full location tree is offered. */
  locations?: (StockRow | LocationRef)[] | null
  header?: string
}>()
const emit = defineEmits<{ select: [locationId: number]; cancel: [] }>()

interface Choice {
  id: number
  label: string
  detail?: string
}

const tree = ref<LocationNode[]>([])
const loadError = ref('')

function flatten(nodes: LocationNode[], depth = 0): Choice[] {
  return nodes.flatMap((n) => [
    { id: n.id, label: `${' '.repeat(depth)}${n.name}`, detail: n.code },
    ...flatten(n.children, depth + 1),
  ])
}

const fromScan = computed<Choice[]>(() =>
  (props.locations ?? []).map((l) =>
    'location_id' in l
      ? { id: l.location_id, label: l.location_path.map((p) => p.name).join(' / '), detail: `qty ${l.quantity}` }
      : { id: l.id, label: l.name, detail: l.code },
  ),
)
const choices = computed(() => (fromScan.value.length ? fromScan.value : flatten(tree.value)))

onMounted(async () => {
  if (fromScan.value.length) return
  try {
    tree.value = await apiFetch<LocationNode[]>('/locations/tree')
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : 'Could not load locations'
  }
})
</script>

<template>
  <Dialog :visible="true" modal :header="header ?? 'Choose a location'" :style="{ width: '28rem' }" @update:visible="emit('cancel')">
    <p v-if="loadError" role="alert">{{ loadError }}</p>
    <ul class="choices">
      <li v-for="c in choices" :key="c.id">
        <Button :label="c.label" :data-test="`loc-${c.id}`" text class="choice" @click="emit('select', c.id)">
          <template #default>
            <span class="name">{{ c.label }}</span>
            <small v-if="c.detail" class="muted">{{ c.detail }}</small>
          </template>
        </Button>
      </li>
    </ul>
    <p v-if="!choices.length && !loadError" class="muted">No locations yet.</p>
    <template #footer><Button label="Cancel" text @click="emit('cancel')" /></template>
  </Dialog>
</template>

<style scoped>
.choices { list-style: none; margin: 0; padding: 0; max-height: 50vh; overflow-y: auto; }
.choice { width: 100%; justify-content: space-between; }
</style>
