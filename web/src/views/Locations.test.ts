import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import Locations from './Locations.vue'

const toastAdd = vi.fn()
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: toastAdd }) }))

const tree = [{ id: 1, name: 'Garage', code: 'LOC-0001', parent_id: null, location_type_id: null, type_name: null, children: [] }]

describe('Locations', () => {
  beforeEach(() => {
    toastAdd.mockClear()
    localStorage.clear()
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const json = (b: unknown, status = 200) =>
        new Response(JSON.stringify(b), { status, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/locations/1') && init?.method === 'DELETE') {
        return json({ error: 'conflict', message: 'Location still holds stock.' }, 409)
      }
      if (url.endsWith('/locations/tree')) return json(tree)
      return json([])
    }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('delete conflict shows server message', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: Locations }, { path: '/locations/:id', component: { template: '<div/>' } }] })
    await router.push('/')
    const w = mount(Locations, { global: { plugins: [PrimeVue, router] }, attachTo: document.body })
    await flushPromises()
    await w.get('[data-test=delete-1]').trigger('click')
    await flushPromises()
    ;(document.body.querySelector('[data-test=confirm-delete]') as HTMLElement).click()
    await flushPromises()
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: 'error', summary: 'Location still holds stock.' }))
    w.unmount()
  })
})
