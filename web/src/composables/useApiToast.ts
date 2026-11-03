import { useToast } from 'primevue/usetoast'

/** Toast helpers; errors show the server's own message (ApiError.message). */
export function useApiToast() {
  const toast = useToast()
  return {
    error(e: unknown, fallback = 'Request failed') {
      toast.add({ severity: 'error', summary: e instanceof Error ? e.message : fallback, life: 6000 })
    },
    success(message: string) {
      toast.add({ severity: 'success', summary: message, life: 3000 })
    },
  }
}
