import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LocationTree from './LocationTree.vue'

const node = (id: number, name: string, children: unknown[] = []) => ({
  id, name, code: `LOC-${id}`, parent_id: null, location_type_id: null, type_name: null, children,
})
const nodes = [node(1, 'Garage', [node(2, 'Cabinet', [node(4, 'Drawer')])]), node(3, 'Office')] as never[]

describe('LocationTree', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('renders nested nodes and emits select', async () => {
    const w = mount(LocationTree, { props: { nodes, selectable: true } })
    expect(w.findAll('[data-depth]').map((b) => b.attributes('data-depth'))).toEqual(['0', '1', '2', '0'])
    expect(w.get('[data-test=loc-4]').text()).toContain('Drawer')
    await w.get('[data-test=loc-2]').trigger('click')
    expect(w.emitted('select')![0]).toEqual([2])
  })

  it('does not emit select when not selectable', async () => {
    const w = mount(LocationTree, { props: { nodes } })
    await w.get('[data-test=loc-2]').trigger('click')
    expect(w.emitted('select')).toBeUndefined()
  })

  it('collapses a node and remembers it in localStorage', async () => {
    const w = mount(LocationTree, { props: { nodes } })
    await w.get('[data-test=toggle-1]').trigger('click')
    expect(w.find('[data-test=loc-2]').exists()).toBe(false)
    expect(w.find('[data-test=loc-3]').exists()).toBe(true)
    w.unmount()
    const again = mount(LocationTree, { props: { nodes } })
    expect(again.find('[data-test=loc-2]').exists()).toBe(false)
  })

  it('works when localStorage throws', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    const w = mount(LocationTree, { props: { nodes } })
    expect(w.find('[data-test=loc-4]').exists()).toBe(true)
    await w.get('[data-test=toggle-1]').trigger('click')
    expect(w.find('[data-test=loc-2]').exists()).toBe(false)
  })
})
