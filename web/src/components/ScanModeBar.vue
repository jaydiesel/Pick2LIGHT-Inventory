<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

import { type ScanMode, useScanStore } from '@/stores/scan'

const store = useScanStore()
const modes: { id: ScanMode; label: string; icon: string }[] = [
  { id: 'find', label: 'Find', icon: 'pi-search' },
  { id: 'check_in', label: 'Check in', icon: 'pi-arrow-down' },
  { id: 'check_out', label: 'Check out', icon: 'pi-arrow-up' },
  { id: 'consume', label: 'Use up', icon: 'pi-minus-circle' },
]

function onKey(ev: KeyboardEvent) {
  if (ev.key === 'Escape') store.reset()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="modebar" role="group" aria-label="Scan mode">
    <button
      v-for="m in modes"
      :key="m.id"
      :class="['p2l-btn', 'mode', `mode-${m.id}`, { active: store.mode === m.id }]"
      :aria-pressed="store.mode === m.id"
      :data-test="`mode-${m.id}`"
      @click="store.setMode(m.id)"
    >
      <i :class="['pi', m.icon]" /> <span class="label">{{ m.label }}</span>
    </button>
    <label v-if="store.mode !== 'find'" class="qty">
      Qty
      <input v-model.number="store.quantity" class="p2l-input" type="number" min="1" step="any" data-test="quantity" />
    </label>
  </div>
</template>

<style scoped>
.modebar { display: flex; gap: .25rem; align-items: center; flex-wrap: wrap; }
.mode.active { color: #fff; }
.mode-find.active { background: #0b63ce; border-color: #0b63ce; }
.mode-check_in.active { background: #2e7d32; border-color: #2e7d32; }
.mode-check_out.active { background: #b26a00; border-color: #b26a00; }
.mode-consume.active { background: #c62828; border-color: #c62828; }
.qty { display: flex; gap: .35rem; align-items: center; font-size: .85rem; }
.qty input { width: 5rem; }
@media (max-width: 768px) { .label { display: none; } }
</style>
