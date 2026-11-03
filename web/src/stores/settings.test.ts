import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSession } from './session'
import { useSettings } from './settings'

const PUBLIC = { 'auth.mode': 'password', 'display.theme': 'system' }
const FULL = { ...PUBLIC, 'display.theme': 'dark', 'backup.keep': 14 }

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
}

describe('settings across auth changes', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.endsWith('/settings/public')) return json(PUBLIC)
        if (url.endsWith('/settings')) return json(FULL)
        return json({ ok: true })
      }),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('reloads the full settings after login', async () => {
    const settings = useSettings()
    await settings.load()
    expect(settings.get('backup.keep')).toBeUndefined()
    await useSession().login('admin', 'pw')
    await vi.waitFor(() => expect(settings.get('backup.keep')).toBe(14))
  })

  it('drops back to the public subset on logout', async () => {
    const session = useSession()
    const settings = useSettings()
    await session.login('admin', 'pw')
    await vi.waitFor(() => expect(settings.get('backup.keep')).toBe(14))
    vi.doMock('../router', () => ({ default: { push: vi.fn() } }))
    await session.logout()
    expect(settings.get('backup.keep')).toBeUndefined()
    expect(settings.get('display.theme')).toBe('system')
  })
})
