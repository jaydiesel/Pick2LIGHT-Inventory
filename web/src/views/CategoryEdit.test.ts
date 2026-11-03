import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import CategoryEdit from './CategoryEdit.vue'

const toastAdd = vi.fn()
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: toastAdd }) }))

const cat = (id: number, name: string, parent_id: number | null, extra = {}) => ({
  id, name, parent_id, icon: null, description: null, tracking_mode: null, sku_prefix: null,
  sku_pattern: null, unit_id_pattern: null, effective_tracking_mode: 'bulk', path: [], ...extra,
})
const field = (id: number, key: string, category_id: number, inherited_from: number | null) => ({
  id, category_id, key, label: key.toUpperCase(), order: id, type: 'text', required: false,
  filterable: false, show_on_label: false, number_si_prefixes: false, scope: 'item', inherited_from,
})

describe('CategoryEdit', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    toastAdd.mockClear()
    setActivePinia(createPinia())
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const json = (b: unknown, status = 200) =>
        new Response(JSON.stringify(b), { status, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/categories') ) return json([cat(1, 'Electronics', null), cat(2, 'Resistors', 1), cat(3, 'Tools', null)])
      if (url.endsWith('/categories/2/fields')) return json([field(10, 'brand', 1, 1), field(11, 'power', 2, null)])
      if (url.endsWith('/categories/2/log-types')) return json([])
      if (url.endsWith('/categories/2') && init?.method === 'PATCH') {
        return json({ error: 'conflict', message: 'Cannot move a category into its own descendant.' }, 409)
      }
      if (url.endsWith('/categories/2')) return json(cat(2, 'Resistors', 1))
      return json({})
    })
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  async function mountPage() {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/categories/:id', component: CategoryEdit }, { path: '/categories', component: { template: '<div/>' } }],
    })
    await router.push('/categories/2')
    const wrapper = mount(CategoryEdit, { global: { plugins: [PrimeVue, router] } })
    await flushPromises()
    return wrapper
  }

  it('inherited fields are read-only', async () => {
    const w = await mountPage()
    const inherited = w.get('[data-test=inherited-field-brand]')
    expect(inherited.text()).toContain('from Electronics')
    expect(inherited.find('button').exists()).toBe(false)
    expect(w.find('[data-test=edit-field-brand]').exists()).toBe(false)
    expect(w.find('[data-test=edit-field-power]').exists()).toBe(true)
  })

  it('shows server conflict message on move', async () => {
    const w = await mountPage()
    await w.get('[data-test=change-parent]').trigger('click')
    await w.get('[data-test=cat-3]').trigger('click')
    await flushPromises()
    const patch = fetchMock.mock.calls.find(([, i]) => i?.method === 'PATCH')!
    expect(JSON.parse(patch[1].body)).toEqual({ parent_id: 3 })
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: 'error', summary: 'Cannot move a category into its own descendant.' }))
  })
})
