import { defineStore } from 'pinia'
import { ref } from 'vue'

import { apiFetch } from '@/api/client'
import type { ScanResult, StockRow } from '@/api/types'

export type ScanMode = 'find' | 'check_in' | 'check_out' | 'consume'
export const IDLE_RESET_MS = 60_000
export const MAX_RECENT = 20

export interface PendingChoice {
  code: string
  mode: ScanMode
  quantity: number
  locations: StockRow[]
  message: string
}

export const useScanStore = defineStore('scan', () => {
  const mode = ref<ScanMode>('find')
  const quantity = ref(1)
  const recent = ref<ScanResult[]>([])
  const pendingLocationChoice = ref<PendingChoice | null>(null)
  const busy = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined

  function touch() {
    clearTimeout(timer)
    if (mode.value !== 'find') timer = setTimeout(reset, IDLE_RESET_MS)
  }

  function setMode(m: ScanMode) {
    mode.value = m
    touch()
  }

  function reset() {
    clearTimeout(timer)
    mode.value = 'find'
    quantity.value = 1
    pendingLocationChoice.value = null
  }

  async function send(code: string, m: ScanMode, qty: number, locationId?: number): Promise<ScanResult> {
    const body: Record<string, unknown> = { code, mode: m, quantity: qty }
    if (locationId !== undefined) body.location_id = locationId
    busy.value = true
    try {
      const result = await apiFetch<ScanResult>('/scan', { method: 'POST', json: body })
      recent.value = [result, ...recent.value].slice(0, MAX_RECENT)
      if (result.action === 'needs_location') {
        pendingLocationChoice.value = {
          code,
          mode: m,
          quantity: qty,
          locations: (result.locations ?? []) as StockRow[],
          message: result.message,
        }
      } else {
        pendingLocationChoice.value = null
        if (m !== 'find' && result.action !== 'error') quantity.value = 1
      }
      return result
    } finally {
      busy.value = false
      touch()
    }
  }

  function submit(code: string, extra: { location_id?: number } = {}) {
    return send(code, mode.value, quantity.value, extra.location_id)
  }

  async function chooseLocation(locationId: number): Promise<ScanResult | null> {
    const pending = pendingLocationChoice.value
    if (!pending) return null
    pendingLocationChoice.value = null
    return send(pending.code, pending.mode, pending.quantity, locationId)
  }

  function cancelChoice() {
    pendingLocationChoice.value = null
  }

  return { mode, quantity, recent, pendingLocationChoice, busy, setMode, reset, submit, chooseLocation, cancelChoice }
})
