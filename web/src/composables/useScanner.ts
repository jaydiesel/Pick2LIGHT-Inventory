import { onMounted, onUnmounted, toValue, type MaybeRefOrGetter } from 'vue'

export interface ScannerOptions {
  minLength: number
  maxGapMs: number
  prefix: string
  suffix: string
  interceptInputs: boolean
}

type TextField = HTMLInputElement | HTMLTextAreaElement

const TEXT_INPUT_TYPES = new Set(['text', 'search', 'email', 'url', 'tel', 'number', 'password'])

/** Only text-like fields can have leaked characters removed. Contenteditable elements are not handled. */
function textField(target: EventTarget | null): TextField | null {
  if (target instanceof HTMLTextAreaElement) return target
  if (target instanceof HTMLInputElement && TEXT_INPUT_TYPES.has(target.type)) return target
  return null
}

/** Caret of a field; `number` inputs throw or report null, in which case there is nothing to restore. */
function caretOf(f: TextField): [number, number] | null {
  try {
    return f.selectionStart === null || f.selectionEnd === null ? null : [f.selectionStart, f.selectionEnd]
  } catch {
    return null
  }
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
  let caretBefore: [number, number] | null = null

  function reset() {
    buffer = ''
    field = null
    fieldBefore = ''
    caretBefore = null
  }

  function begin(ch: string, target: EventTarget | null) {
    buffer = ch
    field = textField(target)
    fieldBefore = field?.value ?? ''
    caretBefore = field ? caretOf(field) : null
  }

  function onKeyDown(e: KeyboardEvent) {
    const o = toValue(opts)
    const now = Date.now()
    const gap = now - lastKeyAt
    lastKeyAt = now

    if (e.key === 'Enter') {
      // Gaps are checked between characters only: many scanners pause before the terminator.
      let code = buffer
      const started = field
      const before = fieldBefore
      const caret = caretBefore
      reset()
      if (code.length < o.minLength) return
      if (o.prefix) {
        if (!code.startsWith(o.prefix)) return
        code = code.slice(o.prefix.length)
      }
      if (o.suffix && code.endsWith(o.suffix)) code = code.slice(0, -o.suffix.length)
      if (!code) return

      e.preventDefault()
      if (started && o.interceptInputs && !started.hasAttribute('data-scan-target')) {
        started.value = before
        if (caret) {
          try {
            started.setSelectionRange(caret[0], caret[1])
          } catch {
            // input types without selection support
          }
        }
        started.dispatchEvent(new Event('input', { bubbles: true }))
      }
      onScan(code)
      return
    }

    if (e.key === 'Shift') {
      // Part of typing capitals; it must not count as a gap-resetting key or leave a stale timestamp.
      lastKeyAt = now - gap
      return
    }
    // ctrl+alt together is AltGr on Windows, which produces printable characters.
    const altGr = e.ctrlKey && e.altKey
    if (e.key.length !== 1 || e.metaKey || ((e.ctrlKey || e.altKey) && !altGr)) {
      reset()
      return
    }
    if (buffer && gap <= o.maxGapMs) buffer += e.key
    else begin(e.key, e.target)
  }

  onMounted(() => window.addEventListener('keydown', onKeyDown, true))
  onUnmounted(() => window.removeEventListener('keydown', onKeyDown, true))
}
