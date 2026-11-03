import { describe, expect, it } from 'vitest'

import { mountWithPlugins } from '@/test-utils'

import FieldDefEditor from './FieldDefEditor.vue'

describe('FieldDefEditor', () => {
  it('derives key from label', async () => {
    const w = mountWithPlugins(FieldDefEditor, { props: { trackingMode: 'bulk' } })
    await w.get('[data-test=label]').setValue('Internal Resistance')
    expect((w.get('[data-test=key]').element as HTMLInputElement).value).toBe('internal_resistance')
    await w.get('[data-test=key]').setValue('ir_mohm')
    await w.get('[data-test=label]').setValue('IR')
    expect((w.get('[data-test=key]').element as HTMLInputElement).value).toBe('ir_mohm')
  })

  it('shows unit options only for number', async () => {
    const w = mountWithPlugins(FieldDefEditor, { props: { trackingMode: 'bulk' } })
    await w.get('[data-test=type]').setValue('text')
    expect(w.find('[data-test=unit-options]').exists()).toBe(false)
    await w.get('[data-test=type]').setValue('number')
    expect(w.find('[data-test=unit-options]').exists()).toBe(true)
  })

  it('requires at least one option for select', async () => {
    const w = mountWithPlugins(FieldDefEditor, { props: { trackingMode: 'bulk' } })
    await w.get('[data-test=label]').setValue('Head')
    await w.get('[data-test=type]').setValue('select')
    expect(w.get('[data-test=save]').attributes('disabled')).toBeDefined()
    await w.get('[data-test=add-option]').trigger('click')
    await w.get('[data-test=option-value-0]').setValue('hex')
    expect(w.get('[data-test=save]').attributes('disabled')).toBeUndefined()
    await w.get('[data-test=save]').trigger('click')
    const saved = w.emitted('save')![0][0] as Record<string, unknown>
    expect(saved).toMatchObject({ key: 'head', label: 'Head', type: 'select', options: [{ value: 'hex' }] })
  })

  it('hides scope for bulk categories', () => {
    expect(mountWithPlugins(FieldDefEditor, { props: { trackingMode: 'bulk' } }).find('[data-test=scope]').exists()).toBe(false)
    expect(mountWithPlugins(FieldDefEditor, { props: { trackingMode: 'unit' } }).find('[data-test=scope]').exists()).toBe(true)
  })

  it('locks the key of an existing field', () => {
    const w = mountWithPlugins(FieldDefEditor, {
      props: { trackingMode: 'bulk', initial: { key: 'length', label: 'Length', type: 'number', options: [] } },
    })
    expect(w.get('[data-test=key]').attributes('disabled')).toBeDefined()
  })
})
