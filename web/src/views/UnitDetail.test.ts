import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import LatestValues from '@/components/LatestValues.vue'
import { mountWithPlugins, stubApi } from '@/test-utils'

import UnitDetail from './UnitDetail.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
afterEach(() => vi.unstubAllGlobals())

const TYPES = [
  { id: 3, category_id: 1, key: 'capacity_test', name: 'Capacity Test', icon: null, applies_to: 'unit', inherited_from: null, summary_fields: ['ir_mohm'], fields: [] },
]
const UNIT = {
  id: 7, item_id: 1, item: { id: 1, name: 'Samsung 30Q', sku: 'CELL-18650-30Q' }, unit_code: 'C0007', serial_number: null, location_id: 2,
  location_path: [{ id: 2, name: 'Cell box', code: 'LOC-0002' }], condition: 'tested_good', status: 'checked_out', attrs: {},
  attrs_display: { wrap_color: 'pink' }, barcodes: [], created_at: '', updated_at: '',
}
const ITEM = { id: 1, category_id: 1, category_path: [{ id: 1, name: 'Cells' }], tracking_mode: 'unit', name: 'Samsung 30Q', sku: 'CELL-18650-30Q', description: null, notes: null, attrs: {}, attrs_display: {}, min_stock: null, default_location_id: null, photo_attachment_id: null, on_hand: 0, barcodes: [], created_at: '', updated_at: '' }

describe('LatestValues', () => {
  it('shows newest entry values per type', () => {
    const w = mountWithPlugins(LatestValues, {
      props: {
        logTypes: TYPES,
        latest: { capacity_test: { performed_at: '2026-06-01T00:00:00Z', values: { ir_mohm: 22 }, values_display: { ir_mohm: '22mΩ' } } },
      },
    })
    expect(w.text()).toContain('Capacity Test')
    expect(w.text()).toContain('22mΩ')
  })
})

describe('UnitDetail', () => {
  it('actions match status', async () => {
    stubApi({
      '/units/7': UNIT,
      '/items/1': ITEM,
      '/units/7/latest': {},
      '/units/7/log': [],
      '/movements': [],
      '/attachments': [],
      '/categories/1/log-types': TYPES,
      '/categories/1/fields': [],
    })
    const w = mountWithPlugins(UnitDetail, { props: { id: '7' } })
    await flushPromises()
    expect(w.find('[data-test=unit-check-in]').exists()).toBe(true)
    expect(w.find('[data-test=unit-check-out]').exists()).toBe(false)
    expect(w.text()).toContain('C0007')
    expect(w.text()).toContain('Add Capacity Test')
  })
})
