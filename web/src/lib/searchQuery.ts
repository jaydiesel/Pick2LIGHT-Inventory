import type { LocationQuery, LocationQueryRaw } from 'vue-router'

export interface FilterRow {
  key: string
  op: string
  value: string
}
export interface LatestRow {
  log_type: string
  key: string
  op: string
  value: string
}
export interface SearchState {
  q: string
  category: number | null
  sub: boolean
  location: number | null
  conditions: string[]
  filters: FilterRow[]
  latest: LatestRow[]
  low: boolean
  page: number
}

const list = (v: unknown): string[] => (Array.isArray(v) ? v : v == null ? [] : [v]).map(String).filter(Boolean)
const num = (v: unknown): number | null => {
  const n = Number(Array.isArray(v) ? v[0] : v)
  return v == null || v === '' || Number.isNaN(n) ? null : n
}

function splitFilter(s: string): [string, string, string] | null {
  const a = s.indexOf(':')
  const b = a < 0 ? -1 : s.indexOf(':', a + 1)
  if (a < 0 || b < 0) return null
  return [s.slice(0, a), s.slice(a + 1, b), s.slice(b + 1)]
}

export function stateToQuery(s: SearchState): LocationQueryRaw {
  const q: LocationQueryRaw = {}
  if (s.q) q.q = s.q
  if (s.category !== null) q.category = String(s.category)
  if (!s.sub) q.sub = '0'
  if (s.location !== null) q.location = String(s.location)
  if (s.conditions.length) q.cond = s.conditions.join(',')
  if (s.filters.length) q.f = s.filters.map((f) => `${f.key}:${f.op}:${f.value}`)
  if (s.latest.length) q.latest = s.latest.map((f) => `${f.log_type}.${f.key}:${f.op}:${f.value}`)
  if (s.low) q.low = '1'
  if (s.page) q.page = String(s.page)
  return q
}

export function queryToState(q: LocationQuery | LocationQueryRaw): SearchState {
  const filters: FilterRow[] = []
  for (const raw of list(q.f)) {
    const parts = splitFilter(raw)
    if (parts) filters.push({ key: parts[0], op: parts[1], value: parts[2] })
  }
  const latest: LatestRow[] = []
  for (const raw of list(q.latest)) {
    const parts = splitFilter(raw)
    const dot = parts ? parts[0].indexOf('.') : -1
    if (parts && dot > 0) latest.push({ log_type: parts[0].slice(0, dot), key: parts[0].slice(dot + 1), op: parts[1], value: parts[2] })
  }
  return {
    q: list(q.q)[0] ?? '',
    category: num(q.category),
    sub: list(q.sub)[0] !== '0',
    location: num(q.location),
    conditions: (list(q.cond)[0] ?? '').split(',').filter(Boolean),
    filters,
    latest,
    low: list(q.low)[0] === '1',
    page: num(q.page) ?? 0,
  }
}

export function stateToSearchBody(s: SearchState, pageSize: number): Record<string, unknown> {
  return {
    q: s.q || null,
    category_id: s.category,
    include_subcategories: s.sub,
    location_id: s.location,
    conditions: s.conditions,
    filters: s.filters.filter((f) => f.key && f.value !== '').map(({ key, op, value }) => ({ key, op, value })),
    latest: s.latest.filter((f) => f.key && f.value !== '').map(({ log_type, key, op, value }) => ({ log_type, key, op, value })),
    low_stock: s.low,
    limit: pageSize,
    offset: s.page * pageSize,
  }
}
