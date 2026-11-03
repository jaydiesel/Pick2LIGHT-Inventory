import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useScanStore } from './scan'

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
}

describe('scan store', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  const navigate = vi.fn()
  const notify = vi.fn()

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    navigate.mockReset()
    notify.mockReset()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  function bound() {
    const store = useScanStore()
    store.bind({ navigate, notify })
    return store
  }

  it('needs_location opens picker and resubmits with location_id', async () => {
    const locations = [{ id: 7, name: 'Bin', code: 'LOC-0007' }]
    fetchMock
      .mockResolvedValueOnce(json({ kind: 'item', action: 'needs_location', locations, message: 'Choose' }))
      .mockResolvedValueOnce(json({ kind: 'item', action: 'checked_out', message: 'Took 1' }))
    const store = bound()
    store.mode = 'check_out'
    await store.submit('R-10K')
    expect(store.pendingLocationChoice?.code).toBe('R-10K')
    expect(store.pendingLocationChoice?.locations).toEqual(locations)

    await store.chooseLocation(7)
    expect(store.pendingLocationChoice).toBeNull()
    const body = JSON.parse(fetchMock.mock.calls[1][1].body)
    expect(body).toEqual({ code: 'R-10K', mode: 'check_out', quantity: 1, location_id: 7 })
    expect(notify).toHaveBeenCalledWith('success', 'Took 1')
    expect(store.recent[0].action).toBe('checked_out')
  })

  it('mode resets to find after 60 s', () => {
    const store = bound()
    store.mode = 'consume'
    store.quantity = 5
    vi.advanceTimersByTime(59_000)
    expect(store.mode).toBe('consume')
    // A change restarts the idle timer.
    store.quantity = 6
    vi.advanceTimersByTime(59_000)
    expect(store.mode).toBe('consume')
    vi.advanceTimersByTime(1_000)
    expect(store.mode).toBe('find')
    expect(store.quantity).toBe(1)
  })

  it('a scan restarts the idle timer', async () => {
    fetchMock.mockImplementation(async () => json({ kind: 'item', action: 'consumed', message: 'ok' }))
    const store = bound()
    store.mode = 'consume'
    vi.advanceTimersByTime(50_000)
    await store.submit('X1')
    vi.advanceTimersByTime(50_000)
    expect(store.mode).toBe('consume')
    vi.advanceTimersByTime(10_000)
    expect(store.mode).toBe('find')
  })

  it('navigates on found in find mode only', async () => {
    fetchMock.mockImplementation(async () => json({ kind: 'unit', action: 'found', unit: { id: 3 }, message: 'Unit' }))
    const store = bound()
    await store.submit('U1')
    expect(navigate).toHaveBeenCalledWith('/units/3')
    navigate.mockReset()
    store.mode = 'check_in'
    await store.submit('U1')
    expect(navigate).not.toHaveBeenCalled()
    expect(notify).toHaveBeenCalledWith('info', 'Unit')
  })

  it('shows an error toast for action error and keeps only 20 recent', async () => {
    fetchMock.mockImplementation(async () => json({ kind: 'item', action: 'error', message: 'Insufficient stock' }))
    const store = bound()
    for (let i = 0; i < 22; i++) await store.submit(`C${i}`)
    expect(notify).toHaveBeenLastCalledWith('error', 'Insufficient stock')
    expect(store.recent).toHaveLength(20)
    expect(store.recent[0].code).toBe('C21')
  })
})
