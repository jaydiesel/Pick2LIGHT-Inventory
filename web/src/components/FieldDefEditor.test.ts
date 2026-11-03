import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Select from 'primevue/select'
import { describe, expect, it } from 'vitest'
import FieldDefEditor from './FieldDefEditor.vue'

function mountEditor(props: Record<string, unknown> = {}) {
  return mount(FieldDefEditor, { props: { scopeAllowed: false, ...props }, global: { plugins: [PrimeVue] } })
}

describe('FieldDefEditor', () => {
  it('derives key from label', async () => {
    const w = mountEditor()
    await w.get('[data-test=label]').setValue('Internal Resistance')
    expect((w.get('[data-test=key]').element as HTMLInputElement).value).toBe('internal_resistance')
  })

  it('stops deriving the key once it was edited by hand', async () => {
    const w = mountEditor()
    await w.get('[data-test=key]').setValue('ir')
    await w.get('[data-test=label]').setValue('Internal Resistance')
    expect((w.get('[data-test=key]').element as HTMLInputElement).value).toBe('ir')
  })

  it('shows unit options only for number', async () => {
    const w = mountEditor()
    expect(w.find('[data-test=number-unit]').exists()).toBe(false)
    w.findComponent(Select).vm.$emit('update:modelValue', 'number')
    await w.vm.$nextTick()
    expect(w.find('[data-test=number-unit]').exists()).toBe(true)
    expect(w.find('[data-test=number-min]').exists()).toBe(true)
    w.findComponent(Select).vm.$emit('update:modelValue', 'text')
    await w.vm.$nextTick()
    expect(w.find('[data-test=number-unit]').exists()).toBe(false)
  })

  it('requires at least one option for select', async () => {
    const w = mountEditor()
    await w.get('[data-test=label]').setValue('Head')
    w.findComponent(Select).vm.$emit('update:modelValue', 'select')
    await w.vm.$nextTick()
    expect(w.get('[data-test=save]').attributes('disabled')).toBeDefined()
    await w.get('[data-test=add-option]').trigger('click')
    await w.get('[data-test=option-value-0]').setValue('shcs')
    await w.get('[data-test=option-label-0]').setValue('Socket head')
    expect(w.get('[data-test=save]').attributes('disabled')).toBeUndefined()
    await w.get('form').trigger('submit')
    const body = w.emitted('save')![0][0] as Record<string, unknown>
    expect(body).toMatchObject({ key: 'head', type: 'select', options: [{ value: 'shcs', label: 'Socket head', sku_code: null }] })
  })

  it('hides scope for bulk categories', () => {
    expect(mountEditor({ scopeAllowed: false }).find('[data-test=scope]').exists()).toBe(false)
    expect(mountEditor({ scopeAllowed: true }).find('[data-test=scope]').exists()).toBe(true)
  })

  it('emits only changed keys when editing, with null to clear', async () => {
    const field = {
      id: 5, category_id: 1, key: 'tol', label: 'Tolerance', help_text: 'old', order: 2, type: 'text',
      required: false, filterable: false, show_on_label: false, number_si_prefixes: false, scope: 'item',
    }
    const w = mountEditor({ field })
    await w.get('[data-test=help]').setValue('')
    await w.get('[data-test=label]').setValue('Tolerance %')
    await w.get('form').trigger('submit')
    expect(w.emitted('save')![0][0]).toEqual({ label: 'Tolerance %', help_text: null })
  })
})
