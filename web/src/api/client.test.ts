import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiFetch } from './client'
import { useSession } from '../stores/session'

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  )
}

describe('apiFetch', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.unstubAllGlobals())

  it('prefixes /api/v1, sends JSON and returns the parsed body', async () => {
    const fetchMock = respond(200, { ok: true })
    vi.stubGlobal('fetch', fetchMock)
    const out = await apiFetch<{ ok: boolean }>('/things', { method: 'POST', json: { a: 1 } })
    expect(out).toEqual({ ok: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/things')
    expect(init.credentials).toBe('same-origin')
    expect(init.body).toBe('{"a":1}')
    expect(new Headers(init.headers).get('content-type')).toBe('application/json')
  })

  it('populates ApiError.fields from a 422', async () => {
    vi.stubGlobal(
      'fetch',
      respond(422, { error: 'validation', message: 'Validation failed', fields: { name: 'required' } }),
    )
    const err = (await apiFetch('/things').catch((e) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.error).toBe('validation')
    expect(err.fields).toEqual({ name: 'required' })
  })

  it('calls session.onUnauthenticated on 401', async () => {
    vi.stubGlobal('fetch', respond(401, { error: 'unauthenticated', message: 'Login required' }))
    const session = useSession()
    const spy = vi.spyOn(session, 'onUnauthenticated').mockImplementation(() => {})
    await expect(apiFetch('/items')).rejects.toBeInstanceOf(ApiError)
    expect(spy).toHaveBeenCalledOnce()
  })
})
