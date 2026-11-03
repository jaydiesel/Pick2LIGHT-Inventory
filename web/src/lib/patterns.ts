// Client-side helpers for field keys and the SKU pattern preview. The preview is an
// approximation of server/pick2light/core/sku.py and is always labelled "Preview" in the UI.
import type { components } from '../api/schema'
import { formatQuantity, parseQuantity } from './si'

type FieldOption = components['schemas']['FieldOption']

/** Same pattern as the server's KEY_PATTERN (core/categories.py). */
export const KEY_RE = /^[a-z][a-z0-9_]{0,62}$/
export const DEFAULT_SKU_PATTERN = '{prefix}-{seq:4}'
export const DEFAULT_UNIT_PATTERN = '{prefix}{seq:4}'

/** Turn a label into a field key that satisfies KEY_RE (or '' when nothing usable is left). */
export function slugify(label: string): string {
  let key = label
    .replace(/ß/g, 'ss')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (key && !/^[a-z]/.test(key)) key = `f_${key}`
  return key.slice(0, 63).replace(/_+$/, '')
}

export interface PreviewField {
  key: string
  type: string
  number_unit?: string | null
  decimals?: number | null
  options?: FieldOption[] | null
}

export interface PreviewInput {
  prefix: string
  examples: Record<string, string>
  fields: PreviewField[]
  /** Stands in for the parent item's SKU in unit-code patterns. */
  sku?: string
  seq?: number
}

const TOKEN_RE = /\{(\w+)(?::(\d+))?(?:\|(\w+))?\}/g

function sanitize(text: string): string {
  return text
    .replace(/[µμ]/g, 'u')
    .replace(/[^A-Za-z0-9._-]/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '')
}

function renderField(raw: string, spec: PreviewField | undefined, modifier: string | undefined): string {
  const value = raw.trim()
  if (!value) return ''
  if (spec?.type === 'number') {
    try {
      const n = parseQuantity(value, spec.number_unit ?? null)
      return formatQuantity(n, null, spec.decimals ?? undefined, modifier === 'si')
    } catch {
      return value
    }
  }
  let text = value
  if (spec && (spec.type === 'select' || spec.type === 'multi_select')) {
    const option = spec.options?.find((o) => o.value === value || o.label === value)
    text = option ? option.sku_code || option.value : value
  }
  if (modifier === 'lower') return text.toLowerCase()
  if (modifier === 'si') return text
  return text.toUpperCase()
}

/** Render `pattern` using the example values; mirrors the server's rendering rules. */
export function renderPreview(pattern: string, input: PreviewInput): string {
  const byKey = new Map(input.fields.map((f) => [f.key, f]))
  const rendered = pattern
    .replace(TOKEN_RE, (_m, key: string, width: string | undefined, modifier: string | undefined) => {
      if (key === 'prefix') return input.prefix
      if (key === 'sku') return input.sku ?? 'SKU'
      if (key === 'seq') return String(input.seq ?? 1).padStart(Number(width ?? 0), '0')
      return renderField(input.examples[key] ?? '', byKey.get(key), modifier)
    })
    .replace(/([-_.])[-_.]+/g, '$1')
    .replace(/^[-_.]+|[-_.]+$/g, '')
  return sanitize(rendered)
}
