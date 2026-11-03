import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import Setup from './Setup.vue'

const packs = [
  { id: 'electronics', name: 'Electronics', description: 'e', category_count: 7 },
  { id: 'generic', name: 'Generic', description: 'g', category_count: 1 },
]

describe('Setup wizard', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    setActivePinia(createPinia())
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const json = (b: unknown) =>
        new Response(JSON.stringify(b), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.endsWith('/packs')) return json(packs)
      if (url.endsWith('/setup') && init?.method === 'POST') return json({ ok: true, categories_created: 8 })
      return json({ mode: 'password', authenticated: true, setup_completed: true })
    })
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  async function mountSetup() {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div>home</div>' } },
        { path: '/setup', component: Setup },
      ],
    })
    await router.push('/setup')
    const wrapper = mount(Setup, { global: { plugins: [PrimeVue, ToastService, router] } })
    await flushPromises()
    return { wrapper, router }
  }

  it('disables Next for short passwords and shows the hint', async () => {
    const { wrapper } = await mountSetup()
    await wrapper.get('input[type=password]').setValue('short')
    expect(wrapper.text()).toContain('At least 8 characters')
    expect(wrapper.get('[data-test=next]').attributes('disabled')).toBeDefined()
  })

  it('posts the chosen options and goes home', async () => {
    const { wrapper, router } = await mountSetup()
    const pws = wrapper.findAll('input[type=password]')
    await pws[0].setValue('longenough1')
    await pws[1].setValue('longenough1')
    await wrapper.get('[data-test=next]').trigger('click')
    await flushPromises()
    // Generic is unchecked by default; everything else checked.
    await wrapper.get('[data-test=next]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test=finish]').trigger('click')
    await flushPromises()
    const post = fetchMock.mock.calls.find(([u, i]) => u.endsWith('/setup') && i?.method === 'POST')!
    expect(JSON.parse(post[1].body)).toEqual({
      auth_mode: 'password',
      username: 'admin',
      password: 'longenough1',
      packs: ['electronics'],
    })
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('submits No login without a password', async () => {
    const { wrapper, router } = await mountSetup()
    await wrapper.findAll('input[type=radio]')[1].setValue(true)
    expect(wrapper.find('input[type=password]').exists()).toBe(false)
    await wrapper.get('[data-test=next]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test=next]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test=finish]').trigger('click')
    await flushPromises()
    const post = fetchMock.mock.calls.find(([u, i]) => u.endsWith('/setup') && i?.method === 'POST')!
    expect(JSON.parse(post[1].body)).toEqual({ auth_mode: 'none', username: 'admin', packs: ['electronics'] })
    expect(router.currentRoute.value.path).toBe('/')
  })
})
