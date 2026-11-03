import { describe, expect, it } from 'vitest'

import { type SearchState, queryToState, stateToQuery, stateToSearchBody } from '@/lib/searchQuery'

const STATE: SearchState = {
  q: '10k',
  category: 3,
  sub: true,
  location: 5,
  conditions: ['faulty', 'tested_good'],
  filters: [{ key: 'resistance', op: 'lt', value: '5k' }],
  latest: [{ log_type: 'capacity_test', key: 'ir_mohm', op: 'lt', value: '30' }],
  low: true,
  page: 2,
}

describe('search URL state', () => {
  it('serializes filters into URL and back', () => {
    const query = stateToQuery(STATE)
    expect(query.f).toEqual(['resistance:lt:5k'])
    expect(query.latest).toEqual(['capacity_test.ir_mohm:lt:30'])
    expect(queryToState(query)).toEqual(STATE)
  })

  it('keeps colons inside values', () => {
    const state: SearchState = { ...queryToState({}), filters: [{ key: 'note', op: 'contains', value: 'a:b' }] }
    expect(queryToState(stateToQuery(state)).filters).toEqual(state.filters)
  })

  it('builds the API body with paging', () => {
    const body = stateToSearchBody(STATE, 50)
    expect(body).toMatchObject({ q: '10k', category_id: 3, include_subcategories: true, location_id: 5, low_stock: true, limit: 50, offset: 100 })
    expect(body.filters).toEqual([{ key: 'resistance', op: 'lt', value: '5k' }])
  })

  it('has empty defaults', () => {
    expect(queryToState({})).toEqual({ q: '', category: null, sub: true, location: null, conditions: [], filters: [], latest: [], low: false, page: 0 })
  })
})
