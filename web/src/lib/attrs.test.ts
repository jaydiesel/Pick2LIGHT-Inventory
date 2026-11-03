import { describe, expect, it } from 'vitest'

import { attrsPatch } from './attrs'

describe('attrsPatch', () => {
  it('sends only changed keys that still have a field', () => {
    const original = { value: 1, old: 'x', tags: ['a'] }
    const current = { value: 2, old: 'x', tags: ['a'] }
    expect(attrsPatch(original, current, ['value', 'tags'])).toEqual({ value: 2 })
  })

  it('sends null for cleared fields', () => {
    expect(attrsPatch({ value: 1, note: 'n' }, { note: 'n' }, ['value', 'note'])).toEqual({ value: null })
  })

  it('never sends keys of removed fields, even if present in the form', () => {
    expect(attrsPatch({}, { removed: 'x', value: 3 }, ['value'])).toEqual({ value: 3 })
  })

  it('compares lists and objects by value', () => {
    expect(attrsPatch({ tags: ['a', 'b'] }, { tags: ['a', 'b'] }, ['tags'])).toEqual({})
  })
})
