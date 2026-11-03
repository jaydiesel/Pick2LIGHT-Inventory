import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import { type ScannerOptions, useScanner } from './useScanner'

const DEFAULTS: ScannerOptions = { minLength: 4, maxGapMs: 30, prefix: '', suffix: '', interceptInputs: true }

const mounted: { unmount: () => void }[] = []

function harness(opts: Partial<ScannerOptions> = {}) {
  const scans: string[] = []
  const Comp = defineComponent({
    setup() {
      useScanner({ ...DEFAULTS, ...opts }, (code) => scans.push(code))
      return () =>
        h('div', [h('input', { id: 'plain' }), h('input', { id: 'search', 'data-scan-target': '' })])
    },
  })
  const wrapper = mount(Comp, { attachTo: document.body })
  mounted.push(wrapper)
  return { scans, wrapper }
}

function key(k: string, target: EventTarget = window) {
  const ev = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true })
  target.dispatchEvent(ev)
  if (k.length === 1 && target instanceof HTMLInputElement && !ev.defaultPrevented) target.value += k
  return ev
}

function type(text: string, gapMs: number, target: EventTarget = window, enter = true) {
  let last: KeyboardEvent | undefined
  for (const ch of text) {
    last = key(ch, target)
    vi.advanceTimersByTime(gapMs)
  }
  if (enter) last = key('Enter', target)
  return last!
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  mounted.splice(0).forEach((w) => {
    try {
      w.unmount()
    } catch {
      /* already unmounted by the test */
    }
  })
  document.body.innerHTML = ''
})

describe('useScanner', () => {
  it('detects fast sequence ending in Enter', () => {
    const { scans } = harness()
    const enter = type('C0042', 5)
    expect(scans).toEqual(['C0042'])
    expect(enter.defaultPrevented).toBe(true)
  })

  it('ignores slow human typing', () => {
    const { scans } = harness()
    const enter = type('C0042', 120)
    expect(scans).toEqual([])
    expect(enter.defaultPrevented).toBe(false)
  })

  it('ignores short codes below minLength', () => {
    const { scans } = harness()
    type('ab1', 5)
    expect(scans).toEqual([])
  })

  it('strips configured prefix and suffix', () => {
    const { scans } = harness({ prefix: '#', suffix: '$' })
    type('#C0042$', 5)
    expect(scans).toEqual(['C0042'])
  })

  it('requires prefix when configured', () => {
    const { scans } = harness({ prefix: '#' })
    type('C0042', 5)
    expect(scans).toEqual([])
  })

  it('restores input value when intercepting', () => {
    const { scans, wrapper } = harness()
    const input = wrapper.get('#plain').element as HTMLInputElement
    input.value = 'note: '
    input.focus()
    const onInput = vi.fn()
    input.addEventListener('input', onInput)
    type('C0042', 5, input)
    expect(scans).toEqual(['C0042'])
    expect(input.value).toBe('note: ')
    expect(onInput).toHaveBeenCalled()
  })

  it('does not restore data-scan-target input', () => {
    const { scans, wrapper } = harness()
    const input = wrapper.get('#search').element as HTMLInputElement
    input.focus()
    type('C0042', 5, input)
    expect(scans).toEqual(['C0042'])
    expect(input.value).toBe('C0042')
  })

  it('leaves other inputs alone when interception is off', () => {
    const { scans, wrapper } = harness({ interceptInputs: false })
    const input = wrapper.get('#plain').element as HTMLInputElement
    input.focus()
    type('C0042', 5, input)
    expect(scans).toEqual([])
    expect(input.value).toBe('C0042')
  })

  it('handles two scans back to back', () => {
    const { scans } = harness()
    type('C0001', 5)
    vi.advanceTimersByTime(5)
    type('C0002', 5)
    expect(scans).toEqual(['C0001', 'C0002'])
  })

  it('stops listening after unmount', () => {
    const { scans, wrapper } = harness()
    wrapper.unmount()
    type('C0042', 5)
    expect(scans).toEqual([])
  })
})
