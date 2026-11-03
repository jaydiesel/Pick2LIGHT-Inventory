import { describe, expect, it } from 'vitest'

import { mountWithPlugins } from '@/test-utils'

import FieldForm from './FieldForm.vue'

const spec = (key: string, type: string, extra: Record<string, unknown> = {}) => ({
  id: key.length, category_id: 1, key, label: key, type, scope: 'item', required: false, filterable: false,
  show_on_label: false, number_unit: null, number_si_prefixes: false, min: null, max: null, decimals: null,
  options: [], help_text: null, order: 0, inherited_from: null, ...extra,
})

const SPECS = [
  spec('model', 'text'),
  spec('notes', 'long_text'),
  spec('capacity', 'number', { number_unit: 'mAh' }),
  spec('format', 'select', { options: [{ value: '18650' }, { value: '21700' }] }),
  spec('tags', 'multi_select', { options: [{ value: 'a' }, { value: 'b' }] }),
  spec('ecc', 'boolean'),
  spec('tested', 'date'),
  spec('datasheet', 'url'),
]

describe('FieldForm', () => {
  it('renders control per type', () => {
    const w = mountWithPlugins(FieldForm, { props: { specs: SPECS, modelValue: {}, errors: {} } })
    expect(w.get('[data-test=field-model] input').attributes('type')).toBe('text')
    expect(w.find('[data-test=field-notes] textarea').exists()).toBe(true)
    expect(w.find('[data-test=field-capacity] input').exists()).toBe(true)
    expect(w.findAll('[data-test=field-format] option').map((o) => o.text())).toContain('18650')
    expect(w.findAll('[data-test=field-tags] input[type=checkbox]')).toHaveLength(2)
    expect(w.get('[data-test=field-ecc] input').attributes('type')).toBe('checkbox')
    expect(w.get('[data-test=field-tested] input').attributes('type')).toBe('date')
    expect(w.get('[data-test=field-datasheet] input').attributes('type')).toBe('url')
  })

  it('emits merged values', async () => {
    const w = mountWithPlugins(FieldForm, { props: { specs: SPECS, modelValue: { model: 'x' }, errors: {} } })
    await w.get('[data-test=field-format] select').setValue('21700')
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([{ model: 'x', format: '21700' }])
  })

  it('shows server field errors', () => {
    const w = mountWithPlugins(FieldForm, { props: { specs: SPECS, modelValue: {}, errors: { capacity: 'Must be at least 0' } } })
    expect(w.get('[data-test=field-capacity]').text()).toContain('Must be at least 0')
  })
})
