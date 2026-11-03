import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { errorResponse, mountWithPlugins, stubApi } from '@/test-utils'

import LogEntryForm from './LogEntryForm.vue'

afterEach(() => vi.unstubAllGlobals())

const TYPE = {
  id: 3, category_id: 1, key: 'capacity_test', name: 'Capacity Test', icon: null, applies_to: 'unit', inherited_from: null,
  summary_fields: ['ir_mohm'],
  fields: [
    { key: 'capacity_mah', label: 'Capacity', type: 'number', number_unit: 'mAh', number_si_prefixes: false, options: [] },
    { key: 'ir_mohm', label: 'IR', type: 'number', number_unit: 'mΩ', number_si_prefixes: false, options: [] },
  ],
}
const ENTRY = { id: 9, log_entry_type_id: 3, type_key: 'capacity_test', type_name: 'Capacity Test', unit_id: 7, item_id: null, performed_at: '2026-11-03T10:00:00Z', values: { ir_mohm: 22 }, values_display: {}, notes: null, created_at: '' }

async function fillIr(w: ReturnType<typeof mountWithPlugins>, value: string) {
  const input = w.get('[data-test=field-ir_mohm] input')
  await input.trigger('focus')
  await input.setValue(value)
  await input.trigger('blur')
}

describe('LogEntryForm', () => {
  it('posts typed values', async () => {
    const fetch = stubApi({ 'POST /log-entries': ENTRY })
    const w = mountWithPlugins(LogEntryForm, { props: { logType: TYPE, unitId: 7 } })
    await fillIr(w, '22')
    await w.get('form').trigger('submit')
    await flushPromises()
    const body = JSON.parse(fetch.mock.calls[0][1]!.body as string)
    expect(body).toMatchObject({ log_entry_type_id: 3, unit_id: 7, values: { ir_mohm: 22 } })
    expect(typeof body.performed_at).toBe('string')
    expect(w.emitted('saved')).toHaveLength(1)
  })

  it('server field error displayed in form', async () => {
    stubApi({ 'POST /log-entries': errorResponse(422, { error: 'validation', message: 'Validation failed', fields: { ir_mohm: 'Must be at least 0' } }) })
    const w = mountWithPlugins(LogEntryForm, { props: { logType: TYPE, unitId: 7 } })
    await fillIr(w, '5')
    await w.get('form').trigger('submit')
    await flushPromises()
    expect(w.get('[data-test=field-ir_mohm]').text()).toContain('Must be at least 0')
    expect(w.emitted('saved')).toBeUndefined()
  })
})
