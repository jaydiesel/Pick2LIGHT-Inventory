import { describe, expect, it } from 'vitest'

import { mountWithPlugins } from '@/test-utils'

import LocationTree from './LocationTree.vue'

const NODES = [
  {
    id: 1, name: 'Garage', code: 'LOC-0001', type_name: 'Room',
    children: [{ id: 2, name: 'Cabinet', code: 'LOC-0002', type_name: null, children: [{ id: 3, name: 'A1', code: 'LOC-0003', type_name: 'Drawer', children: [] }] }],
  },
  { id: 4, name: 'Office', code: 'LOC-0004', type_name: null, children: [] },
]

describe('LocationTree', () => {
  it('renders nested nodes and emits select', async () => {
    const w = mountWithPlugins(LocationTree, { props: { nodes: NODES } })
    expect(w.text()).toContain('Garage')
    expect(w.text()).toContain('A1')
    await w.get('[data-test=location-3] .name').trigger('click')
    expect(w.emitted('select')![0]).toEqual([3])
  })

  it('collapses a branch', async () => {
    const w = mountWithPlugins(LocationTree, { props: { nodes: NODES } })
    await w.get('[data-test=toggle-1]').trigger('click')
    expect(w.text()).not.toContain('Cabinet')
    expect(w.text()).toContain('Office')
  })
})
