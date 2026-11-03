<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { apiFetch } from '@/api/client'
import type { LowStockRow, ScanResult } from '@/api/types'
import AttachCodeDialog from '@/components/AttachCodeDialog.vue'
import { useScanStore } from '@/stores/scan'

const router = useRouter()
const scan = useScanStore()
const low = ref<LowStockRow[]>([])
const unknown = ref<string[]>([])
const attaching = ref<string | null>(null)
const query = ref('')

async function load() {
  const [l, u] = await Promise.all([apiFetch<LowStockRow[]>('/stock/low'), apiFetch<string[]>('/scan/unknown')])
  low.value = l
  unknown.value = u
}

function link(r: ScanResult): string | null {
  if (r.item) return `/items/${r.item.id}`
  if (r.unit) return `/units/${r.unit.id}`
  if (r.location) return `/locations/${r.location.id}`
  return null
}

function search() {
  router.push({ name: 'search', query: query.value.trim() ? { q: query.value.trim() } : {} })
}

onMounted(load)
</script>

<template>
  <h1>Dashboard</h1>
  <form class="card row" role="search" @submit.prevent="search">
    <input v-model="query" class="p2l-input spacer" data-scan-target placeholder="Search or scan anything" aria-label="Search" />
    <button class="p2l-btn primary" type="submit">Search</button>
  </form>
  <div class="grid-2">
    <section class="card">
      <h2>Recent scans</h2>
      <p v-if="!scan.recent.length" class="muted">Scan a label with your barcode scanner — it works on every page.</p>
      <table v-else class="plain" data-test="recent-scans">
        <tbody>
          <tr v-for="(r, i) in scan.recent" :key="i">
            <td><code>{{ r.code }}</code></td>
            <td><span :class="['badge', { danger: r.action === 'error', warn: r.kind === 'unknown' }]">{{ r.kind }}</span></td>
            <td>
              <RouterLink v-if="link(r)" :to="link(r)!">{{ r.message }}</RouterLink>
              <span v-else>{{ r.message }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
    <section class="card">
      <h2>Low stock</h2>
      <p v-if="!low.length" class="muted">Nothing is below its minimum.</p>
      <table v-else class="plain" data-test="low-stock">
        <thead><tr><th>Item</th><th>On hand</th><th>Min</th></tr></thead>
        <tbody>
          <tr v-for="row in low" :key="row.item_id">
            <td><RouterLink :to="`/items/${row.item_id}`">{{ row.name }}</RouterLink> <span class="muted">{{ row.sku }}</span></td>
            <td>{{ row.on_hand }}</td>
            <td>{{ row.min_stock }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    <section class="card">
      <h2>Unknown scans</h2>
      <p v-if="!unknown.length" class="muted">No unknown codes.</p>
      <table v-else class="plain" data-test="unknown-scans">
        <tbody>
          <tr v-for="code in unknown" :key="code">
            <td><code>{{ code }}</code></td>
            <td class="row">
              <RouterLink class="p2l-btn" :to="{ path: '/items/new', query: { barcode: code } }" data-test="create-from-code">Create item</RouterLink>
              <button class="p2l-btn" @click="attaching = code">Attach…</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
  <AttachCodeDialog :open="!!attaching" :code="attaching || ''" @close="attaching = null" @attached="load" />
</template>
