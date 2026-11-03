import { defineStore } from 'pinia'
import { ref } from 'vue'

import { apiFetch } from '@/api/client'
import type { AuthStatus } from '@/api/types'

export const useSession = defineStore('session', () => {
  const loaded = ref(false)
  const mode = ref<'password' | 'none'>('password')
  const authenticated = ref(false)
  const setupCompleted = ref(false)
  const username = ref<string | null>(null)

  function apply(s: AuthStatus) {
    mode.value = s.mode as 'password' | 'none'
    authenticated.value = s.authenticated
    setupCompleted.value = s.setup_completed
    username.value = s.username ?? null
    loaded.value = true
  }

  async function load() {
    apply(await apiFetch<AuthStatus>('/auth/status'))
  }

  async function login(user: string, password: string) {
    apply(await apiFetch<AuthStatus>('/auth/login', { method: 'POST', json: { username: user, password } }))
  }

  async function logout() {
    await apiFetch('/auth/logout', { method: 'POST' })
    authenticated.value = false
  }

  function onUnauthenticated() {
    authenticated.value = false
  }

  return { loaded, mode, authenticated, setupCompleted, username, apply, load, login, logout, onUnauthenticated }
})
