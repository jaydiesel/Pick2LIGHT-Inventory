import { describe, expect, it } from 'vitest'

import vectors from '../../../shared/si-vectors.json'
import { formatQuantity, parseQuantity } from './si'

describe('parseQuantity', () => {
  it.each(vectors.parse as [string, string, number][])('parses %s (%s)', (text, unit, expected) => {
    expect(parseQuantity(text, unit)).toBeCloseTo(expected, 12)
    expect(Math.abs(parseQuantity(text, unit) - expected)).toBeLessThanOrEqual(Math.abs(expected) * 1e-12)
  })

  it.each(vectors.parse_errors as [string, string][])('rejects %s', (text, unit) => {
    expect(() => parseQuantity(text, unit)).toThrow()
  })

  it('tells the user to use a dot', () => {
    expect(() => parseQuantity('4,7k', 'Ω')).toThrow(/dot/)
  })

  it('accepts only plain numbers without prefixes', () => {
    expect(() => parseQuantity('4.7k', 'Ω', false)).toThrow()
    expect(parseQuantity('4700', 'Ω', false)).toBe(4700)
  })
})

describe('formatQuantity', () => {
  it.each(vectors.format as [number, string | null, number | null, string][])(
    'formats %s %s',
    (value, unit, decimals, expected) => {
      expect(formatQuantity(value, unit, decimals ?? undefined)).toBe(expected)
    },
  )
})
