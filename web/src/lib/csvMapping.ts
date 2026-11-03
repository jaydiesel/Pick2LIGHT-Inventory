import type { FieldDefOut } from '@/api/types'
import { slugKey } from '@/lib/keys'

export const BASE_TARGETS: { value: string; label: string; aliases: string[] }[] = [
  { value: 'name', label: 'Name', aliases: ['item', 'title', 'part'] },
  { value: 'sku', label: 'SKU', aliases: [] },
  { value: 'description', label: 'Description', aliases: ['desc'] },
  { value: 'notes', label: 'Notes', aliases: ['note', 'comment', 'comments'] },
  { value: 'min_stock', label: 'Minimum stock', aliases: ['min', 'minimum'] },
  { value: 'quantity', label: 'Quantity', aliases: ['qty', 'count', 'amount', 'stock', 'on_hand'] },
  { value: 'location_code', label: 'Location code', aliases: ['location', 'loc', 'bin', 'drawer'] },
  { value: 'barcode', label: 'Barcode (UPC/EAN)', aliases: ['upc', 'ean', 'gtin'] },
  { value: 'unit_code', label: 'Unit code', aliases: [] },
  { value: 'serial_number', label: 'Serial number', aliases: ['serial', 'sn'] },
  { value: 'condition', label: 'Condition', aliases: [] },
]

export function autoMap(headers: string[], specs: FieldDefOut[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const header of headers) {
    const h = header.trim().toLowerCase()
    const slug = slugKey(header)
    const base = BASE_TARGETS.find((t) => [t.value, t.label.toLowerCase(), ...t.aliases].includes(h) || t.value === slug)
    const field = specs.find((s) => s.key === h || s.key === slug || s.label.toLowerCase() === h || `attr.${s.key}` === h)
    out[header] = base ? base.value : field ? `attr.${field.key}` : 'ignore'
  }
  return out
}

/** Header row of a CSV file, using the same delimiter rule as the server (most of , ; tab). */
export function csvHeaders(text: string): string[] {
  const first = text.replace(/^﻿/, '').split(/\r?\n/).find((l) => l.trim()) ?? ''
  const delim = [',', ';', '\t'].reduce((best, d) => (first.split(d).length > first.split(best).length ? d : best), ',')
  const cells: string[] = []
  let cur = ''
  let quoted = false
  for (let i = 0; i < first.length; i++) {
    const ch = first[i]
    if (quoted) {
      if (ch === '"' && first[i + 1] === '"') {
        cur += '"'
        i++
      } else if (ch === '"') quoted = false
      else cur += ch
    } else if (ch === '"') quoted = true
    else if (ch === delim) {
      cells.push(cur.trim())
      cur = ''
    } else cur += ch
  }
  cells.push(cur.trim())
  return cells.filter((c, i) => c !== '' || i < cells.length - 1)
}
