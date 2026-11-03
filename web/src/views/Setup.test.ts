import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountWithPlugins, stubApi } from '@/test-utils'

import Setup from './Setup.vue'

const push = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

const PACKS = [
  { id: 'electronics', name: 'Electronics', description: '', category_count: 3 },
  { id: 'generic', name: 'Generic', description: '', category_count: 1 },
]
const STATUS = { mode: 'password', authenticated: true, setup_completed: true, username: 'admin' }

afterEach(() => vi.unstubAllGlobals())

describe('Setup wizard', () => {
  it('requires 8 characters before Next', async () => {
    stubApi({ '/packs': PACKS })
    const w = mountWithPlugins(Setup)
    await w.get('[data-test=password]').setValue('short')
    await w.get('[data-test=confirm]').setValue('short')
    expect(w.text()).toContain('At least 8 characters')
    expect(w.get('[data-test=next]').attributes('disabled')).toBeDefined()
  })

  it('posts the chosen login and packs', async () => {
    const fetch = stubApi({ '/packs': PACKS, 'POST /setup': STATUS })
    const w = mountWithPlugins(Setup)
    await flushPromises()
    await w.get('[data-test=password]').setValue('correct horse')
    await w.get('[data-test=confirm]').setValue('correct horse')
    await w.get('[data-test=next]').trigger('click')
    await w.get('[data-test=next]').trigger('click')
    await w.get('[data-test=finish]').trigger('click')
    await flushPromises()
    const call = fetch.mock.calls.find(([url]) => String(url).endsWith('/setup'))!
    expect(JSON.parse(call[1]!.body as string)).toEqual({
      auth_mode: 'password',
      username: 'admin',
      password: 'correct horse',
      packs: ['electronics'],
    })
    expect(push).toHaveBeenCalledWith('/')
  })

  it('allows no login', async () => {
    const fetch = stubApi({ '/packs': PACKS, 'POST /setup': { ...STATUS, mode: 'none' } })
    const w = mountWithPlugins(Setup)
    await flushPromises()
    await w.get('[data-test=mode-none]').trigger('click')
    await w.get('[data-test=next]').trigger('click')
    await w.get('[data-test=next]').trigger('click')
    await w.get('[data-test=finish]').trigger('click')
    await flushPromises()
    const call = fetch.mock.calls.find(([url]) => String(url).endsWith('/setup'))!
    expect(JSON.parse(call[1]!.body as string)).toEqual({ auth_mode: 'none', packs: ['electronics'] })
  })
})
