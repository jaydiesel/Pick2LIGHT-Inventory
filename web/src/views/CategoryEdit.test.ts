import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { errorResponse, mountWithPlugins, stubApi } from '@/test-utils'

import CategoryEdit from './CategoryEdit.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
afterEach(() => vi.unstubAllGlobals())

const base = { icon: null, description: null, tracking_mode: null, effective_tracking_mode: 'bulk', sku_prefix: null, sku_pattern: null, unit_id_pattern: null, default_label_template_id: null, default_unit_label_template_id: null, created_at: '', updated_at: '' }
const ROOT = { ...base, id: 1, name: 'Electronics', parent_id: null, path: [{ id: 1, name: 'Electronics' }] }
const RES = { ...base, id: 2, name: 'Resistors', parent_id: 1, path: [{ id: 1, name: 'Electronics' }, { id: 2, name: 'Resistors' }] }
const OTHER = { ...base, id: 3, name: 'Other', parent_id: null, path: [{ id: 3, name: 'Other' }] }
const field = (id: number, key: string, inherited_from: number | null) => ({
  id, category_id: inherited_from ?? 2, key, label: key, type: 'text', scope: 'item', required: false, filterable: false,
  show_on_label: false, number_unit: null, number_si_prefixes: false, min: null, max: null, decimals: null, options: [],
  help_text: null, order: 0, inherited_from,
})

function api(extra: Record<string, unknown> = {}) {
  return stubApi({
    '/categories/2': RES,
    '/categories': [ROOT, RES, OTHER],
    '/categories/2/fields': [field(10, 'datasheet', 1), field(11, 'resistance', null)],
    '/categories/2/log-types': [],
    ...extra,
  })
}

describe('CategoryEdit', () => {
  it('inherited fields are read-only', async () => {
    api()
    const w = mountWithPlugins(CategoryEdit, { props: { id: '2' } })
    await flushPromises()
    const inherited = w.get('[data-test=field-datasheet]')
    expect(inherited.text()).toContain('from Electronics')
    expect(inherited.find('[data-test=edit-field]').exists()).toBe(false)
    expect(w.get('[data-test=field-resistance]').find('[data-test=edit-field]').exists()).toBe(true)
  })

  it('shows server conflict message on move', async () => {
    api({ 'PATCH /categories/2': errorResponse(409, { error: 'conflict', message: "Field key 'datasheet' already exists in the new parent" }) })
    const w = mountWithPlugins(CategoryEdit, { props: { id: '2' } })
    await flushPromises()
    await w.get('[data-test=parent]').setValue('3')
    await w.get('[data-test=save-category]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain("Field key 'datasheet' already exists in the new parent")
  })
})
