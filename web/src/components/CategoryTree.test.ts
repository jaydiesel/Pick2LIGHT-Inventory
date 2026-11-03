import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CategoryTree from './CategoryTree.vue'

const categories = [
  { id: 1, name: 'Electronics', parent_id: null },
  { id: 2, name: 'Resistors', parent_id: 1 },
  { id: 3, name: 'Tools', parent_id: null },
] as never[]

describe('CategoryTree', () => {
  it('indents children under their parent and emits select', async () => {
    const w = mount(CategoryTree, { props: { categories, selectedId: 2 } })
    expect(w.findAll('button').map((b) => b.attributes('data-depth'))).toEqual(['0', '1', '0'])
    expect(w.findAll('button').map((b) => b.text())).toEqual(['Electronics', 'Resistors', 'Tools'])
    expect(w.get('[data-test=cat-2]').classes()).toContain('selected')
    await w.get('[data-test=cat-3]').trigger('click')
    expect(w.emitted('select')![0]).toEqual([3])
  })
  it('does not emit for disabled ids', async () => {
    const w = mount(CategoryTree, { props: { categories, disabledIds: [3] } })
    await w.get('[data-test=cat-3]').trigger('click')
    expect(w.emitted('select')).toBeUndefined()
  })
})
