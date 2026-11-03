import { describe, expect, it } from 'vitest'

import { mountWithPlugins } from '@/test-utils'

import SiNumberInput from './SiNumberInput.vue'

function mountInput(props: Record<string, unknown> = {}) {
  return mountWithPlugins(SiNumberInput, { props: { modelValue: null, unit: 'Ω', allowPrefixes: true, ...props } })
}

describe('SiNumberInput', () => {
  it('parses 4k7 to 4700 on blur', async () => {
    const w = mountInput()
    const input = w.get('input')
    await input.trigger('focus')
    await input.setValue('4k7')
    await input.trigger('blur')
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([4700])
  })

  it('shows error for 4,7k', async () => {
    const w = mountInput()
    const input = w.get('input')
    await input.trigger('focus')
    await input.setValue('4,7k')
    await input.trigger('blur')
    expect(w.text()).toContain('dot')
    expect(w.emitted('update:modelValue')).toBeUndefined()
  })

  it('formats on blur as 4.7kΩ', async () => {
    const w = mountInput({ modelValue: 4700 })
    expect((w.get('input').element as HTMLInputElement).value).toBe('4.7kΩ')
  })

  it('emits null when cleared', async () => {
    const w = mountInput({ modelValue: 10 })
    const input = w.get('input')
    await input.trigger('focus')
    await input.setValue('')
    await input.trigger('blur')
    expect(w.emitted('update:modelValue')!.at(-1)).toEqual([null])
  })
})
