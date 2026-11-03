import { onBeforeUnmount, onMounted } from 'vue'

export interface ScannerOptions {
  minLength: number
  maxGapMs: number
  prefix: string
  suffix: string
  interceptInputs: boolean
}

type Field = HTMLInputElement | HTMLTextAreaElement

function asField(el: EventTarget | Element | null): Field | null {
  return el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement ? el : null
}

/**
 * Detect barcode scanners that "type" a code: ≥ minLength characters, each within maxGapMs of the
 * previous one, ending with Enter (spec §5.1). Human typing is far slower, so it passes through.
 */
export function createScanDetector(getOptions: () => ScannerOptions, onScan: (code: string) => void) {
  let buffer = ''
  let last = 0
  let field: Field | null = null
  let startValue = ''

  function reset() {
    buffer = ''
    field = null
  }

  function handle(ev: KeyboardEvent) {
    const opts = getOptions()
    const now = Date.now()
    const gap = now - last
    if (ev.key === 'Enter') {
      const qualifies = buffer.length >= opts.minLength && gap <= opts.maxGapMs
      const target = field
      const text = buffer
      reset()
      last = now
      if (!qualifies) return
      let code = text
      if (opts.prefix) {
        if (!code.startsWith(opts.prefix)) return
        code = code.slice(opts.prefix.length)
      }
      if (opts.suffix && code.endsWith(opts.suffix)) code = code.slice(0, -opts.suffix.length)
      code = code.trim()
      if (code.length === 0) return
      const isScanTarget = target?.hasAttribute('data-scan-target') ?? false
      if (target && !isScanTarget && !opts.interceptInputs) return
      ev.preventDefault()
      ev.stopPropagation()
      if (target && !isScanTarget) {
        target.value = startValue
        target.dispatchEvent(new Event('input', { bubbles: true }))
      }
      onScan(code)
      return
    }
    if (ev.key.length !== 1 || ev.ctrlKey || ev.metaKey || ev.altKey) {
      if (ev.key !== 'Shift') reset()
      return
    }
    if (!buffer || gap > opts.maxGapMs) {
      buffer = ev.key
      field = asField(ev.target) ?? asField(document.activeElement)
      startValue = field?.value ?? ''
    } else {
      buffer += ev.key
    }
    last = now
  }

  return { handle, reset }
}

export function useScanner(options: ScannerOptions | (() => ScannerOptions), onScan: (code: string) => void) {
  const getOptions = typeof options === 'function' ? options : () => options
  const detector = createScanDetector(getOptions, onScan)
  onMounted(() => window.addEventListener('keydown', detector.handle, true))
  onBeforeUnmount(() => window.removeEventListener('keydown', detector.handle, true))
  return detector
}
