import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiFetch } from '../api/client'
import { useSession } from './session'

export const useSettings = defineStore('settings', () => {
  const values = ref<Record<string, unknown>>({})

  /** Public settings always; the full set too when logged in (or login is off). */
  async function load(): Promise<void> {
    const merged = await apiFetch<Record<string, unknown>>('/settings/public')
    const session = useSession()
    if (session.authenticated || session.mode === 'none') {
      Object.assign(merged, await apiFetch<Record<string, unknown>>('/settings'))
    }
    values.value = merged
  }

  function get<T = unknown>(key: string, fallback?: T): T {
    return (key in values.value ? values.value[key] : fallback) as T
  }

  return { values, load, get }
})
