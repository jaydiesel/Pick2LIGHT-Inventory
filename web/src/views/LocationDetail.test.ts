import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import LocationDetail from './LocationDetail.vue'

const toastAdd = vi.fn()
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: toastAdd }) }))

const loc = {
  id: 5, parent_id: 2, location_type_id: 1, name: 'Drawer 3', code: 'LOC-0005', notes: 'Small parts',
  photo_attachment_id: null, light_children: 'inherit', grid_row: null, grid_col: null,
  created_at: '', updated_at: '', type_name: 'Drawer',
  path: [{ id: 1, name: 'Garage', code: 'LOC-0001' }, { id: 2, name: 'Cabinet', code: 'LOC-0002' }],
}
const tree = [{ id: 1, name: 'Garage', code: 'LOC-0001', parent_id: null, location_type_id: null, type_name: null, children: [
  { id: 2, name: 'Cabinet', code: 'LOC-0002', parent_id: 1, location_type_id: null, type_name: null, children: [
    { id: 5, name: 'Drawer 3', code: 'LOC-0005', parent_id: 2, location_type_id: 1, type_name: 'Drawer', children: [
      { id: 6, name: 'Bin A', code: 'LOC-0006', parent_id: 5, location_type_id: null, type_name: null, children: [] },
      { id: 7, name: 'Bin B', code: 'LOC-0007', parent_id: 5, location_type_id: null, type_name: null, children: [] },
    ] }] }] }]
const templates = [
  { id: 1, name: 'Item 50x30', target: 'item', width_mm: 50, height_mm: 30, dpi: 203, layout: [] },
  { id: 2, name: 'Location 50x30', target: 'location', width_mm: 50, height_mm: 30, dpi: 203, layout: [] },
]
const sheets = [{ id: 'a4-3x8', name: 'A4 3x8', cols: 3, rows: 8 }, { id: 'letter-3x10', name: 'Letter 3x10', cols: 3, rows: 10 }]

describe('LocationDetail', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  const open = vi.fn()

  beforeEach(() => {
    toastAdd.mockClear()
    open.mockReset()
    setActivePinia(createPinia())
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const json = (b: unknown, status = 200) =>
        new Response(JSON.stringify(b), { status, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/labels/pdf')) {
        const body = JSON.parse(init!.body as string)
        if (body.sheet_id) return json({ error: 'validation', message: 'bad', fields: { sheet_id: 'Label is larger than the sheet cell' } }, 422)
        return new Response(new Blob(['%PDF'], { type: 'application/pdf' }), { status: 200, headers: { 'content-type': 'application/pdf' } })
      }
      if (url.endsWith('/locations/tree')) return json(tree)
      if (url.endsWith('/locations/5')) return json(loc)
      if (url.endsWith('/search')) return json({ hits: [{ id: 9, name: 'Resistor 10k', sku: 'RES-0001', category_id: 1, category_name: 'Resistors', on_hand: 40, min_stock: null, attrs_display: {}, matched_unit_id: null, rank: 1 }], total: 1 })
      if (url.includes('/attachments?')) return json([])
      if (url.endsWith('/label-templates')) return json(templates)
      if (url.endsWith('/label-sheets')) return json(sheets)
      return json({})
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('open', open)
    URL.createObjectURL = vi.fn(() => 'blob:pdf')
    URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => vi.unstubAllGlobals())

  async function mountPage() {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/locations/:id', component: LocationDetail }, { path: '/locations', component: { template: '<div/>' } }, { path: '/items/:id', component: { template: '<div/>' } }],
    })
    await router.push('/locations/5')
    const wrapper = mount(LocationDetail, { global: { plugins: [PrimeVue, router] } })
    await flushPromises()
    return wrapper
  }

  it('shows breadcrumb from path', async () => {
    const w = await mountPage()
    const crumbs = w.get('[data-test=breadcrumb]').text()
    expect(crumbs).toContain('Garage')
    expect(crumbs).toContain('Cabinet')
    expect(crumbs).toContain('Drawer 3')
    expect(w.text()).toContain('LOC-0005')
    expect(w.text()).toContain('Small parts')
    expect(w.text()).toContain('Resistor 10k')
    const search = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/search'))!
    expect(JSON.parse(search[1].body)).toMatchObject({ location_id: 5 })
  })

  it('print label opens the tab synchronously and loads the PDF with the location template', async () => {
    const tab = { location: '', close: vi.fn() }
    open.mockReturnValue(tab)
    const w = await mountPage()
    await w.get('[data-test=print-label]').trigger('click')
    expect(open).toHaveBeenCalledWith('', '_blank')
    await flushPromises()
    const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/labels/pdf'))!
    expect(JSON.parse(call[1].body)).toMatchObject({ template_id: 2, target_type: 'location', ids: [5] })
    expect(tab.location).toBe('blob:pdf')
  })

  it('print labels for children shows the server sheet error', async () => {
    const tab = { location: '', close: vi.fn() }
    open.mockReturnValue(tab)
    const w = await mountPage()
    await w.get('[data-test=print-children]').trigger('click')
    await flushPromises()
    await w.get('[data-test=print-children-go]').trigger('click')
    await flushPromises()
    const call = fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/labels/pdf')).at(-1)!
    expect(JSON.parse(call[1].body)).toMatchObject({ ids: [6, 7], sheet_id: 'a4-3x8', start_position: 0 })
    expect(tab.close).toHaveBeenCalled()
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ summary: 'Label is larger than the sheet cell' }))
  })
})
