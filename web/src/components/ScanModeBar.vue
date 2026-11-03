<script setup lang="ts">
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import { onMounted, onUnmounted } from 'vue'
import { useScanStore, type ScanMode } from '../stores/scan'

const scan = useScanStore()

const modes: { id: ScanMode; label: string; severity: 'secondary' | 'success' | 'warn' | 'danger' }[] = [
  { id: 'find', label: 'Find', severity: 'secondary' },
  { id: 'check_in', label: 'Check in', severity: 'success' },
  { id: 'check_out', label: 'Check out', severity: 'warn' },
  { id: 'consume', label: 'Consume', severity: 'danger' },
]

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') scan.reset()
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="scan-mode-bar" :data-mode="scan.mode" role="group" aria-label="Scan mode">
    <Button
      v-for="m in modes"
      :key="m.id"
      :label="m.label"
      :severity="m.severity"
      :variant="scan.mode === m.id ? undefined : 'outlined'"
      :aria-pressed="scan.mode === m.id"
      :data-test="`mode-${m.id}`"
      size="small"
      @click="scan.mode = m.id"
    />
    <InputNumber
      v-model="scan.quantity"
      :min="1"
      :use-grouping="false"
      show-buttons
      button-layout="horizontal"
      input-class="qty"
      aria-label="Quantity"
      size="small"
    />
  </div>
</template>

<style scoped>
.scan-mode-bar { display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap; }
.scan-mode-bar :deep(.qty) { width: 3.5rem; text-align: center; }
</style>
