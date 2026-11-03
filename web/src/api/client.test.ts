import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch, setUnauthenticatedHandler } from './client'

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('apiFetch', () => {
  it('prefixes /api/v1 and sends JSON', async () => {
    const fetch = mockFetch(200, { ok: true })
    await expect(apiFetch('/items', { method: 'POST', json: { name: 'x' } })).resolves.toEqual({ ok: true })
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/items')
    expect(init.body).toBe('{"name":"x"}')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.credentials).toBe('same-origin')
  })

  it('parses validation errors into ApiError.fields', async () => {
    mockFetch(422, { error: 'validation', message: 'Validation failed', fields: { name: 'Required' } })
    const err = (await apiFetch('/items').catch((e) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.fields).toEqual({ name: 'Required' })
  })

  it('calls the unauthenticated handler on 401', async () => {
    const handler = vi.fn()
    setUnauthenticatedHandler(handler)
    mockFetch(401, { error: 'unauthenticated', message: 'Please log in' })
    await expect(apiFetch('/categories')).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledOnce()
  })

  it('returns undefined for 204', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(apiFetch('/items/1', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})
