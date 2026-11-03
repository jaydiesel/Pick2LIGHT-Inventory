import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiFetch } from '../api/client'

interface AuthStatus {
  mode: 'password' | 'none'
  authenticated: boolean
  setup_completed: boolean
}

export const useSession = defineStore('session', () => {
  const mode = ref<'password' | 'none'>('password')
  const authenticated = ref(false)
  const setupCompleted = ref(false)
  const loaded = ref(false)

  async function load(): Promise<void> {
    const status = await apiFetch<AuthStatus>('/auth/status')
    mode.value = status.mode
    authenticated.value = status.authenticated
    setupCompleted.value = status.setup_completed
    loaded.value = true
  }

  async function login(username: string, password: string): Promise<void> {
    await apiFetch('/auth/login', { method: 'POST', json: { username, password } })
    authenticated.value = true
  }

  async function logout(): Promise<void> {
    await apiFetch('/auth/logout', { method: 'POST' })
    authenticated.value = false
    const { default: router } = await import('../router')
    await router.push('/login')
  }

  /** Called by the API client on any 401: forget the session and go to the login page. */
  function onUnauthenticated(): void {
    authenticated.value = false
    void import('../router').then(({ default: router }) => {
      const current = router.currentRoute.value
      if (current.path === '/login' || current.path === '/setup') return
      return router.push({ path: '/login', query: { next: current.fullPath } })
    })
  }

  return { mode, authenticated, setupCompleted, loaded, load, login, logout, onUnauthenticated }
})
