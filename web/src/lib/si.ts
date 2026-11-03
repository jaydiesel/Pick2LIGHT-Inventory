// TypeScript port of server/pick2light/core/si.py — both must pass shared/si-vectors.json.

const MICRO = 'µ' // U+00B5 for display
const FACTORS: Record<string, number> = { p: 1e-12, n: 1e-9, u: 1e-6, μ: 1e-6, m: 1e-3, k: 1e3, M: 1e6, G: 1e9 }
const EXP_TO_PREFIX: Record<number, string> = { [-12]: 'p', [-9]: 'n', [-6]: MICRO, [-3]: 'm', 0: '', 3: 'k', 6: 'M', 9: 'G' }
const OHM = 'Ω' // U+03A9
const PLAIN = /^[+-]?\d+(?:\.\d+)?$/
const SUFFIX = /^([+-]?\d+(?:\.\d+)?)\s*([pnuμmkMGR])?$/
const INFIX = /^([+-]?\d+)([pnuμmkMGR])(\d+)$/

const norm = (s: string | null | undefined) => (s ?? '').normalize('NFKC')

function stripUnit(s: string, unit: string): string {
  if (unit && s.endsWith(unit)) return s.slice(0, -unit.length).trimEnd()
  if (unit === OHM) {
    const lower = s.toLowerCase()
    for (const alias of ['ohms', 'ohm']) if (lower.endsWith(alias)) return s.slice(0, -alias.length).trimEnd()
  }
  return s
}

function factor(prefix: string | undefined, unit: string): number {
  if (!prefix) return 1
  if (prefix === 'R') {
    if (unit !== OHM) throw new Error('R is only valid for resistance values')
    return 1
  }
  return FACTORS[prefix]
}

export function parseQuantity(text: string, unit: string | null, allowPrefixes = true): number {
  const u = norm(unit)
  let s = norm(text).trim()
  if (!s) throw new Error('Enter a number')
  if (s.includes(',')) throw new Error('Use a dot as the decimal separator (4.7, not 4,7)')
  s = stripUnit(s, u)
  if (PLAIN.test(s)) return Number(s)
  if (!allowPrefixes) throw new Error('Enter a plain number')
  let m = SUFFIX.exec(s)
  if (m) return Number(m[1]) * factor(m[2], u)
  m = INFIX.exec(s)
  if (m) return Number(`${m[1]}.${m[3]}`) * factor(m[2], u)
  throw new Error(`Not a valid number: ${text}`)
}

function num(value: number, decimals?: number): string {
  const places = decimals ?? 6
  const factorPow = 10 ** places
  const rounded = Math.round(value * factorPow) / factorPow
  let text = rounded.toFixed(places)
  if (text.includes('.')) text = text.replace(/0+$/, '').replace(/\.$/, '')
  return text === '-0' || text === '' ? '0' : text
}

function split(value: number, decimals?: number): [string, string] {
  let exp = Math.floor(Math.log10(Math.abs(value)) / 3) * 3
  exp = Math.max(-12, Math.min(9, exp))
  let mantissa = value / 10 ** exp
  const places = decimals ?? 6
  if (Math.abs(Math.round(mantissa * 10 ** places) / 10 ** places) >= 1000 && exp < 9) {
    exp += 3
    mantissa = value / 10 ** exp
  }
  return [num(mantissa, decimals), EXP_TO_PREFIX[exp]]
}

export function formatQuantity(value: number, unit: string | null, decimals?: number, usePrefixes = true): string {
  const u = unit ?? ''
  if (!usePrefixes || value === 0) return num(value, decimals) + u
  const [mantissa, prefix] = split(value, decimals)
  return `${mantissa}${prefix}${u}`
}
