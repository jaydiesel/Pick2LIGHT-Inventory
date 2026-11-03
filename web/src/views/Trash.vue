<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError, apiFetch } from '@/api/client'
import type { TrashEntry } from '@/api/types'

const entries = ref<TrashEntry[]>([])
const error = ref('')
const LABELS: Record<string, string> = { category: 'Category', log_entry_type: 'Log type', item: 'Item', unit: 'Unit', location: 'Location' }

async function load() {
  entries.value = await apiFetch<TrashEntry[]>('/trash')
}

async function restore(e: TrashEntry) {
  error.value = ''
  try {
    await apiFetch(`/trash/${e.type}/${e.id}/restore`, { method: 'POST' })
    await load()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : String(err)
  }
}

onMounted(load)
</script>

<template>
  <h1>Trash</h1>
  <p class="muted">Deleted things stay here for a while (see Settings) and can be restored.</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <section class="card">
    <p v-if="!entries.length" class="muted">The trash is empty.</p>
    <table v-else class="plain">
      <thead><tr><th>Type</th><th>Name</th><th>Deleted</th><th /></tr></thead>
      <tbody>
        <tr v-for="e in entries" :key="`${e.type}-${e.id}`">
          <td>{{ LABELS[e.type] ?? e.type }}</td>
          <td>{{ e.name }}</td>
          <td>{{ new Date(e.deleted_at).toLocaleString() }}</td>
          <td><button class="p2l-btn" :data-test="`restore-${e.type}-${e.id}`" @click="restore(e)">Restore</button></td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
