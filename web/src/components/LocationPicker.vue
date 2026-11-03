<script setup lang="ts">
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import { computed, onMounted, ref } from 'vue'
import { apiFetch } from '../api/client'
import type { components } from '../api/schema'
import LocationTree from './LocationTree.vue'

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

const fromScan = computed<Choice[]>(() =>
  (props.locations ?? []).map((l) =>
    'location_id' in l
      ? { id: l.location_id, label: l.location_path.map((p) => p.name).join(' / '), detail: `qty ${l.quantity}` }
      : { id: l.id, label: l.name, detail: l.code },
  ),
)

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
    <div class="choices">
      <ul v-if="fromScan.length" class="scan-choices">
        <li v-for="c in fromScan" :key="c.id">
          <Button :label="c.label" :data-test="`loc-${c.id}`" text class="choice" @click="emit('select', c.id)">
            <template #default>
              <span class="name">{{ c.label }}</span>
              <small v-if="c.detail" class="muted">{{ c.detail }}</small>
            </template>
          </Button>
        </li>
      </ul>
      <LocationTree v-else :nodes="tree" selectable @select="emit('select', $event)" />
    </div>
    <p v-if="!fromScan.length && !tree.length && !loadError" class="muted">No locations yet.</p>
    <template #footer><Button label="Cancel" text @click="emit('cancel')" /></template>
  </Dialog>
</template>

<style scoped>
.scan-choices { list-style: none; margin: 0; padding: 0; }
.choices { margin: 0; padding: 0; max-height: 50vh; overflow-y: auto; }
.choice { width: 100%; justify-content: space-between; }
</style>
