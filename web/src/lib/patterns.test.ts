import { describe, expect, it } from 'vitest'
import { renderPreview, slugify } from './patterns'

describe('slugify', () => {
  it('produces keys matching the server regex', () => {
    expect(slugify('Internal Resistance')).toBe('internal_resistance')
    expect(slugify('  Größe (mm) ')).toBe('grosse_mm')
    expect(slugify('3D size')).toBe('f_3d_size')
    expect(slugify('!!!')).toBe('')
    expect(slugify('a'.repeat(80))).toHaveLength(63)
  })
})

describe('renderPreview', () => {
  const fields = [
    { key: 'resistance', type: 'number', number_unit: 'Ω', decimals: null, options: null },
    { key: 'head', type: 'select', number_unit: null, decimals: null, options: [{ value: 'socket', label: 'Socket', sku_code: 'SHCS' }] },
  ]
  it('renders seq, prefix, select sku codes and si numbers', () => {
    expect(renderPreview('{prefix}-{head}-{resistance|si}-{seq:4}', { prefix: 'RES', examples: { head: 'socket', resistance: '4.7k' }, fields })).toBe('RES-SHCS-4.7k-0001')
  })
  it('drops empty tokens and collapses separators', () => {
    expect(renderPreview('{prefix}-{head}-{seq:3}', { prefix: 'x', examples: {}, fields })).toBe('x-001')
  })
})
