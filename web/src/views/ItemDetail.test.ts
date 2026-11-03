import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountWithPlugins, stubApi } from '@/test-utils'

import ItemDetail from './ItemDetail.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
afterEach(() => vi.unstubAllGlobals())

const ITEM = {
  id: 1, category_id: 4, category_path: [{ id: 4, name: 'Screws' }], tracking_mode: 'bulk', name: 'M3x10', sku: 'SCR-M3-10',
  description: null, notes: null, attrs: {}, attrs_display: { length: '10mm' }, min_stock: 50, default_location_id: null,
  photo_attachment_id: null, on_hand: 40, barcodes: [], created_at: '', updated_at: '',
}
const MOVE = {
  id: 5, item_id: 1, item_name: 'M3x10', item_sku: 'SCR-M3-10', unit_id: null, unit_code: null, from_location: null,
  to_location: { id: 2, name: 'A1', code: 'LOC-0002' }, quantity_delta: 40, reason: 'check_in', source: 'ui', note: null,
  reverses_movement_id: null, reversed: false, created_at: '2026-11-03T10:00:00Z',
}
const UNIT = {
  id: 7, item_id: 1, item: { id: 1, name: 'M3x10', sku: 'X' }, unit_code: 'C0001', serial_number: null, location_id: 2,
  location_path: [{ id: 2, name: 'Box', code: 'LOC-0002' }], condition: 'tested_good', status: 'in_stock', attrs: {},
  attrs_display: {}, barcodes: [], created_at: '', updated_at: '',
}

function api(item = ITEM) {
  return stubApi({
    '/items/1': item,
    '/items/1/stock': [{ location_id: 2, location_path: [{ id: 2, name: 'A1', code: 'LOC-0002' }], quantity: 40 }],
    '/items/1/units': [UNIT],
    '/units/7/latest': { capacity_test: { performed_at: '', values: { ir_mohm: 22 }, values_display: { ir_mohm: '22mΩ' } } },
    '/movements': [MOVE],
    'POST /movements/5/undo': { ...MOVE, id: 6, reason: 'undo' },
    '/attachments': [],
    '/items/1/purchase-sources': [],
    '/categories/4/log-types': [],
    '/categories/4/fields': [],
    '/items/1/log': [],
  })
}

describe('ItemDetail', () => {
  it('undo button calls endpoint and refreshes', async () => {
    const fetch = api()
    vi.stubGlobal('confirm', () => true)
    const w = mountWithPlugins(ItemDetail, { props: { id: '1' } })
    await flushPromises()
    const loadsBefore = fetch.mock.calls.filter(([u, i]) => u === '/api/v1/items/1' && !i?.method).length
    await w.get('[data-test=undo-5]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some(([u, i]) => u === '/api/v1/movements/5/undo' && i?.method === 'POST')).toBe(true)
    expect(fetch.mock.calls.filter(([u, i]) => u === '/api/v1/items/1' && !i?.method).length).toBe(loadsBefore + 1)
  })

  it('bulk items show the stock table', async () => {
    api()
    const w = mountWithPlugins(ItemDetail, { props: { id: '1' } })
    await flushPromises()
    expect(w.find('[data-test=stock-table]').exists()).toBe(true)
    expect(w.find('[data-test=units-table]').exists()).toBe(false)
    expect(w.text()).toContain('Low stock')
  })

  it('per-unit items show units table not stock table', async () => {
    api({ ...ITEM, tracking_mode: 'unit' })
    const w = mountWithPlugins(ItemDetail, { props: { id: '1' } })
    await flushPromises()
    expect(w.find('[data-test=units-table]').exists()).toBe(true)
    expect(w.find('[data-test=stock-table]').exists()).toBe(false)
    expect(w.get('[data-test=units-table]').text()).toContain('22mΩ')
  })
})
