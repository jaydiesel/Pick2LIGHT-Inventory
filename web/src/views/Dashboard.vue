<script setup lang="ts">
import Button from 'primevue/button'
import Card from 'primevue/card'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import { useToast } from 'primevue/usetoast'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiFetch } from '../api/client'
import type { components } from '../api/schema'
import { useScanStore, type ScanEntry } from '../stores/scan'

type LowStockRow = components['schemas']['LowStockRow']
type SearchPage = components['schemas']['SearchPage']
type LocationNode = components['schemas']['LocationNode']
type BarcodeIn = components['schemas']['BarcodeIn']

interface Candidate {
  id: number
  label: string
  detail: string
}

const router = useRouter()
const toast = useToast()
const scan = useScanStore()

const query = ref('')
const lowStock = ref<LowStockRow[]>([])
const lowError = ref('')

function search() {
  const q = query.value.trim()
  void router.push({ path: '/search', query: q ? { q } : {} })
}

function link(e: ScanEntry): string | null {
  if (e.item) return `/items/${e.item.id}`
  if (e.unit) return `/units/${e.unit.id}`
  if (e.location) return `/locations/${e.location.id}`
  return null
}

function fail(e: unknown) {
  toast.add({ severity: 'error', summary: e instanceof Error ? e.message : 'Request failed', life: 5000 })
}

onMounted(async () => {
  await Promise.all([
    apiFetch<LowStockRow[]>('/stock/low').then(
      (rows) => (lowStock.value = rows),
      (e) => (lowError.value = e instanceof Error ? e.message : 'Could not load low stock'),
    ),
    scan.loadUnknown().catch(fail),
  ])
})

// ---- Attach… dialog -------------------------------------------------------------------------
// The API has no dedicated unit/location search, so: items and units use `GET /search` (a unit hit is a result
// with `matched_unit_id`, i.e. the query matched a unit code or serial), and locations filter the location tree.
const targetTypes: { label: string; value: BarcodeIn['target_type'] }[] = [
  { label: 'Item', value: 'item' },
  { label: 'Unit', value: 'unit' },
  { label: 'Location', value: 'location' },
]
const kinds: { label: string; value: BarcodeIn['kind'] }[] = [
  { label: 'Manufacturer', value: 'manufacturer' },
  { label: 'Supplier', value: 'supplier' },
  { label: 'Custom', value: 'custom' },
]

const attachCode = ref<string | null>(null)
const targetType = ref<BarcodeIn['target_type']>('item')
const kind = ref<BarcodeIn['kind']>('manufacturer')
const attachQuery = ref('')
const candidates = ref<Candidate[]>([])
const locationTree = ref<Candidate[] | null>(null)
const searching = ref(false)

function flattenTree(nodes: LocationNode[], path: string[] = []): Candidate[] {
  return nodes.flatMap((n) => {
    const here = [...path, n.name]
    return [{ id: n.id, label: here.join(' / '), detail: n.code }, ...flattenTree(n.children, here)]
  })
}

function openAttach(code: string) {
  attachCode.value = code
  targetType.value = 'item'
  kind.value = 'manufacturer'
  attachQuery.value = ''
  candidates.value = []
}

async function runAttachSearch() {
  const q = attachQuery.value.trim()
  if (!q) {
    candidates.value = []
    return
  }
  searching.value = true
  try {
    if (targetType.value === 'location') {
      locationTree.value ??= flattenTree(await apiFetch<LocationNode[]>('/locations/tree'))
      const needle = q.toLowerCase()
      candidates.value = locationTree.value
        .filter((l) => l.label.toLowerCase().includes(needle) || l.detail.toLowerCase().includes(needle))
        .slice(0, 20)
    } else {
      const page = await apiFetch<SearchPage>(`/search?q=${encodeURIComponent(q)}&limit=20`)
      candidates.value =
        targetType.value === 'unit'
          ? page.hits
              .filter((h) => h.matched_unit_id !== null)
              .map((h) => ({ id: h.matched_unit_id!, label: `${h.name} (unit)`, detail: h.sku }))
          : page.hits.map((h) => ({ id: h.id, label: h.name, detail: h.sku }))
    }
  } catch (e) {
    fail(e)
  } finally {
    searching.value = false
  }
}

async function attach(target: Candidate) {
  const code = attachCode.value
  if (!code) return
  try {
    const body: BarcodeIn = { code, target_type: targetType.value, target_id: target.id, kind: kind.value }
    await apiFetch('/barcodes', { method: 'POST', json: body })
  } catch (e) {
    fail(e)
    return
  }
  // The barcode exists now, so a failure to tidy the unknown list must not invite a retry.
  attachCode.value = null
  try {
    await scan.removeUnknown(code)
    toast.add({ severity: 'success', summary: `Attached ${code} to ${target.label}`, life: 4000 })
  } catch {
    toast.add({
      severity: 'warn',
      summary: `Attached ${code} to ${target.label}, but it could not be removed from the unknown list`,
      life: 6000,
    })
  }
}

const attachOpen = computed({
  get: () => attachCode.value !== null,
  set: (v: boolean) => {
    if (!v) attachCode.value = null
  },
})
</script>

<template>
  <section class="dashboard">
    <h1>Dashboard</h1>

    <form class="search" role="search" @submit.prevent="search">
      <InputText v-model="query" type="search" data-scan-target placeholder="Search items…" aria-label="Search items" fluid />
    </form>

    <div class="grid">
      <Card>
        <template #title>Recent scans</template>
        <template #content>
          <p v-if="!scan.recent.length" class="muted">Nothing scanned yet.</p>
          <ul v-else class="plain" data-test="recent">
            <li v-for="(e, i) in scan.recent" :key="i">
              <code>{{ e.code }}</code>
              <span class="tag">{{ e.kind }}</span>
              <span class="tag">{{ e.action }}</span>
              <span class="msg">{{ e.message }}</span>
              <RouterLink v-if="link(e)" :to="link(e)!">Open</RouterLink>
            </li>
          </ul>
        </template>
      </Card>

      <Card>
        <template #title>Low stock</template>
        <template #content>
          <p v-if="lowError" role="alert">{{ lowError }}</p>
          <p v-else-if="!lowStock.length" class="muted">Everything is above its minimum.</p>
          <ul v-else class="plain" data-test="low-stock">
            <li v-for="r in lowStock" :key="r.item_id">
              <RouterLink :to="`/items/${r.item_id}`">{{ r.name }}</RouterLink>
              <code>{{ r.sku }}</code>
              <span class="msg">{{ r.on_hand }} / min {{ r.min_stock }}</span>
            </li>
          </ul>
        </template>
      </Card>

      <Card>
        <template #title>Recent unknown scans</template>
        <template #content>
          <p v-if="!scan.unknown.length" class="muted">No unknown codes.</p>
          <ul v-else class="plain" data-test="unknown">
            <li v-for="code in scan.unknown" :key="code">
              <code>{{ code }}</code>
              <span class="msg" />
              <RouterLink :to="{ path: '/items/new', query: { barcode: code } }">Create item</RouterLink>
              <Button label="Attach…" size="small" text @click="openAttach(code)" />
            </li>
          </ul>
        </template>
      </Card>
    </div>

    <Dialog v-model:visible="attachOpen" modal :header="`Attach ${attachCode ?? ''}`" :style="{ width: '32rem' }">
      <div class="attach">
        <Select v-model="targetType" :options="targetTypes" option-label="label" option-value="value" aria-label="Attach to" @change="runAttachSearch" />
        <Select v-model="kind" :options="kinds" option-label="label" option-value="value" aria-label="Barcode kind" />
        <form class="attach-search" @submit.prevent="runAttachSearch">
          <InputText v-model="attachQuery" placeholder="Search…" aria-label="Search target" fluid />
          <Button type="submit" icon="pi pi-search" aria-label="Search" :loading="searching" />
        </form>
        <ul class="plain">
          <li v-for="c in candidates" :key="c.id">
            <span>{{ c.label }}</span>
            <code>{{ c.detail }}</code>
            <span class="msg" />
            <Button label="Attach" size="small" @click="attach(c)" />
          </li>
        </ul>
      </div>
    </Dialog>
  </section>
</template>

<style scoped>
.search { max-width: 32rem; margin-bottom: 1rem; }
.grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr)); }
.plain { list-style: none; margin: 0; padding: 0; }
.plain li { display: flex; align-items: center; gap: 0.5rem; padding: 0.25rem 0; flex-wrap: wrap; }
.msg { flex: 1; min-width: 0; }
.tag { font-size: 0.75rem; padding: 0 0.4rem; border-radius: 4px; background: var(--p-highlight-background); }
.attach { display: flex; flex-direction: column; gap: 0.75rem; }
.attach-search { display: flex; gap: 0.5rem; }
</style>
