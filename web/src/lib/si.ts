// Engineering-unit parsing and formatting. Faithful port of server/pick2light/core/si.py;
// both are checked against shared/si-vectors.json. Decimal arithmetic is done on
// BigInt coefficients so results never pick up binary floating-point artefacts.

const OHM = 'Ω' // Ω after NFKC (U+2126 OHM SIGN folds to this)
const MICRO_GREEK = 'μ' // μ after NFKC (U+00B5 MICRO SIGN folds to this)
const MICRO_DISPLAY = 'µ' // what we show to users

const PREFIX_EXP: Record<string, number> = {
  p: -12,
  n: -9,
  u: -6,
  [MICRO_GREEK]: -6,
  m: -3,
  k: 3,
  M: 6,
  G: 9,
}
const EXP_SYMBOL: Record<number, string> = {
  [-12]: 'p',
  [-9]: 'n',
  [-6]: MICRO_DISPLAY,
  [-3]: 'm',
  0: '',
  3: 'k',
  6: 'M',
  9: 'G',
}
const MIN_EXP = -12
const MAX_EXP = 9

const NUM = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d{1,3})?'
const NUM_LEAD_RE = new RegExp(`^${NUM}`)
const PLAIN_RE = new RegExp(`^(${NUM})\\s*([pnu${MICRO_GREEK}mkMG])?$`)
const INFIX_RE = new RegExp(`^([+-]?\\d+)([pnu${MICRO_GREEK}mkMGR])(\\d+)$`)

/** value = coef * 10 ** exp */
interface Dec {
  coef: bigint
  exp: number
}

const nfkc = (text: string): string => text.normalize('NFKC')

function displayUnit(unit: string | null | undefined): string {
  return unit ? nfkc(unit).replaceAll(MICRO_GREEK, MICRO_DISPLAY) : ''
}

function decFromString(text: string): Dec {
  const m = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text)
  if (!m) throw new Error(`Not a decimal: ${text}`)
  const frac = m[3] ?? ''
  const coef = BigInt((m[2] + frac) || '0')
  return { coef: m[1] === '-' ? -coef : coef, exp: Number(m[4] ?? 0) - frac.length }
}

const digitCount = (n: bigint): number => (n < 0n ? -n : n).toString().length

/** Exponent of the most significant digit (Decimal.adjusted()). */
const adjusted = (d: Dec): number => d.exp + digitCount(d.coef) - 1

const abs = (n: bigint): bigint => (n < 0n ? -n : n)

/** Round to `places` decimal places, ROUND_HALF_UP (half away from zero). */
function quantize(d: Dec, places: number): Dec {
  const target = -places
  if (d.exp >= target) return { coef: d.coef * 10n ** BigInt(d.exp - target), exp: target }
  const divisor = 10n ** BigInt(target - d.exp)
  const a = abs(d.coef)
  let q = a / divisor
  if ((a % divisor) * 2n >= divisor) q += 1n
  return { coef: d.coef < 0n ? -q : q, exp: target }
}

/** |d| >= limit (a whole number). */
function atLeast(d: Dec, limit: bigint): boolean {
  const a = abs(d.coef)
  return d.exp >= 0 ? a * 10n ** BigInt(d.exp) >= limit : a >= limit * 10n ** BigInt(-d.exp)
}

/** Plain decimal text without exponent or trailing zeros. */
function digits(d: Dec): string {
  if (d.coef === 0n) return '0'
  let coef = abs(d.coef)
  let exp = d.exp
  while (coef % 10n === 0n) {
    coef /= 10n
    exp += 1
  }
  const sign = d.coef < 0n ? '-' : ''
  let s = coef.toString()
  if (exp >= 0) return sign + s + '0'.repeat(exp)
  const places = -exp
  if (s.length <= places) s = '0'.repeat(places - s.length + 1) + s
  return `${sign}${s.slice(0, s.length - places)}.${s.slice(s.length - places)}`
}

function stripUnit(text: string, unit: string): string {
  if (unit === OHM) {
    const lowered = text.toLowerCase()
    for (const alias of ['ohms', 'ohm']) {
      if (lowered.endsWith(alias)) return text.slice(0, -alias.length).trimEnd()
    }
    if (text.endsWith('R') || text.endsWith(OHM)) return text.slice(0, -1).trimEnd()
  } else if (unit && text.endsWith(unit)) {
    return text.slice(0, -unit.length).trimEnd()
  }
  return text
}

/** Parse a number typed by a user into the base unit. Throws `Error`. */
export function parseQuantity(text: string, unit: string | null, allowPrefixes = true): number {
  const cleaned = nfkc(text).trim()
  if (!cleaned) throw new Error('Enter a number.')
  if (cleaned.includes(',')) throw new Error('Use a dot for decimals, not a comma.')
  const baseUnit = unit ? nfkc(unit) : ''
  const body = stripUnit(cleaned, baseUnit)

  let mantissa: string
  let exponent: number
  let usedPrefix: boolean
  const plain = PLAIN_RE.exec(body)
  const infix = INFIX_RE.exec(body)
  if (plain) {
    mantissa = plain[1]
    const symbol = plain[2]
    exponent = symbol ? PREFIX_EXP[symbol] : 0
    usedPrefix = Boolean(symbol)
  } else if (infix && (infix[2] !== 'R' || baseUnit === OHM)) {
    mantissa = `${infix[1]}.${infix[3]}`
    exponent = PREFIX_EXP[infix[2]] ?? 0
    usedPrefix = true
  } else {
    const lead = NUM_LEAD_RE.exec(body)
    const rest = lead ? body.slice(lead[0].length).trim() : ''
    if (rest) throw new Error(`"${rest}" is not a known prefix or unit.`)
    throw new Error(`"${cleaned}" is not a number.`)
  }

  if (usedPrefix && !allowPrefixes) throw new Error('Enter a plain number, without k, m, µ etc.')

  const number = decFromString(mantissa)
  // Number() of a decimal string is correctly rounded, like Python's float(Decimal).
  const result = Number(`${number.coef}e${number.exp + exponent}`)
  if (!Number.isFinite(result)) throw new Error('Number is too large.')
  if (result === 0 && number.coef !== 0n) throw new Error('Number is too small.')
  return result + 0 // turns -0 into 0
}

/** Shortest round-trip decimal of a float (Python's `Decimal(repr(value))`). */
function exactDecimal(value: number): Dec {
  return decFromString(String(value))
}

function scale(
  value: number,
  decimals: number | undefined,
  usePrefixes: boolean,
): { mantissa: Dec; exponent: number } {
  if (!Number.isFinite(value)) throw new Error('Not a finite number.')
  if (decimals !== undefined && decimals < 0) throw new Error('decimals must be 0 or more.')
  const exact = exactDecimal(value)
  if (exact.coef === 0n) return { mantissa: { coef: 0n, exp: 0 }, exponent: 0 }
  let exponent = 0
  if (usePrefixes) {
    exponent = Math.max(MIN_EXP, Math.min(MAX_EXP, Math.floor(adjusted(exact) / 3) * 3))
  }
  const shifted = (e: number): Dec => ({ coef: exact.coef, exp: exact.exp - e })
  let mantissa = shifted(exponent)
  if (decimals !== undefined) {
    mantissa = quantize(mantissa, decimals)
    if (usePrefixes && atLeast(mantissa, 1000n) && exponent < MAX_EXP) {
      exponent += 3 // rounding carried over, e.g. 999.9999 -> 1k
      mantissa = quantize(shifted(exponent), decimals)
    }
  }
  return { mantissa, exponent }
}

/** Format `value` (base unit) for display, e.g. `4.7kΩ`. Throws `Error`. */
export function formatQuantity(
  value: number,
  unit: string | null,
  decimals?: number,
  usePrefixes = true,
): string {
  const { mantissa, exponent } = scale(value, decimals, usePrefixes)
  return `${digits(mantissa)}${EXP_SYMBOL[exponent]}${displayUnit(unit)}`
}
