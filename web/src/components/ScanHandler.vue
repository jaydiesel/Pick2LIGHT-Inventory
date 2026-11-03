<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import type { ScanResult } from '@/api/types'
import LocationPicker from '@/components/LocationPicker.vue'
import { type ScannerOptions, useScanner } from '@/composables/useScanner'
import { useScanStore } from '@/stores/scan'
import { useSettings } from '@/stores/settings'

const store = useScanStore()
const settings = useSettings()
const router = useRouter()
const toast = useToast()

function options(): ScannerOptions {
  return {
    minLength: settings.get('scanner.min_length', 4),
    maxGapMs: settings.get('scanner.max_gap_ms', 30),
    prefix: settings.get('scanner.prefix', ''),
    suffix: settings.get('scanner.suffix', ''),
    interceptInputs: settings.get('scanner.intercept_inputs', true),
  }
}

function show(result: ScanResult, mode: string) {
  if (result.action === 'needs_location') return
  if (result.action === 'error') {
    toast.add({ severity: 'error', summary: result.code, detail: result.message, life: 6000 })
    return
  }
  if (result.kind === 'unknown') {
    toast.add({ severity: 'warn', summary: 'Unknown code', detail: `${result.code} — see the dashboard to add it`, life: 6000 })
    return
  }
  if (mode === 'find' && result.action === 'found') {
    if (result.kind === 'item' && result.item) router.push(`/items/${result.item.id}`)
    else if (result.kind === 'unit' && result.unit) router.push(`/units/${result.unit.id}`)
    else if (result.kind === 'location' && result.location) router.push(`/locations/${result.location.id}`)
    return
  }
  toast.add({ severity: 'success', summary: 'Done', detail: result.message, life: 4000 })
}

async function run(action: () => Promise<ScanResult | null>, mode: string) {
  try {
    const result = await action()
    if (result) show(result, mode)
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Scan failed', detail: e instanceof ApiError ? e.message : String(e), life: 6000 })
  }
}

useScanner(options, (code) => run(() => store.submit(code), store.mode))

function choose(id: number) {
  const mode = store.pendingLocationChoice?.mode ?? store.mode
  run(() => store.chooseLocation(id), mode)
}
</script>

<template>
  <LocationPicker
    :open="!!store.pendingLocationChoice"
    :title="store.pendingLocationChoice?.message"
    :locations="store.pendingLocationChoice?.locations"
    @select="choose"
    @close="store.cancelChoice()"
  />
</template>
