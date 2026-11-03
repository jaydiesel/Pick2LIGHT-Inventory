import { defineStore } from 'pinia'
import { ref } from 'vue'

import { apiFetch } from '@/api/client'

export type Settings = Record<string, unknown>

export const useSettings = defineStore('settings', () => {
  const values = ref<Settings>({})

  async function load(full = false) {
    values.value = await apiFetch<Settings>(full ? '/settings' : '/settings/public')
  }

  async function save(changes: Settings) {
    values.value = await apiFetch<Settings>('/settings', { method: 'PATCH', json: changes })
  }

  function get<T>(key: string, fallback: T): T {
    return (key in values.value ? values.value[key] : fallback) as T
  }

  return { values, load, save, get }
})
