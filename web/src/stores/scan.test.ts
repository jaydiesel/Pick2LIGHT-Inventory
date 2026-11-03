import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { stubApi } from '@/test-utils'

import { useScanStore } from './scan'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const ROWS = [
  { location_id: 1, location_path: [{ id: 1, name: 'A1', code: 'LOC-0001' }], quantity: 5 },
  { location_id: 2, location_path: [{ id: 2, name: 'A2', code: 'LOC-0002' }], quantity: 5 },
]

describe('scan store', () => {
  it('needs_location opens picker and resubmits with location_id', async () => {
    const fetch = stubApi({
      'POST /scan': (_url: string, init: RequestInit) => {
        const body = JSON.parse(init.body as string)
        return body.location_id
          ? { code: body.code, kind: 'item', action: 'checked_out', message: 'Checked out 2 × M3 from A2' }
          : { code: body.code, kind: 'item', action: 'needs_location', locations: ROWS, message: 'Which location?' }
      },
    })
    const store = useScanStore()
    store.setMode('check_out')
    store.quantity = 2
    await store.submit('SCR-M3')
    expect(store.pendingLocationChoice?.locations).toHaveLength(2)
    const result = await store.chooseLocation(2)
    expect(result?.action).toBe('checked_out')
    expect(store.pendingLocationChoice).toBeNull()
    const last = JSON.parse(fetch.mock.calls.at(-1)![1]!.body as string)
    expect(last).toEqual({ code: 'SCR-M3', mode: 'check_out', quantity: 2, location_id: 2 })
    expect(store.recent[0].action).toBe('checked_out')
  })

  it('mode resets to find after 60 s', () => {
    const store = useScanStore()
    store.setMode('consume')
    vi.advanceTimersByTime(59_000)
    expect(store.mode).toBe('consume')
    vi.advanceTimersByTime(1_500)
    expect(store.mode).toBe('find')
  })

  it('keeps at most 20 recent scans', async () => {
    stubApi({ 'POST /scan': { code: 'X', kind: 'unknown', action: 'found', message: 'Unknown code X' } })
    const store = useScanStore()
    for (let i = 0; i < 25; i++) await store.submit(`X${i}`)
    expect(store.recent).toHaveLength(20)
  })
})
