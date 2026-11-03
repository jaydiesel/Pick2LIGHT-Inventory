import { mount, type ComponentMountingOptions } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ConfirmationService from 'primevue/confirmationservice'
import ToastService from 'primevue/toastservice'
import { vi } from 'vitest'
import type { Component } from 'vue'

/** Mount with the same global plugins the app installs (PrimeVue, toasts, confirm, pinia). */
export function mountWithPlugins<C extends Component>(component: C, options: ComponentMountingOptions<C> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(component, {
    ...options,
    global: {
      ...(options.global ?? {}),
      plugins: [pinia, [PrimeVue, { unstyled: true }], ToastService, ConfirmationService, ...(options.global?.plugins ?? [])],
      stubs: { RouterLink: { template: '<a><slot /></a>' }, ...(options.global?.stubs ?? {}) },
    },
  } as ComponentMountingOptions<C>)
}

type Handler = (url: string, init: RequestInit) => unknown | Promise<unknown>

/** Stub fetch with a URL → JSON body router; returns the vi.fn so calls can be asserted. */
export function stubApi(routes: Record<string, unknown | Handler>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = (init.method || 'GET').toUpperCase()
    const key = Object.keys(routes).find((k) => {
      const [m, p] = k.includes(' ') ? k.split(' ', 2) : ['GET', k]
      return m === method && (url === `/api/v1${p}` || url.startsWith(`/api/v1${p}?`))
    })
    if (!key) return new Response(JSON.stringify({ error: 'not_found', message: `${method} ${url}` }), { status: 404 })
    const value = routes[key]
    const body = typeof value === 'function' ? await (value as Handler)(url, init) : value
    if (body instanceof Response) return body
    if (body === undefined) return new Response(null, { status: 204 })
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

export function errorResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}
