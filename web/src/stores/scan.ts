import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { apiFetch } from '../api/client'
import type { components } from '../api/schema'

export type ScanResult = components['schemas']['ScanResult']
export type ScanMode = components['schemas']['ScanRequest']['mode']
export type ScanEntry = ScanResult & { code: string }
export type ToastSeverity = 'success' | 'info' | 'warn' | 'error'

export interface PendingLocationChoice {
  code: string
  locations: NonNullable<ScanResult['locations']>
}

export interface ScanHandlers {
  navigate: (path: string) => void
  notify: (severity: ToastSeverity, message: string) => void
}

const IDLE_MS = 60_000
const RECENT_MAX = 20

export const useScanStore = defineStore('scan', () => {
  const mode = ref<ScanMode>('find')
  const quantity = ref(1)
  const recent = ref<ScanEntry[]>([])
  const pendingLocationChoice = ref<PendingLocationChoice | null>(null)
  const unknown = ref<string[]>([])

  let handlers: ScanHandlers = { navigate: () => {}, notify: () => {} }
  let idleTimer: ReturnType<typeof setTimeout> | undefined

  /** Wire the router/toast side effects; the store itself stays free of component context. */
  function bind(h: ScanHandlers) {
    handlers = h
  }

  /** (Re)start the 60 s countdown back to `find`/1; nothing to count down while already idle. */
  function armIdle() {
    clearTimeout(idleTimer)
    if (mode.value === 'find' && quantity.value === 1) return
    idleTimer = setTimeout(reset, IDLE_MS)
  }

  function reset() {
    mode.value = 'find'
    quantity.value = 1
  }

  watch([mode, quantity], armIdle, { flush: 'sync' })

  function path(r: ScanResult): string | null {
    if (r.kind === 'item' && r.item) return `/items/${r.item.id}`
    if (r.kind === 'unit' && r.unit) return `/units/${r.unit.id}`
    if (r.kind === 'location' && r.location) return `/locations/${r.location.id}`
    return null
  }

  async function loadUnknown() {
    unknown.value = await apiFetch<string[]>('/scan/unknown')
  }

  async function removeUnknown(code: string) {
    await apiFetch(`/scan/unknown/${encodeURIComponent(code)}`, { method: 'DELETE' })
    unknown.value = unknown.value.filter((c) => c !== code)
  }

  function announce(code: string, r: ScanResult) {
    if (r.action === 'needs_location') {
      pendingLocationChoice.value = { code, locations: r.locations ?? [] }
    } else if (r.action === 'error') {
      handlers.notify('error', r.message)
    } else if (r.kind === 'unknown') {
      handlers.notify('warn', r.message)
      void loadUnknown().catch(() => {})
    } else if (r.action === 'found' && mode.value === 'find' && path(r)) {
      handlers.navigate(path(r)!)
    } else {
      handlers.notify(r.action === 'found' ? 'info' : 'success', r.message)
    }
  }

  async function submit(code: string, extra: { location_id?: number } = {}): Promise<ScanResult | null> {
    armIdle()
    let result: ScanResult
    try {
      result = await apiFetch<ScanResult>('/scan', {
        method: 'POST',
        json: { code, mode: mode.value, quantity: quantity.value, ...extra },
      })
    } catch (e) {
      handlers.notify('error', e instanceof Error ? e.message : 'Scan failed')
      return null
    }
    recent.value = [{ ...result, code }, ...recent.value].slice(0, RECENT_MAX)
    pendingLocationChoice.value = null
    announce(code, result)
    return result
  }

  async function chooseLocation(locationId: number) {
    const pending = pendingLocationChoice.value
    if (!pending) return
    await submit(pending.code, { location_id: locationId })
  }

  function cancelLocationChoice() {
    pendingLocationChoice.value = null
  }

  return {
    mode,
    quantity,
    recent,
    unknown,
    pendingLocationChoice,
    bind,
    reset,
    submit,
    chooseLocation,
    cancelLocationChoice,
    loadUnknown,
    removeUnknown,
  }
})
