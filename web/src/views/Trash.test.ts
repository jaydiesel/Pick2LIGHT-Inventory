import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { errorResponse, mountWithPlugins, stubApi } from '@/test-utils'

import Trash from './Trash.vue'

afterEach(() => vi.unstubAllGlobals())

describe('Trash', () => {
  it('restore conflict shows message', async () => {
    stubApi({
      '/trash': [{ type: 'location', id: 4, name: 'Box', deleted_at: '2026-11-01T10:00:00Z' }],
      'POST /trash/location/4/restore': errorResponse(409, { error: 'conflict', message: "Restore 'Garage' first" }),
    })
    const w = mountWithPlugins(Trash)
    await flushPromises()
    expect(w.text()).toContain('Box')
    await w.get('[data-test=restore-location-4]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain("Restore 'Garage' first")
  })
})
