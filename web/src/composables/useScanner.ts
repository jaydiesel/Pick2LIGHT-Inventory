import { onMounted, onUnmounted, toValue, type MaybeRefOrGetter } from 'vue'

export interface ScannerOptions {
  minLength: number
  maxGapMs: number
  prefix: string
  suffix: string
  interceptInputs: boolean
}

type TextField = HTMLInputElement | HTMLTextAreaElement

function textField(target: EventTarget | null): TextField | null {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement ? target : null
}

/**
 * Keyboard-wedge scanner detection (spec 5.1): a burst of printable keys with small gaps, ended by Enter.
 * `opts` may be a getter so settings loaded after mount take effect.
 */
export function useScanner(opts: MaybeRefOrGetter<ScannerOptions>, onScan: (code: string) => void): void {
  let buffer = ''
  let lastKeyAt = 0
  // Where the current burst started typing, so a scan that leaked into a field can be undone.
  let field: TextField | null = null
  let fieldBefore = ''

  function reset() {
    buffer = ''
    field = null
    fieldBefore = ''
  }

  function begin(ch: string, target: EventTarget | null) {
    buffer = ch
    field = textField(target)
    fieldBefore = field?.value ?? ''
  }

  function onKeyDown(e: KeyboardEvent) {
    const o = toValue(opts)
    const now = Date.now()
    const gap = now - lastKeyAt
    lastKeyAt = now

    if (e.key === 'Enter') {
      const fast = buffer.length > 0 && gap <= o.maxGapMs
      let code = buffer
      const started = field
      const before = fieldBefore
      reset()
      if (!fast || code.length < o.minLength) return
      if (o.prefix) {
        if (!code.startsWith(o.prefix)) return
        code = code.slice(o.prefix.length)
      }
      if (o.suffix && code.endsWith(o.suffix)) code = code.slice(0, -o.suffix.length)
      if (!code) return

      e.preventDefault()
      if (started && o.interceptInputs && !started.hasAttribute('data-scan-target')) {
        started.value = before
        started.dispatchEvent(new Event('input', { bubbles: true }))
      }
      onScan(code)
      return
    }

    if (e.key.length !== 1 || e.ctrlKey || e.metaKey || e.altKey) {
      // Shift alone is part of typing capitals; any other non-printable key breaks a burst.
      if (e.key !== 'Shift') reset()
      return
    }
    if (buffer && gap <= o.maxGapMs) buffer += e.key
    else begin(e.key, e.target)
  }

  onMounted(() => window.addEventListener('keydown', onKeyDown, true))
  onUnmounted(() => window.removeEventListener('keydown', onKeyDown, true))
}
