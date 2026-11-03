import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { useScanner, type ScannerOptions } from './useScanner'

const base: ScannerOptions = { minLength: 4, maxGapMs: 30, prefix: '', suffix: '', interceptInputs: true }

describe('useScanner', () => {
  let wrapper: VueWrapper | undefined
  let onScan: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    onScan = vi.fn()
  })
  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    document.body.innerHTML = ''
    vi.useRealTimers()
  })

  function setup(opts: Partial<ScannerOptions> = {}) {
    wrapper = mount(
      defineComponent({
        setup() {
          useScanner({ ...base, ...opts }, onScan)
          return () => h('div')
        },
      }),
    )
  }

  /** Fire one keydown at `target`; returns the event so tests can check defaultPrevented. */
  function press(key: string, target: EventTarget = document.body, init: KeyboardEventInit = {}): KeyboardEvent {
    const ev = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
    target.dispatchEvent(ev)
    return ev
  }

  /** Type `text` (and optionally Enter) with `gap` ms between keys, appending to inputs like a real keyboard. */
  function type(text: string, gap: number, opts: { enter?: boolean; enterGap?: number; target?: HTMLInputElement } = {}) {
    const target = opts.target ?? document.body
    let last: KeyboardEvent | undefined
    for (const ch of text) {
      vi.advanceTimersByTime(gap)
      press(ch, target)
      if (opts.target) opts.target.value += ch
    }
    if (opts.enter ?? true) {
      vi.advanceTimersByTime(opts.enterGap ?? gap)
      last = press('Enter', target)
    }
    return last
  }

  it('detects fast sequence ending in Enter', () => {
    setup()
    const enter = type('ABC123', 5)
    expect(onScan).toHaveBeenCalledTimes(1)
    expect(onScan).toHaveBeenCalledWith('ABC123')
    expect(enter?.defaultPrevented).toBe(true)
  })

  it('still detects a scan when the scanner pauses before Enter', () => {
    setup()
    const enter = type('ABC123', 5, { enterGap: 80 })
    expect(onScan).toHaveBeenCalledWith('ABC123')
    expect(enter?.defaultPrevented).toBe(true)
  })

  it('does not break a burst on Shift keydowns or AltGr characters', () => {
    setup()
    for (const ch of ['A', 'B']) {
      vi.advanceTimersByTime(5)
      press('Shift')
      vi.advanceTimersByTime(5)
      press(ch, document.body, { shiftKey: true })
    }
    vi.advanceTimersByTime(5)
    press('@', document.body, { ctrlKey: true, altKey: true })
    vi.advanceTimersByTime(5)
    press('9')
    vi.advanceTimersByTime(5)
    press('Enter')
    expect(onScan).toHaveBeenCalledWith('AB@9')
  })

  it('restores the caret position along with the value', () => {
    setup()
    const input = document.createElement('input')
    input.value = 'abcd'
    document.body.appendChild(input)
    input.setSelectionRange(2, 2)
    type('ZZ9999', 5, { target: input })
    expect(input.value).toBe('abcd')
    expect([input.selectionStart, input.selectionEnd]).toEqual([2, 2])
  })

  it('does not touch non-text inputs', () => {
    setup()
    const input = document.createElement('input')
    input.type = 'checkbox'
    document.body.appendChild(input)
    const onInput = vi.fn()
    input.addEventListener('input', onInput)
    type('ZZ9999', 5, { target: input })
    expect(onScan).toHaveBeenCalledWith('ZZ9999')
    expect(onInput).not.toHaveBeenCalled()
  })

  it('ignores slow human typing', () => {
    setup()
    const enter = type('ABC123', 120)
    expect(onScan).not.toHaveBeenCalled()
    expect(enter?.defaultPrevented).toBe(false)
  })

  it('ignores short codes below minLength', () => {
    setup()
    type('AB1', 5)
    expect(onScan).not.toHaveBeenCalled()
  })

  it('strips configured prefix and suffix', () => {
    setup({ prefix: '~', suffix: '$' })
    type('~ABC123$', 5)
    expect(onScan).toHaveBeenCalledWith('ABC123')
  })

  it('requires prefix when configured', () => {
    setup({ prefix: '~' })
    type('ABC123', 5)
    expect(onScan).not.toHaveBeenCalled()
  })

  it('restores input value when intercepting', () => {
    setup()
    const input = document.createElement('input')
    input.value = 'abc'
    document.body.appendChild(input)
    const onInput = vi.fn()
    input.addEventListener('input', onInput)
    type('ZZ9999', 5, { target: input })
    expect(onScan).toHaveBeenCalledWith('ZZ9999')
    expect(input.value).toBe('abc')
    expect(onInput).toHaveBeenCalled()
  })

  it('does not restore data-scan-target input', () => {
    setup()
    const input = document.createElement('input')
    input.setAttribute('data-scan-target', '')
    document.body.appendChild(input)
    type('ZZ9999', 5, { target: input })
    expect(onScan).toHaveBeenCalledWith('ZZ9999')
    expect(input.value).toBe('ZZ9999')
  })

  it('leaves input alone when interceptInputs is false', () => {
    setup({ interceptInputs: false })
    const input = document.createElement('input')
    document.body.appendChild(input)
    type('ZZ9999', 5, { target: input })
    expect(onScan).toHaveBeenCalledWith('ZZ9999')
    expect(input.value).toBe('ZZ9999')
  })

  it('handles two scans back to back', () => {
    setup()
    type('C0001', 5)
    type('C0002', 5)
    expect(onScan.mock.calls.map((c) => c[0])).toEqual(['C0001', 'C0002'])
  })

  it('stops listening after unmount', () => {
    setup()
    wrapper?.unmount()
    wrapper = undefined
    type('ABC123', 5)
    expect(onScan).not.toHaveBeenCalled()
  })
})
