<script setup lang="ts">
import type { MovementOut } from '@/api/types'

defineProps<{ movements: MovementOut[] }>()
const emit = defineEmits<{ undo: [id: number] }>()

const REASONS: Record<string, string> = {
  create: 'Added', import: 'Imported', check_out: 'Checked out', check_in: 'Checked in', consume: 'Used up',
  move: 'Moved', adjust: 'Count corrected', stocktake: 'Stocktake', undo: 'Undo',
}

function when(iso: string) {
  return new Date(iso).toLocaleString()
}

function canUndo(m: MovementOut) {
  return !m.reversed && m.reason !== 'undo' && m.reason !== 'create'
}
</script>

<template>
  <p v-if="!movements.length" class="muted">No history yet.</p>
  <table v-else class="plain">
    <thead><tr><th>When</th><th>What</th><th>Qty</th><th>From → to</th><th>Via</th><th /></tr></thead>
    <tbody>
      <tr v-for="m in movements" :key="m.id" :class="{ reversed: m.reversed }">
        <td>{{ when(m.created_at) }}</td>
        <td>{{ REASONS[m.reason] ?? m.reason }}<template v-if="m.unit_code"> · {{ m.unit_code }}</template><span v-if="m.note" class="muted"> — {{ m.note }}</span></td>
        <td>{{ m.quantity_delta > 0 ? '+' : '' }}{{ m.quantity_delta }}</td>
        <td>{{ m.from_location?.name ?? '—' }} → {{ m.to_location?.name ?? '—' }}</td>
        <td class="muted">{{ m.source }}</td>
        <td>
          <span v-if="m.reversed" class="badge">undone</span>
          <button v-else-if="canUndo(m)" class="p2l-btn" :data-test="`undo-${m.id}`" @click="emit('undo', m.id)">Undo</button>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.reversed td { opacity: .6; }
</style>
