import { describe, expect, it } from 'vitest'
import vectors from '../../../shared/si-vectors.json'
import { formatQuantity, parseQuantity } from './si'

type ParseCase = [string, string | null, number]
type FormatCase = [number, string | null, number | null, string]

describe('parseQuantity', () => {
  it.each(vectors.parse as ParseCase[])('parses %j', (text, unit, expected) => {
    expect(parseQuantity(text, unit)).toBe(expected)
  })

  it.each(vectors.parse_errors as [string, string][])('rejects %j', (text, unit) => {
    expect(() => parseQuantity(text, unit)).toThrow(Error)
  })

  it('rejects prefixes when they are not allowed', () => {
    expect(() => parseQuantity('4k7', 'Ω', false)).toThrow('plain number')
    expect(parseQuantity('3000', 'mAh', false)).toBe(3000)
  })
})

describe('formatQuantity', () => {
  it.each(vectors.format as FormatCase[])('formats %j', (value, unit, decimals, expected) => {
    expect(formatQuantity(value, unit, decimals ?? undefined)).toBe(expected)
  })

  it('can skip prefixes', () => {
    expect(formatQuantity(4700, 'Ω', undefined, false)).toBe('4700Ω')
  })
})
