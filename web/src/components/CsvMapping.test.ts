import { describe, expect, it } from 'vitest'

import { mountWithPlugins } from '@/test-utils'

import CsvMapping from './CsvMapping.vue'

const spec = (key: string, label: string) => ({
  id: 1, category_id: 1, key, label, type: 'text', scope: 'item', required: false, filterable: false, show_on_label: false,
  number_unit: null, number_si_prefixes: false, min: null, max: null, decimals: null, options: [], help_text: null, order: 0, inherited_from: null,
})

describe('CsvMapping', () => {
  it('auto-maps "Resistance" header to attr.resistance', () => {
    const w = mountWithPlugins(CsvMapping, {
      props: { headers: ['Name', 'Resistance', 'Qty', 'Location', 'Package type'], specs: [spec('resistance', 'Resistance'), spec('package', 'Package type')], modelValue: {} },
    })
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([
      { Name: 'name', Resistance: 'attr.resistance', Qty: 'quantity', Location: 'location_code', 'Package type': 'attr.package' },
    ])
  })

  it('marks unmapped columns ignore', () => {
    const w = mountWithPlugins(CsvMapping, { props: { headers: ['Whatever', 'sku'], specs: [], modelValue: {} } })
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([{ Whatever: 'ignore', sku: 'sku' }])
  })

  it('lets the user change a target', async () => {
    const w = mountWithPlugins(CsvMapping, { props: { headers: ['Whatever'], specs: [spec('model', 'Model')], modelValue: { Whatever: 'ignore' } } })
    await w.get('[data-test=map-Whatever]').setValue('attr.model')
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([{ Whatever: 'attr.model' }])
  })
})

describe('csvHeaders', () => {
  it('matches the server delimiter rule and strips BOM and quotes', async () => {
    const { csvHeaders } = await import('@/lib/csvMapping')
    expect(csvHeaders('﻿Name;Resistance;"Qty; total"\r\nR;4k7;5')).toEqual(['Name', 'Resistance', 'Qty; total'])
    expect(csvHeaders('\n\nsku,name\n')).toEqual(['sku', 'name'])
  })
})
