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
  /** Mode and quantity of the original scan; the resubmit must not pick up later changes. */
  mode: ScanMode
  quantity: number
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
  // Scans run one at a time so `recent` and the location prompt follow scan order.
  let queue: Promise<unknown> = Promise.resolve()

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

  function announce(code: string, m: ScanMode, q: number, r: ScanResult) {
    if (r.action === 'needs_location') {
      pendingLocationChoice.value = { code, mode: m, quantity: q, locations: r.locations ?? [] }
    } else if (r.action === 'error') {
      handlers.notify('error', r.message)
    } else if (r.kind === 'unknown') {
      handlers.notify('warn', r.message)
      void loadUnknown().catch(() => {})
    } else if (r.action === 'found' && m === 'find' && path(r)) {
      handlers.navigate(path(r)!)
    } else {
      handlers.notify(r.action === 'found' ? 'info' : 'success', r.message)
    }
  }

  type SubmitExtra = { location_id?: number; mode?: ScanMode; quantity?: number }

  async function run(code: string, m: ScanMode, q: number, locationId?: number): Promise<ScanResult | null> {
    let result: ScanResult
    try {
      result = await apiFetch<ScanResult>('/scan', {
        method: 'POST',
        json: { code, mode: m, quantity: q, ...(locationId === undefined ? {} : { location_id: locationId }) },
      })
    } catch (e) {
      handlers.notify('error', e instanceof Error ? e.message : 'Scan failed')
      return null
    }
    recent.value = [{ ...result, code }, ...recent.value].slice(0, RECENT_MAX)
    pendingLocationChoice.value = null
    announce(code, m, q, result)
    return result
  }

  /** Queue a scan; mode and quantity are captured now, not when the request is eventually sent. */
  function submit(code: string, extra: SubmitExtra = {}): Promise<ScanResult | null> {
    armIdle()
    const m = extra.mode ?? mode.value
    const q = extra.quantity ?? quantity.value
    const job = queue.then(() => run(code, m, q, extra.location_id))
    queue = job.catch(() => {})
    return job
  }

  async function chooseLocation(locationId: number) {
    const pending = pendingLocationChoice.value
    if (!pending) return
    await submit(pending.code, { location_id: locationId, mode: pending.mode, quantity: pending.quantity })
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
