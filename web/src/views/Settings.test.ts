import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { errorResponse, mountWithPlugins, stubApi } from '@/test-utils'

import Settings from './Settings.vue'

const VALUES = {
  'auth.mode': 'password', 'scanner.min_length': 4, 'scanner.max_gap_ms': 30, 'scanner.prefix': '', 'scanner.suffix': '',
  'scanner.intercept_inputs': true, 'lights.light_children_default': 'off', 'trash.retention_days': 30,
  'backup.schedule': '03:00', 'backup.keep': 14, 'display.theme': 'system', 'setup.completed': true,
}

afterEach(() => vi.unstubAllGlobals())

describe('Settings', () => {
  beforeEach(() => vi.useRealTimers())

  it('shows field error for invalid schedule', async () => {
    stubApi({
      '/settings': VALUES,
      'PATCH /settings': errorResponse(422, { error: 'validation', message: 'Validation failed', fields: { 'backup.schedule': 'Use 24-hour HH:MM, e.g. 03:00' } }),
      '/backups': { backup_dir: '/backups', backups: [], last: null },
    })
    const w = mountWithPlugins(Settings)
    await flushPromises()
    await w.get('[data-test="backup.schedule"]').setValue('25:00')
    await w.get('[data-test=save-settings]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Use 24-hour HH:MM, e.g. 03:00')
  })

  it('scanner test box reports gaps', async () => {
    stubApi({ '/settings': VALUES, '/backups': { backup_dir: '/backups', backups: [], last: null } })
    const w = mountWithPlugins(Settings, { attachTo: document.body })
    await flushPromises()
    vi.useFakeTimers()
    const box = w.get('[data-test=scanner-test]')
    for (const ch of 'C0042') {
      await box.trigger('keydown', { key: ch })
      vi.advanceTimersByTime(10)
    }
    await box.trigger('keydown', { key: 'Enter' })
    expect(w.get('[data-test=scanner-result]').text()).toContain('C0042')
    expect(w.get('[data-test=scanner-result]').text()).toContain('max gap 10 ms')
    expect(w.get('[data-test=scanner-result]').text()).toContain('looks like a scanner')
    w.unmount()
  })
})
