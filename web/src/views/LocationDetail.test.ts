import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { errorResponse, mountWithPlugins, stubApi } from '@/test-utils'

import LocationDetail from './LocationDetail.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
afterEach(() => vi.unstubAllGlobals())

const LOC = {
  id: 3, name: 'A1', code: 'LOC-0003', parent_id: 2, location_type_id: null, type_name: 'Drawer', notes: 'M3 stuff',
  photo_attachment_id: null, light_children: 'inherit', grid_row: null, grid_col: null, created_at: '', updated_at: '',
  path: [
    { id: 1, name: 'Garage', code: 'LOC-0001' },
    { id: 2, name: 'Cabinet', code: 'LOC-0002' },
    { id: 3, name: 'A1', code: 'LOC-0003' },
  ],
}

function api(extra: Record<string, unknown> = {}) {
  return stubApi({
    '/locations/3': LOC,
    'POST /search': { hits: [{ id: 9, name: 'M3x10', sku: 'SCR-M3-10', category_id: 1, category_name: 'Screws', on_hand: 40, min_stock: null, attrs_display: {}, matched_unit_id: null, rank: 0 }], total: 1, location_match: null },
    '/locations/tree': [],
    '/location-types': [],
    ...extra,
  })
}

describe('LocationDetail', () => {
  it('shows breadcrumb from path and contents', async () => {
    api()
    const w = mountWithPlugins(LocationDetail, { props: { id: '3' } })
    await flushPromises()
    expect(w.get('[data-test=breadcrumb]').text()).toBe('Garage › Cabinet › A1')
    expect(w.text()).toContain('M3x10')
  })

  it('delete conflict shows server message', async () => {
    api({ 'DELETE /locations/3': errorResponse(409, { error: 'conflict', message: 'This location still holds stock or units; move them first' }) })
    vi.stubGlobal('confirm', () => true)
    const w = mountWithPlugins(LocationDetail, { props: { id: '3' } })
    await flushPromises()
    await w.get('[data-test=delete-location]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('This location still holds stock or units; move them first')
  })
})
